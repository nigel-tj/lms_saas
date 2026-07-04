import frappe
from frappe.tests.utils import FrappeTestCase


class TestPaymentsIdempotency(FrappeTestCase):
	def test_webhook_verification_ecocash(self):
		from lms_saas.api.payments.ecocash import EcoCashAdapter

		adapter = EcoCashAdapter()
		result = adapter.verify_webhook(
			{"reference": "REF-1", "status": "success", "amount": 50},
			{},
		)
		self.assertEqual(result["status"], "Confirmed")
		self.assertEqual(result["external_ref"], "REF-1")

	def test_bank_transfer_generates_reference(self):
		from lms_saas.api.payments.bank_transfer import BankTransferAdapter

		adapter = BankTransferAdapter()
		out = adapter.initiate({"name": "PAY-00001", "amount": 200})
		self.assertIn("LMS-", out["external_ref"])
		self.assertIn("instructions", out)
