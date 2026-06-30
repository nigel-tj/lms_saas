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