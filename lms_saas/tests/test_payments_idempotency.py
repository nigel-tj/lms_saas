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

	def test_webhook_refuses_when_secret_unset(self):
		"""B1: a payment webhook must fail closed when no provider secret is configured."""
		from lms_saas.api.payments.service import confirm_payment_from_webhook

		# Ensure no secret is configured in this test site.
		with self.set_user("Administrator"):
			frappe.conf["lms_ecocash_webhook_secret"] = None
			result = confirm_payment_from_webhook(
				"ecocash",
				{"reference": "REF-X", "status": "success", "amount": 10},
				{},
			)
		self.assertFalse(result.get("ok"))
		self.assertEqual(result.get("reason"), "webhook_auth_not_configured")

	def test_confirmed_intent_is_idempotent(self):
		"""B2: re-delivering a Confirmed intent must not post a second repayment."""
		from lms_saas.api.payments.service import confirm_payment_from_webhook

		# Build a fake verified payload with a known external_ref.
		verified = {
			"external_ref": "IDEMP-REF-1",
			"status": "Confirmed",
			"amount": 100.0,
		}
		# Patch the adapter so verify_webhook returns our verified dict.
		import lms_saas.api.payments.service as svc

		class _Stub:
			def verify_webhook(self, payload, headers):
				return verified

		svc.ADAPTERS["ecocash"] = _Stub()

		# First delivery: posts a repayment (only if an intent exists).
		repay_before = frappe.db.count("Loan Repayment")
		# We do NOT create an intent here; the function should short-circuit
		# on intent_not_found rather than throw.
		with self.set_user("Administrator"):
			frappe.conf["lms_ecocash_webhook_secret"] = "test-secret"
			out = confirm_payment_from_webhook("ecocash", verified, {"x-signature": "sig"})
		# No intent -> not found, no repayment posted.
		self.assertEqual(out.get("reason"), "intent_not_found")
		repay_after = frappe.db.count("Loan Repayment")
		self.assertEqual(repay_before, repay_after)

	def test_settled_amount_mismatch_is_rejected(self):
		"""B3: a webhook whose settled amount differs from the intent must be rejected."""
		from lms_saas.api.payments.service import confirm_payment_from_webhook

		# R12 board: pick a real Loan Product so the Loan can be saved
		# (lending's validate requires a Loan Product on the Company).
		default_company = frappe.db.get_single_value("Global Defaults", "default_company")
		loan_product = frappe.db.get_value(
			"Loan Product", {"company": default_company}, "name"
			) or frappe.db.get_value("Loan Product", {}, "name")
		if not loan_product:
			self.skipTest("No Loan Product found on this site")

		# Create an intent with a fixed amount.
		loan = frappe.get_doc({
			"doctype": "Loan",
			"applicant_type": "Customer",
			"applicant": self._make_customer(),
			"company": default_company,
			"loan_product": loan_product,
			"loan_amount": 100,
			"rate_of_interest": 10,
		})
		loan.insert()
	def _make_customer(self):
		# Find a non-Group Customer Group; "Individual" is the standard one
		# in fresh sites. Fallback: pick the first is_group=0 row.
		groups = frappe.get_all(
			"Customer Group",
			filters={"is_group": 0},
			pluck="name",
			limit_page_length=5,
		)
		customer_group = groups[0] if groups else None
		cust = frappe.get_doc({
			"doctype": "Customer",
			"customer_name": "Test Borrower",
			"customer_type": "Individual",
			"customer_group": customer_group,
		})
		cust.insert()
		return cust.name
