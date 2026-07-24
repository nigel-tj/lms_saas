"""Field collection API for collector PWA."""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, cint, flt, now_datetime, today

from lms_saas.lms_saas.report.collection_sheet.collection_sheet import execute as collection_sheet_execute


from lms_saas.install import PORTAL_STAFF_ROLE


def _require_collector():
	"""Collector / Loan Officer / Branch Manager (persona-aware).

	Phase 4.4: Borrowers must NOT be able to record field repayments or fetch
	the collection run sheet. The persona check rejects anyone whose
	Employee.custom_lms_persona is not in the staff set.
	"""
	if frappe.session.user == "Guest":
		frappe.throw("Please log in", frappe.PermissionError)
	roles = set(frappe.get_roles())
	if roles.intersection({"System Manager", "Administrator"}):
		return
	from lms_saas.utils.portal import resolve_portal_persona

	persona = resolve_portal_persona()
	if persona not in ("Collector", "Loan Officer", "Branch Manager"):
		frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist()
def get_collection_run_sheet(days_ahead=7, company=None):
	_require_collector()
	columns, data = collection_sheet_execute({"days_ahead": days_ahead, "company": company})

	# Enrich rows with borrower contact info and loan officer
	for row in data:
		loan = frappe.db.get_value(
			"Loan",
			row.get("loan"),
			["applicant", "applicant_type", "custom_loan_officer", "custom_lms_branch"],
			as_dict=True,
		)
		if loan:
			row["borrower_mobile"] = _contact_for_applicant(loan.applicant_type, loan.applicant)
			row["borrower_address"] = _address_for_applicant(loan.applicant_type, loan.applicant)
			row["loan_officer"] = loan.custom_loan_officer or ""
			row["branch"] = loan.custom_lms_branch or row.get("branch") or ""

	# Horizontal scope: collectors only see rows in their own branch (admins keep all).
	if not _is_admin():
		scope_branch = _collector_branch()
		if not scope_branch:
			frappe.throw("No branch assigned — cannot view run sheet.", frappe.PermissionError)
		data = [row for row in data if row.get("branch") == scope_branch]

	return {"columns": columns, "rows": data}


def _contact_for_applicant(applicant_type, applicant):
	if applicant_type == "Customer":
		return frappe.db.get_value("Customer", applicant, "mobile_no") or ""
	if applicant_type == "Employee":
		return frappe.db.get_value("Employee", applicant, "cell_number") or ""
	return ""


def _address_for_applicant(applicant_type, applicant):
	if applicant_type == "Customer":
		return frappe.db.get_value("Customer", applicant, "primary_address") or ""
	return ""


def _is_admin() -> bool:
	return bool(set(frappe.get_roles()).intersection({"System Manager", "Administrator"}))


def _collector_branch() -> str | None:
	# Top-level import so tests can monkey-patch staff.get_current_user_branch
	# via the staff module reference (R12 board feedback: late imports defeat
	# the monkey-patch and break branch-scope unit tests).
	import lms_saas.api.staff as _staff

	return _staff.get_current_user_branch()


def _assert_loan_in_scope(loan_name: str) -> None:
	"""Fail closed: collectors may only act on loans in their branch.

	Admins bypass. Branch Managers / Officers without a branch cannot collect
	cross-branch by guessing loan names.
	"""
	if _is_admin():
		return
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw("Loan not found.", frappe.DoesNotExistError)
	branch = _collector_branch()
	if not branch:
		frappe.throw("No branch assigned — cannot record collections.", frappe.PermissionError)
	loan_branch = frappe.db.get_value("Loan", loan_name, "custom_lms_branch") or ""
	if loan_branch != branch:
		frappe.throw("Loan is not in your branch.", frappe.PermissionError)


@frappe.whitelist()
def record_field_repayment(loan: str, amount: float, payment_mode: str = "Cash"):
	_require_collector()
	_assert_loan_in_scope(loan)
	amount = flt(amount)
	if amount <= 0:
		frappe.throw("Amount must be positive")

	if payment_mode.lower() in ("ecocash", "onemoney", "mobile"):
		from lms_saas.api.payments.service import create_payment_intent

		return create_payment_intent(loan=loan, amount=amount, provider_code=payment_mode.lower())

	# B12: idempotency guard — if an identical repayment was submitted for this
	# loan+amount in the last N seconds, return it instead of double-posting.
	# R12 board: default raised from 5 min (300s) to 15 min (900s) to absorb
	# USSD retries that arrive 5-10 min after the original confirm on slow
	# mobile networks. Override via site_config `lms_field_repay_dedupe_seconds`.
	dedupe_seconds = cint(frappe.conf.get("lms_field_repay_dedupe_seconds", 900))
	existing = frappe.db.exists(
		"Loan Repayment",
		{
			"against_loan": loan,
			"amount_paid": flt(amount),
			"docstatus": 1,
			"creation": (">=", add_to_date(now_datetime(), seconds=-dedupe_seconds)),
		},
	)
	if existing:
		return {"repayment": existing, "loan": loan, "amount": amount}

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
def record_partial_repayment(loan: str, amount: float, payment_mode: str = "Cash", note: str = ""):
	"""Record a partial field collection (amount < outstanding)."""
	_require_collector()
	_assert_loan_in_scope(loan)
	amount = flt(amount)
	if amount <= 0:
		frappe.throw("Amount must be positive")

	loan_doc = frappe.get_doc("Loan", loan)
	outstanding = flt(loan_doc.total_payment or 0) - flt(loan_doc.total_amount_paid or 0)
	if amount > outstanding:
		frappe.throw(f"Partial amount ({amount}) exceeds outstanding ({outstanding}).")

	result = record_field_repayment(loan, amount, payment_mode)
	if note:
		try:
			frappe.get_doc(
				{
					"doctype": "Comment",
					"comment_type": "Info",
					"reference_doctype": "Loan Repayment",
					"reference_name": result.get("repayment"),
					"content": f"Field collection note: {note}",
				}
			).insert(ignore_permissions=True)
		except Exception:
			pass
	result["partial"] = True
	result["note"] = note
	return result


@frappe.whitelist()
def create_promise_to_pay(loan: str, promised_date, promised_amount=None, note: str = ""):
	"""Create a ToDo tracking a borrower's promise to pay."""
	_require_collector()
	_assert_loan_in_scope(loan)
	loan_doc = frappe.get_doc("Loan", loan)
	todo = frappe.get_doc(
		{
			"doctype": "ToDo",
			"description": f"Promise to pay — Loan {loan} by {promised_date}"
			+ (f" — {promised_amount}" if promised_amount else "")
			+ (f" — {note}" if note else ""),
			"reference_type": "Loan",
			"reference_name": loan,
			"priority": "High",
			"status": "Open",
			"date": promised_date,
		}
	)
	todo.insert(ignore_permissions=True)
	return {"todo": todo.name, "loan": loan, "promised_date": promised_date}


@frappe.whitelist()
def generate_collection_receipt(repayment_name: str):
	"""Generate a PDF receipt for a field collection."""
	_require_collector()
	if not frappe.db.exists("Loan Repayment", repayment_name):
		frappe.throw("Repayment not found.")

	_assert_loan_in_scope(frappe.db.get_value("Loan Repayment", repayment_name, "against_loan"))

	pdf = frappe.get_print(
		"Loan Repayment",
		repayment_name,
		print_format="LMS Collection Receipt",
		as_pdf=True,
	)
	frappe.local.response.filename = f"receipt_{repayment_name}.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "download"


@frappe.whitelist()
def get_offline_queue_status():
	"""Return count of pending offline items (for PWA badge)."""
	_require_collector()
	return {"pending": 0}  # Actual count is in localStorage on the PWA side


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
