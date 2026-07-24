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
		# resolver AND the admin check (via _is_admin) so the guard fires
		# without needing to create a real non-admin user (avoids the email-queue
		# side-effect that breaks subsequent tests on this site).
		import lms_saas.api.staff as staff
		import lms_saas.api.manager as manager

		original_branch = staff.get_current_user_branch
		original_is_admin = manager._is_admin
		try:
			staff.get_current_user_branch = lambda: "Branch A"
			manager._is_admin = lambda: False
			with self.assertRaises(frappe.PermissionError):
				_assert_branch_scope("Branch B")
			# Same branch -> allowed.
			_assert_branch_scope("Branch A")
		finally:
			staff.get_current_user_branch = original_branch
			manager._is_admin = original_is_admin

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
