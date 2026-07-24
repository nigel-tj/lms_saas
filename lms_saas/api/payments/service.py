"""Payment orchestration — intents, webhooks, loan repayment posting."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt, now_datetime, today

from lms_saas.api.payments.bank_transfer import BankTransferAdapter
from lms_saas.api.payments.ecocash import EcoCashAdapter
from lms_saas.api.payments.onemoney import OneMoneyAdapter

ADAPTERS = {
	"ecocash": EcoCashAdapter(),
	"onemoney": OneMoneyAdapter(),
	"bank_transfer": BankTransferAdapter(),
}


def get_payment_config():
	return {
		"enabled": bool(frappe.conf.get("lms_payments_enabled", False)),
		"providers": frappe.get_all(
			"LMS Payment Provider",
			filters={"enabled": 1},
			fields=["name", "provider_code", "provider_name"],
		),
	}


def get_adapter(provider_code: str):
	adapter = ADAPTERS.get((provider_code or "").lower())
	if not adapter:
		frappe.throw(f"Unknown payment provider: {provider_code}")
	return adapter


@frappe.whitelist()
def create_payment_intent(loan: str, amount: float, provider_code: str = "ecocash"):
	"""Create a payment intent for portal or desk."""
	if not frappe.conf.get("lms_payments_enabled", False):
		frappe.throw("Online payments are not enabled on this site.")

	loan_doc = frappe.get_doc("Loan", loan)
	if loan_doc.applicant_type != "Customer":
		frappe.throw("Payments supported for Customer applicants only.")

	from lms_saas.api.collections import borrower_has_consent

	if not borrower_has_consent(loan_doc.applicant):
		frappe.throw("Borrower consent is required before initiating payment.")

	amount = flt(amount)
	if amount <= 0:
		frappe.throw("Amount must be positive.")

	from lms_saas.api.compliance import enforce_origination_controls

	class _Stub:
		applicant = loan_doc.applicant
		loan_amount = amount

	enforce_origination_controls(_Stub(), None)

	intent = frappe.get_doc(
		{
			"doctype": "LMS Payment Intent",
			"loan": loan,
			"customer": loan_doc.applicant,
			"company": loan_doc.company,
			"amount": amount,
			"provider_code": provider_code,
			"status": "Pending",
		}
	)
	intent.insert(ignore_permissions=True)

	adapter = get_adapter(provider_code)
	result = adapter.initiate(intent.as_dict())

	intent.db_set(
		{
			"external_ref": result.get("external_ref"),
			"redirect_url": result.get("redirect_url"),
			"provider_payload": json.dumps(result.get("raw") or {}),
		}
	)

	return {
		"intent": intent.name,
		"external_ref": intent.external_ref,
		"redirect_url": intent.redirect_url,
		"instructions": result.get("instructions"),
	}


@frappe.whitelist(allow_guest=True)
def handle_payment_webhook(provider: str = "ecocash"):
	"""Provider callback — HMAC verified, idempotent.

	SECURITY (B1): a payment webhook is a money-confirmation endpoint. It must
	never fail open. If no webhook secret is configured for the provider we
	refuse to process — an unauthenticated caller cannot confirm a payment.
	"""
	payload = frappe.request.get_json() if frappe.request else {}
	headers = dict(frappe.request.headers) if frappe.request else {}
	result = confirm_payment_from_webhook(provider, payload, headers)
	return result or {"ok": False}


def confirm_payment_from_webhook(provider: str, payload: dict, headers: dict | None = None) -> dict:
	adapter = get_adapter(provider)

	# B1: refuse webhooks when the provider secret is unset (fail closed).
	secret = (
		frappe.conf.get("lms_ecocash_webhook_secret")
		if (provider or "").lower() == "ecocash"
		else frappe.conf.get("lms_onemoney_webhook_secret")
	)
	if not secret:
		frappe.logger("lms_payments").error(
			f"Webhook rejected for provider {provider}: no webhook secret configured."
		)
		return {"ok": False, "reason": "webhook_auth_not_configured"}

	verified = adapter.verify_webhook(payload, headers or {})
	if not verified or not verified.get("external_ref"):
		return {"ok": False, "reason": "verification_failed"}

	external_ref = verified["external_ref"]
	intent_name = frappe.db.get_value("LMS Payment Intent", {"external_ref": external_ref}, "name")
	if not intent_name:
		return {"ok": False, "reason": "intent_not_found"}

	# B2: lock the intent row so two concurrent deliveries (or a delivery +
	# the nightly reconcile) cannot both pass the Confirmed check and double-post.
	intent = frappe.get_doc("LMS Payment Intent", intent_name, for_update=True)
	if intent.status == "Confirmed":
		return {"ok": True, "intent": intent.name, "duplicate": True}

	# B3: the settled amount must match the intent amount.
	if verified.get("amount") is not None and abs(flt(verified.get("amount")) - flt(intent.amount)) > 0.005:
		frappe.throw("Settled amount does not match the payment intent.")

	if verified.get("status") != "Confirmed":
		intent.db_set("status", verified.get("status") or "Failed")
		return {"ok": False, "intent": intent.name, "status": intent.status}

	repayment = _post_loan_repayment(intent, verified_amount=verified.get("amount"))
	intent.db_set({"status": "Confirmed", "loan_repayment": repayment, "confirmed_at": now_datetime()})

	from lms_saas.api.compliance import write_audit_event

	write_audit_event(
		event_type="Payment:Confirmed",
		reference_doctype="LMS Payment Intent",
		reference_name=intent.name,
		amount=intent.amount,
		company=intent.company,
		details=f"repayment={repayment}, provider={provider}",
	)

	try:
		from lms_saas.api.webhooks import dispatch_webhook_event

		dispatch_webhook_event(
			"repayment.received",
			{"loan": intent.loan, "amount": intent.amount, "repayment": repayment, "provider": provider},
		)
	except Exception:
		pass

	return {"ok": True, "intent": intent.name, "repayment": repayment}


def _post_loan_repayment(intent, verified_amount=None) -> str:
	loan = frappe.get_doc("Loan", intent.loan)
	# B3: post the provider-settled amount when available, else the intent amount.
	paid = flt(verified_amount) if verified_amount is not None else flt(intent.amount)
	repayment = frappe.get_doc(
		{
			"doctype": "Loan Repayment",
			"against_loan": intent.loan,
			"applicant_type": "Customer",
			"applicant": intent.customer,
			"company": intent.company or loan.company,
			"posting_date": today(),
			"amount_paid": paid,
		}
	)
	repayment.insert(ignore_permissions=True)
	repayment.submit()
	return repayment.name


def reconcile_pending_payments():
	"""Nightly: poll pending intents older than 1 hour."""
	if not frappe.conf.get("lms_payments_enabled", False):
		return

	pending = frappe.get_all(
		"LMS Payment Intent",
		filters={"status": "Pending"},
		fields=["name", "external_ref", "provider_code"],
		limit=100,
	)
	for row in pending:
		adapter = ADAPTERS.get(row.provider_code)
		if not adapter:
			continue
		settlement = adapter.fetch_settlement(row.external_ref)
		if settlement and settlement.get("status") == "Confirmed":
			confirm_payment_from_webhook(
				row.provider_code,
				{"reference": row.external_ref, "status": "success", "amount": settlement.get("amount")},
				{},
			)


@frappe.whitelist()
def ingest_bank_statement(lines_json: str, provider_code: str = "bank_transfer"):
	"""Ingest bank statement lines for reconciliation (desk/API).

	SECURITY (B14): bank-statement ingestion is an internal reconciliation
	action performed by staff — it must NOT reuse the provider-webhook confirm
	path (which now fails closed without a provider secret). Require an
	authenticated staff/admin user, then post the matched repayment through the
	normal Loan Repayment path and record an audit event.
	"""
	import json

	roles = set(frappe.get_roles())
	if not roles.intersection({"System Manager", "Administrator", "LMS Portal Staff"}):
		frappe.throw("Not permitted", frappe.PermissionError)

	lines = json.loads(lines_json or "[]")
	matched = 0
	for line in lines:
		ref = line.get("reference") or line.get("external_ref")
		amount = flt(line.get("amount"))
		if not ref:
			continue
		recon = frappe.get_doc(
			{
				"doctype": "LMS Payment Reconciliation",
				"provider_code": provider_code,
				"statement_date": line.get("date") or today(),
				"external_ref": ref,
				"amount": amount,
				"raw_line": json.dumps(line),
				"status": "Unmatched",
			}
		)
		recon.insert(ignore_permissions=True)

		intent_name = frappe.db.get_value("LMS Payment Intent", {"external_ref": ref, "status": "Pending"}, "name")
		if intent_name:
			intent = frappe.get_doc("LMS Payment Intent", intent_name)
			# B11: tolerance comparison on money, not float ==.
			if abs(flt(intent.amount) - amount) < 0.005:
				repayment_name = _post_loan_repayment(intent, verified_amount=amount)
				recon.db_set({"status": "Matched", "payment_intent": intent.name})
				# B14/CRITICAL: mark the intent Confirmed so it can't be re-posted by a
				# re-ingest or by reconcile_pending_payments() polling still-Pending intents.
				intent.db_set(
					{
						"status": "Confirmed",
						"loan_repayment": repayment_name,
						"confirmed_at": frappe.utils.now(),
					}
				)
				from lms_saas.api.compliance import write_audit_event

				write_audit_event(
					event_type="Payment:Confirmed",
					reference_doctype="LMS Payment Intent",
					reference_name=intent.name,
					amount=amount,
					company=intent.company,
					details=f"repayment={repayment_name}, source=bank_statement, provider={provider_code}",
				)
				matched += 1

	return {"lines": len(lines), "matched": matched}
