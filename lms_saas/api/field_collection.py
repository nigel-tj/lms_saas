"""Field collection API for collector PWA."""

from __future__ import annotations

import frappe
from frappe.utils import flt, today

from lms_saas.lms_saas.report.collection_sheet.collection_sheet import execute as collection_sheet_execute


def _require_collector():
	if frappe.session.user == "Guest":
		frappe.throw("Please log in", frappe.PermissionError)
	roles = set(frappe.get_roles())
	if not roles.intersection({"LMS Collector", "LMS Branch Manager", "LMS Admin", "System Manager"}):
		frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist()
def get_collection_run_sheet(days_ahead=7, company=None):
	_require_collector()
	columns, data = collection_sheet_execute({"days_ahead": days_ahead, "company": company})
	return {"columns": columns, "rows": data}


@frappe.whitelist()
def record_field_repayment(loan: str, amount: float, payment_mode: str = "Cash"):
	_require_collector()
	amount = flt(amount)
	if amount <= 0:
		frappe.throw("Amount must be positive")

	if payment_mode.lower() in ("ecocash", "onemoney", "mobile"):
		from lms_saas.api.payments.service import create_payment_intent

		return create_payment_intent(loan=loan, amount=amount, provider_code=payment_mode.lower())

	loan_doc = frappe.get_doc("Loan", loan)
	repayment = frappe.get_doc(
		{
			"doctype": "Loan Repayment",
			"against_loan": loan,
			"applicant_type": loan_doc.applicant_type,
			"applicant": loan_doc.applicant,
			"company": loan_doc.company,
			"posting_date": today(),
			"amount_paid": amount,
		}
	)
	repayment.insert(ignore_permissions=True)
	repayment.submit()
	return {"repayment": repayment.name, "loan": loan, "amount": amount}


@frappe.whitelist()
def sync_offline_batch(batch_json: str):
	"""Process queued offline repayments from PWA."""
	_require_collector()
	import json

	batch = json.loads(batch_json or "[]")
	results = []
	for item in batch:
		try:
			out = record_field_repayment(item.get("loan"), item.get("amount"), item.get("payment_mode", "Cash"))
			results.append({"ok": True, **out})
		except Exception as exc:
			results.append({"ok": False, "loan": item.get("loan"), "error": str(exc)})
	return {"results": results}
