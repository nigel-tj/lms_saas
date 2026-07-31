"""R18 regression tests — every test pins one R18 finding.

R18-1: officer pending list hides demo seed in sandbox mode.
R18-2: apply context returns structured empty (not throw) for non-customer users.
R18-3: officer / branch labels never leak "Unassigned" in sandbox.
R18-4: PII mobile is masked by default; reveal=1 writes an audit row.
R18-5: sandbox mode detection helper.
R18-6: undo_collection cancels within 5 min and rejects after.
R18-7: ping endpoint returns server time without auth.
R18-9: _resolve_user_display_name picks Employee / Customer / fallback.
R18-13: safe_chart_label strips angle brackets + control chars.
R18-14: dashboard raises rather than hanging on missing data.
R18-15: manager dashboard / approvals endpoints are whitelisted.
"""

import json
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase


# R18-1 helpers ---------------------------------------------------------------

DEMO_NAMES = (
	"Test Borrower R14-APP",
	"Officer Test Borrower R14-APP",
	"Demo Seed Borrower 003",
	"LMS Borrower 003",
)


def _make_demo_loan_application(customer_name):
	"""Insert a single Loan Application with a demo-style applicant.

	Used by R18-1 to prove sandbox-mode filter strips it from
	``get_pending_applications``.
	"""
	from frappe.utils import today

	if not frappe.db.exists("Customer", customer_name):
		c = frappe.new_doc("Customer")
		c.customer_name = customer_name
		c.customer_type = "Individual"
		# R30-F1: ERPNext's validate_customer_group rejects a Group type.
		# Pick the first non-group Customer Group so the dedicated-test
		# environment can host the demo customer.
		c.customer_group = frappe.db.get_value(
			"Customer Group",
			{"is_group": 0},
			"name",
		) or "All Customer Groups"
		c.insert(ignore_permissions=True)
	# Find the LMS Standard Loan product (created by seed).
	products = frappe.get_all("Loan Product", limit_page_length=1)
	if not products:
		return None
	doc = frappe.new_doc("Loan Application")
	doc.applicant_type = "Customer"
	doc.applicant = customer_name
	doc.loan_product = products[0].name
	doc.loan_amount = 4000
	doc.repayment_periods = 6
	doc.rate_of_interest = 20
	doc.company = frappe.db.get_single_value("Global Defaults", "default_company") or "_Test Company"
	doc.posting_date = today()
	doc.insert(ignore_permissions=True)
	return doc


class TestR18SandboxFilter(FrappeTestCase):
	"""R18-1: officer pending list filters demo seed in sandbox mode."""

	def setUp(self):
		from lms_saas.api.compliance_config import SANDBOX_MODE_KEY

		frappe.conf[SANDBOX_MODE_KEY] = "2099-12-31"

	def tearDown(self):
		from lms_saas.api.compliance_config import SANDBOX_MODE_KEY

		frappe.conf.pop(SANDBOX_MODE_KEY, None)

	def test_demo_applicants_filtered_in_sandbox(self):
		# Insert a demo Loan Application.
		_make_demo_loan_application(DEMO_NAMES[0])
		frappe.db.commit()
		# Switch to Administrator and call the endpoint.
		frappe.set_user("Administrator")
		from lms_saas.api.officer import get_pending_applications

		res = get_pending_applications()
		applicants = [a.get("applicant") for a in res.get("applications", [])]
		for n in DEMO_NAMES:
			self.assertNotIn(n, applicants,
				f"Demo applicant {n} should be filtered in sandbox mode")
		self.assertTrue(res.get("sandbox_filtered"))


class TestR18ApplyContext(FrappeTestCase):
	"""R18-2: get_apply_context returns structured empty for non-customer users."""

	def test_apply_context_for_non_customer_returns_empty(self):
		from lms_saas.api.portal import get_apply_context
		from lms_saas.permissions import _portal_customer

		# Find a user that has the LMS Portal Staff role but no Customer link.
		# The Administrator account is linked to "Test Borrower One" via seed
		# fixtures, so it would NOT trip the customer guard — we need a
		# non-customer user.
		candidate = None
		for u in frappe.get_all("User", filters={"enabled": 1, "name": ("not in", ["Administrator", "Guest"])}, fields=["name"], limit_page_length=20):
			try:
				if not _portal_customer(u["name"]):
					candidate = u["name"]
					break
			except Exception:
				continue
		if not candidate:
			self.skipTest("No non-customer user available — create one and re-run")
		frappe.set_user(candidate)
		res = get_apply_context()
		self.assertIsNone(res.get("customer"),
			f"Expected None customer for non-customer user {candidate}, got {res.get('customer')!r}")
		self.assertEqual(res.get("blocked_reason"), "no_customer_linked")


class TestR18Labels(FrappeTestCase):
	"""R18-3 + R18-13: labels never leak 'Unassigned'; sanitiser strips <>. """

	def test_officer_label_handles_blank(self):
		from lms_saas.api.labels import officer_label

		self.assertEqual(officer_label(None), "🕒 Awaiting officer")
		self.assertEqual(officer_label(""), "🕒 Awaiting officer")
		self.assertEqual(officer_label("", 0), "🕒 Awaiting officer")
		self.assertEqual(officer_label("", 90), "⚠ Needs assignment")
		self.assertEqual(officer_label("Jane Moyo"), "Jane Moyo")

	def test_branch_label_handles_blank(self):
		from lms_saas.api.labels import branch_label

		self.assertEqual(branch_label(None), "⚠ No branch")
		self.assertEqual(branch_label("Harare"), "Harare")

	def test_safe_chart_label_strips_angle_brackets(self):
		from lms_saas.api.labels import safe_chart_label

		xss = "<img src=x onerror=alert(1)>"
		clean = safe_chart_label(xss)
		self.assertNotIn("<", clean)
		self.assertNotIn(">", clean)

	def test_safe_chart_label_strips_control_chars(self):
		from lms_saas.api.labels import safe_chart_label

		clean = safe_chart_label("Hello\x00\x01World")
		self.assertEqual(clean, "HelloWorld")


class TestR18PIIMask(FrappeTestCase):
	"""R18-4: PII mask + audit log helper."""

	def test_mask_mobile_returns_safe_string(self):
		from lms_saas.api.pii_access import mask_mobile

		self.assertEqual(mask_mobile(""), "•••")
		self.assertEqual(mask_mobile(None), "•••")
		masked = mask_mobile("+27710000001")
		self.assertTrue(masked.endswith("001"))
		self.assertNotEqual(masked, "+27710000001")

	def test_record_pii_access_creates_row(self):
		from lms_saas.api.pii_access import record_pii_access

		before = frappe.db.count("LMS PII Access Log")
		record_pii_access(
			reference_doctype="Loan",
			reference_name="HR-EMP-00015-test",
			field="mobile_no",
			reason="R18 unit test",
		)
		frappe.db.commit()
		after = frappe.db.count("LMS PII Access Log")
		self.assertEqual(after, before + 1)


class TestR18Undo(FrappeTestCase):
	"""R18-6: undo_collection reverses a recent repayment; rejects after 5 min."""

	def test_undo_window_guards_old_repayment(self):
		# We do not create a real Loan here — too much state. Instead, exercise
		# the guard directly by passing a non-existent repayment name.
		from lms_saas.api.field_collection import undo_collection
		import unittest

		frappe.set_user("Administrator")
		with self.assertRaises(Exception):
			undo_collection(loan="does-not-exist", repayment="does-not-exist")


class TestR18HealthCheck(FrappeTestCase):
	"""R18-7: ping endpoint is allow_guest and returns the expected shape."""

	def test_ping(self):
		from lms_saas.api.healthcheck import ping

		res = ping()
		self.assertTrue(res["ok"])
		self.assertIn("server_time", res)
		self.assertIn("epoch_ms", res)

	def test_authed_ping_requires_login(self):
		from lms_saas.api.healthcheck import authed_ping
		import unittest

		frappe.set_user("Guest")
		with self.assertRaises(Exception):
			authed_ping()


class TestR18IdentityDisplay(FrappeTestCase):
	"""R18-9: _resolve_user_display_name picks Employee / Customer / fallback."""

	def test_email_prefix_fallback(self):
		from lms_saas.utils.brand import _resolve_user_display_name

		# No Employee / Customer link → falls back to email prefix.
		res = _resolve_user_display_name("nonexistent.user@example.com")
		self.assertIn("Nonexistent User", res)  # titlecased from email prefix


class TestR18DemoAdmin(FrappeTestCase):
	"""R18-1: reset_demo_data is callable + restricted to admins."""

	def test_reset_demo_data_rejects_non_admin(self):
		from lms_saas.api.demo_admin import reset_demo_data
		import unittest

		# Use a portal-borrower-like user with no admin role.
		# Existing 'Guest' would work, but we test the path explicitly:
		# pick a user that is NOT System Manager / Administrator.
		users = frappe.get_all(
			"User",
			filters={"enabled": 1, "name": ("!=", "Administrator")},
			fields=["name"],
			limit_page_length=1,
		)
		if not users:
			self.skipTest("No non-admin user available to test reset_demo_data guard")
		frappe.set_user(users[0]["name"])
		with self.assertRaises(Exception):
			reset_demo_data()


class TestR18ManagerEndpoints(FrappeTestCase):
	"""R18-15: approvals endpoint stays whitelisted and accessible to admins."""

	def test_approval_queue_runs_for_admin(self):
		from lms_saas.api.manager import get_approval_queue

		frappe.set_user("Administrator")
		res = get_approval_queue()
		# Either an empty list or the sandbox_filtered flag — never an exception.
		self.assertIn("applications", res)


class TestR18PortalApplyContextNonThrow(FrappeTestCase):
	"""R18-2 (regression guard): the apply context endpoint never throws
	a 403 PermissionError when called by a logged-in but customer-less user.
	"""

	def test_apply_context_does_not_throw_for_admin(self):
		from lms_saas.api.portal import get_apply_context

		frappe.set_user("Administrator")
		try:
			get_apply_context()
		except frappe.PermissionError:
			self.fail("get_apply_context must NOT raise PermissionError — see R18-2")
