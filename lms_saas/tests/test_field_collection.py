"""Tests for field collection enhancements: partial payments, promise-to-pay, receipt."""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestFieldCollection(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_field_collection_api_surface(self):
		"""New field collection API methods exist and are callable."""
		from lms_saas.api import field_collection

		for fn in (
			"get_collection_run_sheet",
			"record_field_repayment",
			"record_partial_repayment",
			"create_promise_to_pay",
			"generate_collection_receipt",
			"get_offline_queue_status",
			"sync_offline_batch",
		):
			self.assertTrue(callable(getattr(field_collection, fn, None)), fn)

	def test_promise_to_pay_creates_todo(self):
		"""create_promise_to_pay creates a ToDo linked to the loan."""
		from lms_saas.api.field_collection import create_promise_to_pay

		# Find an existing loan to use
		loan_name = frappe.db.get_value("Loan", {"docstatus": 1}, "name")
		if not loan_name:
			self.skipTest("No submitted loan found for test")

		result = create_promise_to_pay(
			loan=loan_name,
			promised_date="2026-07-15",
			promised_amount=500,
			note="Test promise",
		)
		self.assertIn("todo", result)
		# Cleanup
		if result.get("todo"):
			frappe.delete_doc("ToDo", result["todo"], force=1, ignore_permissions=True)

	def test_offline_queue_status(self):
		"""get_offline_queue_status returns a dict with pending count."""
		from lms_saas.api.field_collection import get_offline_queue_status

		result = get_offline_queue_status()
		self.assertIn("pending", result)

	def test_repayment_idempotency_guard(self):
		"""B12: a second identical repayment within 5 minutes returns the first, no double-post."""
		from lms_saas.api.field_collection import record_field_repayment
		from frappe.utils import now_datetime

		loan = frappe.db.get_value("Loan", {"docstatus": 1}, "name")
		if not loan:
			self.skipTest("No submitted loan found for test")

		# R12 board: the lending module requires `Collection Offset Sequence for
		# Standard Asset` to be set on the Company before Loan Repayment.validate
		# can run. The sequence must be a Loan Demand Offset Order (not a Loan
		# Product). Set it on the default Company for the duration of the test
		# (saved per-test by FrappeTestCase's per-test rollback).
		company = frappe.db.get_single_value("Global Defaults", "default_company")
		original = frappe.db.get_value("Company", company, "collection_offset_sequence_for_standard_asset")
		if not original:
			seq = frappe.db.get_value("Loan Demand Offset Order", {}, "name")
			if not seq:
				self.skipTest("No Loan Demand Offset Order found to use as Collection Offset Sequence")
			frappe.db.set_value("Company", company, "collection_offset_sequence_for_standard_asset", seq)

		existing = frappe.get_doc(
			{
				"doctype": "Loan Repayment",
				"against_loan": loan,
				"applicant_type": "Customer",
				"applicant": frappe.db.get_value("Loan", loan, "applicant"),
				"posting_date": "2026-07-15",
				"amount_paid": 123.45,
				"docstatus": 1,
				"creation": now_datetime(),
			}
		)
		existing.insert(ignore_permissions=True)
		try:
			out = record_field_repayment(loan=loan, amount=123.45, payment_mode="cash")
			self.assertEqual(out.get("repayment"), existing.name)
		finally:
			# Cancel and delete (Loan Repayment is submittable, can't delete while submitted)
			try:
				doc = frappe.get_doc("Loan Repayment", existing.name)
				if doc.docstatus == 1:
					doc.cancel()
			except Exception:
				pass
			frappe.delete_doc("Loan Repayment", existing.name, force=1, ignore_permissions=True)
			# Restore the original (in case the per-test rollback doesn't catch this)
			if not original:
				frappe.db.set_value("Company", company, "collection_offset_sequence_for_standard_asset", None)

	def test_collection_receipt_scope_enforced(self):
		"""B21: a collector cannot generate a receipt for a loan outside their branch.

		The helper first checks the loan exists (DoesNotExistError) then verifies
		branch scope (PermissionError). To exercise the branch-scope path we
		pre-create the loan in Branch B and assert the helper raises
		PermissionError (not DoesNotExistError) when the collector is in
		Branch A.
		"""
		from lms_saas.api import field_collection
		from lms_saas.api import staff
		from lms_saas.api.field_collection import _assert_loan_in_scope

		# Force a non-admin session user so the admin bypass doesn't short-circuit
		# the branch-scope check. The branch resolver is now resolved via the
		# staff module (top-level import so it's monkey-patchable).
		frappe.set_user("test.collector.scope@example.com")
		original_branch = staff.get_current_user_branch
		try:
			# Branch mismatch — the loan is in Branch B, the collector in Branch A.
			# To avoid the DoesNotExistError short-circuit we use a loan that
			# exists in the DB; we create a draft loan with a non-existent
			# applicant to keep the test self-contained.
			loan_name = f"TEST-LOAN-{frappe.utils.now_datetime().strftime('%H%M%S%f')}"
			try:
				frappe.get_doc(
					{
						"doctype": "Loan",
						"applicant_type": "Customer",
						"applicant": "FAKE-CUSTOMER-FOR-SCOPE-TEST",
						"loan_amount": 1,
						"rate_of_interest": 0,
						"custom_lms_branch": "Branch B",
					}
				).insert(ignore_permissions=True)
			except Exception:
				# If the fake customer can't be created we still need a real
				# loan name for the existence check. Use a known existing loan.
				loan_name = frappe.db.get_value("Loan", {}, "name") or "no-loan"
			staff.get_current_user_branch = lambda: "Branch A"
			with self.assertRaises(frappe.PermissionError):
				_assert_loan_in_scope(loan_name)
		finally:
			staff.get_current_user_branch = original_branch
			frappe.set_user("Administrator")