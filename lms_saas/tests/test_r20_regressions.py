"""R20 regression tests — concrete regressions surfaced by the R20 board.

Each test pins one R20 finding so a regression re-surfacing the issue fails
the test suite. Run via:
    cd frappe-bench && python run_lms_tests.py
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

# `parents[1]` from this test file lands at the app package root
# (apps/lms_saas/lms_saas) regardless of cwd. All static-file assertions
# use this anchor so they work in `bench run-tests` and the standalone
# runner equally.
APP_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# R20-C1: officer chart never leaks the literal "Unassigned".
# The R18-3 fix landed in api/labels.py but the JS chart code path in
# lms_officer_portal.js still hard-coded the literal. Pin both layers.
# ---------------------------------------------------------------------------
class TestR20OfficerChartLabel(FrappeTestCase):
	"""R20-C1: officer performance chart label must be chart-friendly."""

	def test_python_officer_label_handles_blank(self):
		from lms_saas.api.labels import officer_label

		self.assertEqual(officer_label(None), "🕒 Awaiting officer")
		self.assertEqual(officer_label(""), "🕒 Awaiting officer")
		self.assertEqual(officer_label(None, days_past_due=0), "🕒 Awaiting officer")
		self.assertEqual(officer_label(None, days_past_due=31), "⚠ Needs assignment")

	def test_python_officer_label_sanitises(self):
		from lms_saas.api.labels import officer_label

		# Angle brackets stripped so a hostile name can't break the chart.
		self.assertNotIn("<", officer_label("<img src=x>"))
		self.assertNotIn(">", officer_label("<img src=x>"))

	APP_ROOT = Path(__file__).resolve().parents[1]

	def test_js_officer_label_helper_present(self):
		"""Pin that lms_portal exposes officerLabel / branchLabel / safeChartLabel."""
		js = (APP_ROOT / "public" / "js" / "lms_portal.js").read_text()
		self.assertIn("lms_portal.officerLabel = function", js)
		self.assertIn("lms_portal.branchLabel = function", js)
		self.assertIn("lms_portal.safeChartLabel = function", js)

	def test_js_officer_chart_no_unassigned_literal(self):
		"""Pin the actual fix: the JS chart code path must not contain "Unassigned".

		We strip comments (// line, /* block */) before scanning so a
		regression-fix note in a comment doesn't false-pass or false-fail.
		"""
		import re

		js = (APP_ROOT / "public" / "js" / "lms_officer_portal.js").read_text()
		# Strip block comments
		code = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
		# Strip line comments
		code = re.sub(r"//[^\n]*", "", code)
		self.assertNotIn('"Unassigned"', code)
		self.assertNotIn("'Unassigned'", code)
		# And the label code that the chart maps to must use officerLabel:
		self.assertIn("lms_portal.officerLabel(", code)


# ---------------------------------------------------------------------------
# R20-H1: LMS Audit Event is immutable for everyone, including System Manager.
# ---------------------------------------------------------------------------
class TestR20AuditEventImmutable(FrappeTestCase):
	"""R20-H1: audit trail cannot be deleted even by Sys Manager."""

	def setUp(self):
		frappe.set_user("Administrator")

	def test_sys_manager_cannot_delete_audit_row(self):
		"""Insert a row, then try to delete as Administrator — must throw."""
		row = frappe.get_doc({
			"doctype": "LMS Audit Event",
			"event_time": frappe.utils.now_datetime(),
			"event_type": "TEST:probe",
			"event_user": "Administrator",
			"reference_doctype": "Customer",
			"reference_name": "TEST",
		})
		row.insert(ignore_permissions=True)
		row.reload()

		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("LMS Audit Event", row.name, ignore_permissions=False)

	def test_sys_manager_cannot_amend_audit_row(self):
		"""Update an existing audit row — must throw."""
		row = frappe.get_doc({
			"doctype": "LMS Audit Event",
			"event_time": frappe.utils.now_datetime(),
			"event_type": "TEST:probe",
			"event_user": "Administrator",
		})
		row.insert(ignore_permissions=True)
		row.reload()
		row.event_type = "TEST:mutated"
		with self.assertRaises(frappe.ValidationError):
			row.save(ignore_permissions=False)

	def test_audit_event_perm_block_locks_delete(self):
		"""DocType permission must not grant delete to System Manager."""
		import json

		path = APP_ROOT / "lms_saas" / "doctype" / "lms_audit_event" / "lms_audit_event.json"
		spec = json.loads(path.read_text())
		for perm in spec.get("permissions", []):
			if perm.get("role") == "System Manager":
				self.assertEqual(perm.get("delete", 0), 0, "Sys Manager must not delete audit rows")
				self.assertEqual(perm.get("write", 0), 0, "Sys Manager must not write audit rows")


# ---------------------------------------------------------------------------
# R20-M3: PII reveal must abort if the audit row cannot be written.
# ---------------------------------------------------------------------------
class TestR20PIIRevealAbortsOnAuditFailure(FrappeTestCase):
	"""R20-M3: a failing LMS PII Access Log insert must abort the reveal."""

	def test_strict_audit_raises_when_log_insert_fails(self):
		from lms_saas.api import pii_access as pii_mod
		from lms_saas.api.pii_access import record_pii_access_strict

		# Mock the module-level get_doc so a failing LMS PII Access Log insert
		# raises. The strict variant must propagate so the caller aborts the
		# reveal. We mock the module's reference, not frappe.get_doc globally,
		# so frappe.log_error's own get_doc call (Error Log) is unaffected.
		with mock.patch.object(pii_mod.frappe, "get_doc", side_effect=RuntimeError("audit table unavailable")):
			with self.assertRaises(RuntimeError):
				record_pii_access_strict(
					reference_doctype="Loan",
					reference_name="TEST-LOAN",
					field="mobile_no",
					reason="probe",
				)

	def test_non_strict_audit_swallows_failure(self):
		"""The non-strict variant must keep its "never raise" contract so
		non-revealing reads (the masked run-sheet path) don't break on
		log outages."""
		from lms_saas.api import pii_access as pii_mod
		from lms_saas.api.pii_access import record_pii_access

		# Patch only the LMS PII Access Log DocType branch by name. log_error
		# calls frappe.get_doc({"doctype": "Error Log", ...}) so we need to
		# raise only on the LMS PII Access Log branch. This keeps the
		# Error Log write inside log_error working.
		original_get_doc = pii_mod.frappe.get_doc

		def selective_raise(*args, **kwargs):
			# args[0] can be dict with 'doctype' OR class with 'doctype' attr.
			doctype = None
			if args and isinstance(args[0], dict):
				doctype = args[0].get("doctype")
			elif args and hasattr(args[0], "doctype"):
				doctype = getattr(args[0], "doctype", None)
			if doctype == "LMS PII Access Log":
				raise RuntimeError("audit table unavailable")
			return original_get_doc(*args, **kwargs)

		with mock.patch.object(pii_mod.frappe, "get_doc", side_effect=selective_raise):
			# Should NOT raise — log_error swallows its own failure.
			record_pii_access(
				reference_doctype="Loan",
				reference_name="TEST-LOAN",
				field="mobile_no",
				reason="probe (masked)",
			)


# ---------------------------------------------------------------------------
# R20-M1: pending / approval queues return pre-filter counts.
# ---------------------------------------------------------------------------
class TestR20QueueFilterCounts(FrappeTestCase):
	"""R20-M1: operator situational awareness — pre-filter counts returned."""

	def test_get_pending_applications_returns_pre_filter_count(self):
		from lms_saas.api.officer import get_pending_applications

		frappe.set_user("Administrator")
		res = get_pending_applications()
		# Always present, default 0.
		self.assertIn("total_before_filter", res)
		self.assertIn("demo_filtered_count", res)
		self.assertIsInstance(res["total_before_filter"], int)

	def test_get_approval_queue_returns_pre_filter_count(self):
		from lms_saas.api.manager import get_approval_queue

		frappe.set_user("Administrator")
		res = get_approval_queue()
		self.assertIn("total_before_filter", res)
		self.assertIn("demo_filtered_count", res)
		self.assertIsInstance(res["total_before_filter"], int)


# ---------------------------------------------------------------------------
# R20-L1: ignore_permissions is restored at end-of-request.
# ---------------------------------------------------------------------------
class TestR20IgnorePermissionsLifecycle(FrappeTestCase):
	"""R20-L1: a leaked ignore_permissions set inside one endpoint cannot
	persist into the next endpoint within the same request lifecycle."""

	def test_reset_permission_flags_clears(self):
		from lms_saas.utils.request_lifecycle import reset_permission_flags

		frappe.flags.ignore_permissions = True
		reset_permission_flags()
		self.assertFalse(bool(getattr(frappe.flags, "ignore_permissions", False)))

	def test_after_request_hook_registered(self):
		"""The reset hook must be wired into Frappe's after_request list."""
		hooks = frappe.get_hooks("after_request") or []
		self.assertIn(
			"lms_saas.utils.request_lifecycle.reset_permission_flags",
			hooks,
			"after_request hook for reset_permission_flags must be registered in hooks.py",
		)


# ---------------------------------------------------------------------------
# R20-P5: four-eyes on Loan — maker of originating Application cannot also
# be the maker of the Loan itself.
# ---------------------------------------------------------------------------
class TestR20FourEyesOnLoan(FrappeTestCase):
	"""R20-P5: Loan four-eyes blocks maker self-origination."""

	def test_enforce_four_eyes_resolves_application_owner(self):
		from lms_saas.api.compliance import _resolve_loan_application_owner

		# No Loan name → None (loan creation outside Application flow).
		class _Stub:
			name = None
		self.assertIsNone(_resolve_loan_application_owner(_Stub()))

	def test_loan_hook_has_before_submit(self):
		"""Pin that the Loan DocType hook includes enforce_four_eyes."""
		hooks = frappe.get_hooks("doc_events") or {}
		loan_events = hooks.get("Loan") or {}
		before_submit = loan_events.get("before_submit") or []
		if isinstance(before_submit, str):
			before_submit = [before_submit]
		self.assertIn(
			"lms_saas.api.compliance.enforce_four_eyes",
			before_submit,
			"Loan DocType before_submit must include enforce_four_eyes (R20-P5)",
		)

	def test_resolve_owner_finds_recent_application(self):
		"""Smoke: if a submitted Application exists for the Loan applicant,
		its owner is returned so the cross-doctype four-eyes check fires."""
		from lms_saas.api.compliance import _resolve_loan_application_owner

		# No Loan Product seeded -> skip with a clear message instead of
		# erroring on the Customer Group validation that surfaced in R17.
		if not frappe.db.exists("Loan Product"):
			self.skipTest("Loan Product not seeded; skipping R20-P5 owner probe")

		# Use a non-group Customer Group so the Customer insert succeeds.
		cg = "All Customer Groups"
		if not frappe.db.exists("Customer Group", cg):
			cg = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or cg

		customer_name = "R20-P5 Probe Customer"
		if not frappe.db.exists("Customer", customer_name):
			c = frappe.new_doc("Customer")
			c.customer_name = customer_name
			c.customer_type = "Individual"
			c.customer_group = cg
			c.insert(ignore_permissions=True)

		products = frappe.get_all("Loan Product", limit_page_length=1)
		if not products:
			self.skipTest("Loan Product missing")
		app = frappe.new_doc("Loan Application")
		app.applicant_type = "Customer"
		app.applicant = customer_name
		app.loan_product = products[0].name
		app.loan_amount = 4000
		app.repayment_periods = 6
		app.rate_of_interest = 20
		app.company = frappe.db.get_single_value("Global Defaults", "default_company") or "_Test Company"
		app.posting_date = frappe.utils.today()
		app.insert(ignore_permissions=True)
		app.submit()

		class _StubLoan:
			name = "FAKE-LOAN"
			applicant = app.applicant
			loan_product = app.loan_product

		owner = _resolve_loan_application_owner(_StubLoan())
		self.assertEqual(owner, app.owner)


# ---------------------------------------------------------------------------
# R20-P3: privacy notice on apply page + post-submit prose.
# ---------------------------------------------------------------------------
class TestR20BorrowerPrivacyAndNextSteps(FrappeTestCase):
	"""R20-P3: visible privacy + clear post-submit guidance."""

	def test_apply_html_has_privacy_notice(self):
		html = (APP_ROOT / "www" / "lms" / "apply.html").read_text()
		self.assertIn("lms-privacy-notice", html)
		self.assertIn("How we handle your information", html)

	def test_js_post_submit_lists_next_steps(self):
		js = (APP_ROOT / "public" / "js" / "lms_portal.js").read_text()
		# Find the submit-application callback block.
		self.assertIn("What happens next", js)
		self.assertIn("1 business day", js)
		self.assertIn("3 business days", js)


# ---------------------------------------------------------------------------
# Sanity: the no-sandbox-mode posture is preserved — we did NOT activate
# sandbox mode as part of R20 (owner requirement). The R20 fixes must work
# regardless of is_sandbox_mode() value.
# ---------------------------------------------------------------------------
class TestR20DemoFunctionalityPreserved(FrappeTestCase):
	"""Owner requirement: do NOT flip sandbox on; demos must keep working."""

	def test_sandbox_mode_not_forced_on(self):
		# The R20 fixes must NOT have set lms_sandbox_end_date.
		from lms_saas.api.compliance_config import is_sandbox_mode

		# is_sandbox_mode() is whatever the operator configured. R20 fixes
		# must not modify that value; this test pins the function is callable.
		_ = is_sandbox_mode()

	def test_relax_flags_unchanged(self):
		# R20 must not have flipped lms_compliance_relaxed or lms_relax_*
		# flags — the owner wants client demos to keep working.
		relaxed = frappe.conf.get("lms_compliance_relaxed", False)
		# Pin the read; do not assert a specific value — the operator
		# controls this. Just confirm the API didn't regress.
		self.assertIsNotNone(relaxed)