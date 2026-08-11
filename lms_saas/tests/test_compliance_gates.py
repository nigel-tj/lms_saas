import frappe
from frappe.tests.utils import FrappeTestCase


class TestComplianceGates(FrappeTestCase):
	def test_aml_config_defaults(self):
		from lms_saas.api.aml import _aml_config

		cfg = _aml_config()
		self.assertIn("enabled", cfg)
		self.assertIn("require_clear", cfg)

	def test_aml_normalize_status(self):
		from lms_saas.api.aml import _normalize_aml_status

		self.assertEqual(_normalize_aml_status("pass"), "Clear")
		self.assertEqual(_normalize_aml_status("Flagged"), "Flagged")

	def test_decisioning_compare(self):
		from lms_saas.api.decisioning import _compare

		self.assertTrue(_compare(700, ">=", 600))
		self.assertFalse(_compare(500, ">=", 600))

	def test_payment_adapters_registered(self):
		from lms_saas.api.payments.service import ADAPTERS

		self.assertIn("ecocash", ADAPTERS)
		self.assertIn("onemoney", ADAPTERS)
		self.assertIn("bank_transfer", ADAPTERS)

	def test_aml_default_is_fail_closed(self):
		"""B5: AML must default to fail-CLOSED so a provider outage cannot
		silently clear a borrower for origination. Sandbox fail-open is an
		explicit opt-in via lms_sandbox_end_date or lms_compliance_relaxed.
		"""
		from lms_saas.api.aml import _aml_config
		from lms_saas.api.compliance_config import get_effective_compliance_config

		# Production mode (no sandbox date, no relax flags) — fail-CLOSED.
		frappe.conf.pop("lms_sandbox_end_date", None)
		frappe.conf.pop("lms_compliance_relaxed", None)
		frappe.conf.pop("lms_aml_block_on_error", None)
		cfg = _aml_config()
		effective = get_effective_compliance_config()
		self.assertTrue(
			cfg["block_on_error"],
			"B5: AML must default to fail-CLOSED (provider outage blocks origination)",
		)
		self.assertTrue(
			effective.get("lms_aml_block_on_error"),
			"B5: effective compliance config must also be fail-CLOSED in production",
		)

		# Sandbox mode — fail-OPEN so seeding smoke tests can run.
		frappe.conf["lms_sandbox_end_date"] = "2099-12-31"
		try:
			cfg = _aml_config()
			self.assertFalse(
				cfg["block_on_error"],
				"B5: AML must be fail-OPEN in sandbox mode (operator opt-in)",
			)
		finally:
			frappe.conf.pop("lms_sandbox_end_date", None)

	def test_bureau_default_is_fail_closed(self):
		"""B17: credit bureau must default to fail-CLOSED so a provider
		outage cannot silently skip the credit-score gate at origination.
		"""
		from lms_saas.api.underwriting import _bureau_config
		from lms_saas.api.compliance_config import get_effective_compliance_config

		frappe.conf.pop("lms_sandbox_end_date", None)
		frappe.conf.pop("lms_credit_bureau_block_on_error", None)
		cfg = _bureau_config()
		effective = get_effective_compliance_config()
		self.assertTrue(
			cfg["block_on_error"],
			"B17: bureau must default to fail-CLOSED",
		)
		self.assertTrue(
			effective.get("lms_credit_bureau_block_on_error"),
			"B17: effective compliance config must also be fail-CLOSED in production",
		)

	def test_bureau_score_applicant_refuses_when_disabled(self):
		"""B17: score_applicant must refuse when the bureau is not enabled,
		rather than echoing the config as if it were a score.
		"""
		from lms_saas.api.integrations import bureau

		frappe.conf["lms_credit_bureau_enabled"] = False
		frappe.conf["lms_credit_bureau_url"] = None
		# Bypass the API key check by stubbing it.
		import unittest.mock as _mock
		with _mock.patch.object(bureau, "validate_api_key", lambda: None):
			with self.assertRaises(frappe.exceptions.PermissionError):
				bureau.score_applicant(customer="NONE")

	def test_bureau_score_applicant_refuses_when_no_url(self):
		"""B17: score_applicant must refuse when bureau is enabled but no
		URL is configured, rather than echoing the config.
		"""
		from lms_saas.api.integrations import bureau

		frappe.conf["lms_credit_bureau_enabled"] = True
		frappe.conf["lms_credit_bureau_url"] = None
		import unittest.mock as _mock
		with _mock.patch.object(bureau, "validate_api_key", lambda: None):
			with self.assertRaises(frappe.exceptions.ValidationError):
				bureau.score_applicant(customer="NONE")

	def test_required_apps_pin_versions(self):
		"""B19: required_apps must declare major-version pins so a site on
		Frappe 14 cannot install this app (which uses the popover API and
		newer loan Repayment Schedule schema)."""
		from lms_saas import hooks

		apps = hooks.required_apps
		self.assertIsInstance(apps, list)
		self.assertGreater(len(apps), 0)
		for entry in apps:
			if isinstance(entry, dict):
				self.assertIn("name", entry)
				self.assertIn("version", entry)
				# Version pin must be a non-empty constraint string.
				self.assertTrue(entry["version"])

	def test_four_eyes_enforced_by_default(self):
		"""B5: four-eyes must be ON unless the site explicitly opts into relaxed mode."""
		from lms_saas.api.compliance import enforce_four_eyes

		# Default (no relaxed flag): a maker cannot self-approve.
		frappe.conf["lms_compliance_relaxed"] = False
		doc = frappe._dict(doctype="Loan Disbursement", name="DISC-TEST", owner="maker_user")
		frappe.session.user = "maker_user"
		with self.assertRaises(frappe.exceptions.ValidationError):
			enforce_four_eyes(doc, None)

		# Relaxed mode: control is lifted (sandbox/testing only).
		frappe.conf["lms_compliance_relaxed"] = True
		try:
			enforce_four_eyes(doc, None)
		except frappe.exceptions.ValidationError:
			self.fail("four-eyes should be relaxed when lms_compliance_relaxed=True")
		finally:
			frappe.conf["lms_compliance_relaxed"] = False
			frappe.session.user = "Administrator"

	def test_branch_scope_rejects_cross_branch(self):
		"""B21: a manager may not read a customer in another branch."""
		from lms_saas.api.manager import _assert_branch_scope

		# NOTE: branch-scope checks BYPASS for System Manager / Administrator by
		# design. The test must use a non-admin LMS Portal Staff user to exercise
		# the actual branch-scope guard. We monkey-patch both the branch
		# resolver AND the admin check (via is_admin in utils.access_control,
		# which is the single source of truth post-R54) so the guard fires
		# without needing to create a real non-admin user (avoids the email-queue
		# side-effect that breaks subsequent tests on this site).
		import lms_saas.api.staff as staff
		from lms_saas.utils import access_control

		original_branch = staff.get_current_user_branch
		original_is_admin = access_control.is_admin
		try:
			staff.get_current_user_branch = lambda: "Branch A"
			access_control.is_admin = lambda: False
			with self.assertRaises(frappe.PermissionError):
				_assert_branch_scope("Branch B")
			# Same branch -> allowed.
			_assert_branch_scope("Branch A")
		finally:
			staff.get_current_user_branch = original_branch
			access_control.is_admin = original_is_admin

	def _make_staff_user_with_branch(self, branch):
		"""Create a non-admin LMS Portal Staff user (no System Manager) so the
		branch-scope guard actually fires."""
		email = f"{branch.lower().replace(' ', '')}.staff@example.com"
		if frappe.db.exists("User", email):
			return email
		# Ensure LMS Portal Staff role exists
		if not frappe.db.exists("Role", "LMS Portal Staff"):
			frappe.get_doc({"doctype": "Role", "role_name": "LMS Portal Staff"}).insert(
				ignore_permissions=True
			)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": branch,
				"roles": [{"role": "LMS Portal Staff"}],
			}
		)
		user.insert(ignore_permissions=True)
		return user.name

	def _make_user_with_branch(self, branch):
		# Legacy helper retained for backward compat — creates a System Manager
		# (which bypasses branch-scope, so it's only useful for admin-override tests).
		email = f"{branch.lower().replace(' ', '')}@example.com"
		if frappe.db.exists("User", email):
			return email
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": branch,
				"roles": [{"role": "System Manager"}],
			}
		)
		user.insert(ignore_permissions=True)
		return user.name
