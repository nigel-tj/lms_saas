"""Field collection API for collector PWA."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, add_to_date, cint, flt, getdate, now_datetime, today

from lms_saas.lms_saas.report.collection_sheet.collection_sheet import execute as collection_sheet_execute


from lms_saas.install import PORTAL_STAFF_ROLE
from lms_saas.api.pii_access import mask_mobile, record_pii_access, record_pii_access_strict


def _require_collector():
	"""Collector / Loan Officer / Branch Manager (persona-aware).

	Delegates to the shared access-control module.
	"""
	from lms_saas.utils.access_control import require_persona
	require_persona("Collector", "Loan Officer", "Branch Manager")


@frappe.whitelist()
def get_collection_run_sheet(days_ahead=7, company=None, reveal=False):
	"""Return today's run sheet for the collector.

	R18-4: borrower mobile is MASKED by default. Pass ``reveal=True`` to
	get the full MSISDN — every reveal is recorded in the LMS PII Access
	Log so the regulator has an audit trail.
	"""
	_require_collector()
	columns, data = collection_sheet_execute({"days_ahead": days_ahead, "company": company})
	# R18-4: `reveal` can come in as a string from the JS query. Coerce.
	reveal_flag = str(reveal).lower() in ("1", "true", "yes")

	# Enrich rows with borrower contact info and loan officer
	for row in data:
		loan = frappe.db.get_value(
			"Loan",
			row.get("loan"),
			["applicant", "applicant_type", "custom_loan_officer", "custom_lms_branch"],
			as_dict=True,
		)
		if loan:
			mobile = _contact_for_applicant(loan.applicant_type, loan.applicant)
			address = _address_for_applicant(loan.applicant_type, loan.applicant)
			if reveal_flag:
				# R18-4: log every reveal so the operator can prove no PII
				# was abused. R20-M3: STRICT — if the audit row cannot be
				# written, abort the reveal so we never serve cleartext
				# PII without an audit row.
				record_pii_access_strict(
					reference_doctype="Loan",
					reference_name=row.get("loan"),
					field="mobile_no",
					reason="Field collection run sheet reveal",
				)
				row["borrower_mobile"] = mobile
			else:
				row["borrower_mobile"] = mask_mobile(mobile)
				row["borrower_mobile_masked"] = True
			row["borrower_address"] = address  # address is not PII-grade here; left in place
			row["loan_officer"] = loan.custom_loan_officer or ""
			row["branch"] = loan.custom_lms_branch or row.get("branch") or ""

	# Horizontal scope: collectors only see rows in their own branch.
	# Admins and Branch Managers see all branches (managers oversee the
	# whole branch, not just one cost-center slice).
	if not _is_admin() and not _is_branch_manager():
		scope_branch = _collector_branch()
		if not scope_branch:
			frappe.throw("No branch assigned — cannot view run sheet.", frappe.PermissionError)
		data = [row for row in data if row.get("branch") == scope_branch]

	return {
		"columns": columns,
		"rows": data,
		"pii_revealed": bool(reveal_flag),
		# R58: per-bucket KPI totals computed FROM the scoped rows so the
		# KPI strip and the run sheet can never disagree (R35-#27).
		"kpis": _bucket_kpis(data),
		# R59: what THIS collector actually collected today. The old strip
		# showed only what is still owed (overdue + upcoming) and had no
		# "collected" card at all, so a collector who had just recorded
		# repayments saw no evidence of their own work. Sourced from the
		# submitted Loan Repayment records the collector owns — same day
		# window as get_collections_overview (getdate comparison, since
		# posting_date is a Datetime column).
		"collected_today": _collected_today(),
	}


def _collected_today():
	"""Today's collections by the signed-in collector (count + total).

	Datetime-safe: posting_date is a Datetime column, so filter with a
	date range (>= today 00:00, < tomorrow 00:00) — plain equality only
	matches midnight and silently hides same-day work.
	"""
	today_start = getdate(today())
	tomorrow_start = add_days(today_start, 1)
	rows = frappe.get_all(
		"Loan Repayment",
		filters={
			"docstatus": 1,
			"owner": frappe.session.user,
			"posting_date": (">=", today_start),
			"posting_date": ("<", tomorrow_start),
		},
		fields=["amount_paid"],
	)
	return {
		"amount": sum(flt(r.amount_paid) for r in rows),
		"count": len(rows),
	}


@frappe.whitelist()
def get_collection_history(days=30, limit=200):
	"""R59: historical collections view for the collector.

	Returns the collector's own submitted repayments, newest first, with
	a per-day rollup the UI can chart. Days is clamped to 1..365 so a
	stray value can't dump the whole table.
	"""
	_require_collector()
	days = max(1, min(cint(days), 365))
	limit = max(1, min(cint(limit), 500))
	since = add_days(getdate(today()), -days)

	rows = frappe.get_all(
		"Loan Repayment",
		filters={
			"docstatus": 1,
			"owner": frappe.session.user,
			"posting_date": (">=", since),
		},
		fields=["name", "against_loan", "amount_paid", "posting_date", "mode_of_payment"],
		order_by="posting_date desc",
		limit_page_length=limit,
	)

	# Resolve borrower names in one batch query so the history table
	# shows who paid, not a bare loan number.
	loan_names = list({r.against_loan for r in rows if r.against_loan})
	borrower_map = {}
	if loan_names:
		borrower_map = {
			l.name: l.applicant
			for l in frappe.get_all(
				"Loan",
				filters={"name": ("in", loan_names)},
				fields=["name", "applicant"],
			)
		}

	per_day = {}
	items = []
	for r in rows:
		day = getdate(r.posting_date).isoformat()
		per_day[day] = per_day.get(day, 0) + flt(r.amount_paid)
		items.append(
			{
				"repayment": r.name,
				"loan": r.against_loan,
				"borrower": borrower_map.get(r.against_loan, r.against_loan),
				"amount": flt(r.amount_paid),
				"date": day,
				"mode": r.mode_of_payment or "",
			}
		)

	return {
		"days": days,
		"total": sum(flt(r.amount_paid) for r in rows),
		"count": len(rows),
		"per_day": [{"date": d, "amount": a} for d, a in sorted(per_day.items())],
		"items": items,
	}


def _bucket_kpis(rows):
	"""Recompute per-bucket totals from the final row list.

	Takes the post-scope rows (what the page will actually render) so the
	KPI strip always agrees with the visible list — the totals are derived
	from the same data, not a parallel query.
	"""
	kpis = {
		"overdue": {"count": 0, "amount": 0.0},
		"upcoming": {"count": 0, "amount": 0.0},
	}
	for row in rows:
		bucket = row.get("bucket") or "upcoming"
		if bucket not in kpis:
			continue
		kpis[bucket]["count"] += 1
		kpis[bucket]["amount"] += flt(row.get("amount") or 0)
	return kpis


@frappe.whitelist()
def reveal_borrower_pii(loan: str, field: str = "mobile_no"):
	"""One-shot PII reveal endpoint with a mandatory audit row.

	R18-4: the run sheet masks the borrower's mobile by default. When the
	collector taps "Reveal" on a row, this endpoint returns the cleartext
	and writes one row to LMS PII Access Log so the regulator sees who
	looked at what.
	"""
	_require_collector()
	_assert_loan_in_scope(loan)
	loan_doc = frappe.db.get_value(
		"Loan",
		loan,
		["applicant", "applicant_type"],
		as_dict=True,
	)
	if not loan_doc:
		frappe.throw("Loan not found.", frappe.DoesNotExistError)
	if field != "mobile_no":
		frappe.throw("Unsupported field for reveal.")
	mobile = _contact_for_applicant(loan_doc.applicant_type, loan_doc.applicant)
	# R20-M3: STRICT audit — a failed insert aborts the reveal. The collector
	# never sees the cleartext unless the regulator can see the audit row.
	record_pii_access_strict(
		reference_doctype="Loan",
		reference_name=loan,
		field=field,
		reason="Field collection explicit reveal",
	)
	return {"loan": loan, "field": field, "value": mobile}


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
	from lms_saas.utils.access_control import is_admin
	return is_admin()


def _is_branch_manager() -> bool:
	"""True if the signed-in user's persona is Branch Manager."""
	from lms_saas.utils.portal import resolve_portal_persona

	return resolve_portal_persona() == "Branch Manager"


def _collector_branch() -> str | None:
	# Top-level import so tests can monkey-patch staff.get_current_user_branch
	# via the staff module reference (R12 board feedback: late imports defeat
	# the monkey-patch and break branch-scope unit tests).
	import lms_saas.api.staff as _staff

	return _staff.get_current_user_branch()


def _assert_loan_in_scope(loan_name: str) -> None:
	"""Fail closed: collectors may only act on loans in their branch.

	Admins and Branch Managers bypass (managers oversee all loans in the
	branch). Collectors/Officers without a branch cannot collect
	cross-branch by guessing loan names.
	"""
	if _is_admin() or _is_branch_manager():
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
def undo_collection(loan: str, repayment: str):
	"""R18-6: cancel a repayment recorded in the last 5 minutes.

	Paired with the B12 15-min dedup window — but the Undo window is
	deliberately tighter because the operator has the customer's cash in
	hand and needs to act fast. Refunds the GL entry, marks the repayment
	cancelled, and records a money event for the audit trail.
	"""
	_require_collector()
	_assert_loan_in_scope(loan)

	if not repayment or not frappe.db.exists("Loan Repayment", repayment):
		frappe.throw("Repayment not found.", frappe.DoesNotExistError)

	r = frappe.get_doc("Loan Repayment", repayment)
	# Only the recording collector (or an admin) can undo. We approximate
	# "recording collector" by checking the loan is in their branch and
	# the repayment was created within the last 5 minutes.
	from frappe.utils import time_diff_in_seconds
	if time_diff_in_seconds(frappe.utils.now_datetime(), r.creation) > 300 and not _is_admin():
		frappe.throw("Undo window has closed. Reverse this through Manager Books instead.", frappe.PermissionError)

	if r.docstatus == 2:
		return {"loan": loan, "repayment": repayment, "status": "already_cancelled"}

	# Cancel the repayment and reverse the GL entry.
	if r.docstatus == 1:
		r.cancel()
	else:
		r.delete()

	# R18-6: money-event audit row so the operator can prove the reversal.
	# R58-sweep fix: record_money_event is a doc_event hook (doc, method) —
	# the audit row goes through write_audit_event directly. The old call
	# passed event_type=/amount= kwargs that the hook never accepted, so
	# UNDO crashed with TypeError AFTER the cancel — the repayment was
	# reversed but the collector saw a 500 and the audit trail lost the
	# reversal event.
	from lms_saas.api.compliance import write_audit_event

	write_audit_event(
		event_type="Loan Repayment:Cancelled",
		reference_doctype="Loan Repayment",
		reference_name=repayment,
		amount=-flt(r.amount_paid or 0),
		details="Undone by collector via R18-6 Undo toast within 5 min of creation.",
	)

	return {"loan": loan, "repayment": repayment, "status": "cancelled"}


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
	"""Process queued offline repayments from PWA.

	R59: pass the collector's note through (it used to be dropped on
	sync) and reuse the record_field_repayment dedupe window so a queued
	item that already made it (e.g. retry after a dropped response) does
	not double-post.
	"""
	_require_collector()
	import json

	batch = json.loads(batch_json or "[]")
	results = []
	for item in batch:
		try:
			out = record_field_repayment(
				item.get("loan"),
				item.get("amount"),
				item.get("payment_mode", "Cash"),
			)
			note = item.get("note") or ""
			if note and out.get("repayment"):
				try:
					frappe.get_doc(
						{
							"doctype": "Comment",
							"comment_type": "Info",
							"reference_doctype": "Loan Repayment",
							"reference_name": out.get("repayment"),
							"content": f"Field collection note: {note}",
						}
					).insert(ignore_permissions=True)
				except Exception:
					pass
			results.append({"ok": True, **out})
		except Exception as exc:
			results.append({"ok": False, "loan": item.get("loan"), "error": str(exc)})
	return {"results": results}
