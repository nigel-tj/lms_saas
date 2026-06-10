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
	"""Provider callback — HMAC verified, idempotent."""
	payload = frappe.request.get_json() if frappe.request else {}
	headers = dict(frappe.request.headers) if frappe.request else {}
	result = confirm_payment_from_webhook(provider, payload, headers)
	return result or {"ok": False}


def confirm_payment_from_webhook(provider: str, payload: dict, headers: dict | None = None) -> dict:
	adapter = get_adapter(provider)
	verified = adapter.verify_webhook(payload, headers or {})
	if not verified or not verified.get("external_ref"):
		return {"ok": False, "reason": "verification_failed"}

	external_ref = verified["external_ref"]
	intent_name = frappe.db.get_value("LMS Payment Intent", {"external_ref": external_ref}, "name")
	if not intent_name:
		return {"ok": False, "reason": "intent_not_found"}

	intent = frappe.get_doc("LMS Payment Intent", intent_name)
	if intent.status == "Confirmed":
		return {"ok": True, "intent": intent.name, "duplicate": True}

	if verified.get("status") != "Confirmed":
		intent.db_set("status", verified.get("status") or "Failed")
		return {"ok": False, "intent": intent.name, "status": intent.status}

	repayment = _post_loan_repayment(intent)
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


def _post_loan_repayment(intent) -> str:
	loan = frappe.get_doc("Loan", intent.loan)
	repayment = frappe.get_doc(
		{
			"doctype": "Loan Repayment",
			"against_loan": intent.loan,
			"applicant_type": "Customer",
			"applicant": intent.customer,
			"company": intent.company or loan.company,
			"posting_date": today(),
			"amount_paid": intent.amount,
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
	"""Ingest bank statement lines for reconciliation (desk/API)."""
	import json

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
			if flt(intent.amount) == amount:
				confirm_payment_from_webhook(
					provider_code,
					{"reference": ref, "status": "success", "amount": amount, "confirmed": True},
					{},
				)
				recon.db_set({"status": "Matched", "payment_intent": intent.name})
				matched += 1

	return {"lines": len(lines), "matched": matched}
