"""Reporting module — single source of truth for portfolio, arrears, and collections reports.

Consolidates the duplicated report logic across ``api/officer.py`` (the
"my" variants scoped to one officer) and ``api/manager.py`` (the branch-
scoped variants). The R35-#27 lesson — "KPIs and their tabs MUST use the
same definition" — is enforced structurally here: both the dashboard KPI
and the report tab call the same function, so a refactor cannot
reintroduce the split.

Interface (small, deep):

- :func:`portfolio_summary` — PAR buckets, outstanding, NPA count.
- :func:`arrears_aging` — loans grouped by DPD bucket.
- :func:`collections_report` — repayments in a date range, grouped by officer.
- :func:`disbursement_report` — disbursements in a date range, grouped by officer.

Each function takes a ``scope`` parameter (``"officer"`` or ``"branch"``)
so the "my" variants are just ``scope="officer"`` with the officer's
Employee name, not a separate copy of the formula.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, today, getdate, add_days, cint


# ---------------------------------------------------------------------------
# Portfolio summary (PAR buckets)
# ---------------------------------------------------------------------------

def portfolio_summary(
	*,
	branch: str | None = None,
	officer: str | None = None,
) -> dict:
	"""Portfolio at risk summary: outstanding, PAR buckets, NPA count.

	Args:
		branch: optional branch (Cost Center) filter. When set, only
			loans in this branch are counted.
		officer: optional Employee name filter. When set, only loans
			assigned to this officer are counted.

	Returns:
		dict with ``total_loans``, ``total_outstanding``, ``par30_count``,
		``par30_outstanding``, ``par60_count``, ``par60_outstanding``,
		``par90_count``, ``par90_outstanding``, ``current_outstanding``,
		``npa_count``, ``par_ratio``.
	"""
	filters: dict = {
		"docstatus": 1,
		"status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
	}
	if branch:
		filters["custom_lms_branch"] = branch
	if officer:
		filters["custom_loan_officer"] = officer

	loans = frappe.get_all(
		"Loan",
		filters=filters,
		fields=[
			"name", "loan_amount", "total_payment", "total_amount_paid",
			"custom_days_past_due", "custom_loan_officer", "status",
		],
		limit_page_length=0,
	)

	summary = {
		"total_loans": len(loans),
		"total_outstanding": 0,
		"par30_count": 0,
		"par30_outstanding": 0,
		"par60_count": 0,
		"par60_outstanding": 0,
		"par90_count": 0,
		"par90_outstanding": 0,
		"current_count": 0,
		"current_outstanding": 0,
		"npa_count": 0,
	}

	for loan in loans:
		outstanding = flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0)
		dpd = flt(loan.custom_days_past_due or 0)
		summary["total_outstanding"] += outstanding
		if dpd > 90:
			summary["par90_count"] += 1
			summary["par90_outstanding"] += outstanding
			summary["npa_count"] += 1
		elif dpd > 60:
			summary["par60_count"] += 1
			summary["par60_outstanding"] += outstanding
		elif dpd > 30:
			summary["par30_count"] += 1
			summary["par30_outstanding"] += outstanding
		else:
			# #37 fix: the officer's Portfolio Summary "Current" KPI
			# expects a loan count, not a dollar amount. The dollar
			# amount is preserved as current_outstanding so the
			# outstanding tile still totals correctly. R35-#27 lesson:
			# keep the KPI definition single-source-of-truth across the
			# dashboard and the tab so a refactor cannot reintroduce the
			# split.
			summary["current_count"] += 1
			summary["current_outstanding"] += outstanding

	summary["par_ratio"] = (
		(summary["par30_outstanding"] + summary["par60_outstanding"] + summary["par90_outstanding"])
		/ summary["total_outstanding"]
		if summary["total_outstanding"]
		else 0
	)

	return summary


# ---------------------------------------------------------------------------
# Arrears aging
# ---------------------------------------------------------------------------

def arrears_aging(
	*,
	as_on_date: str | None = None,
	branch: str | None = None,
	officer: str | None = None,
) -> dict:
	"""Arrears aging report: loans grouped by DPD bucket.

	Args:
		as_on_date: unused (DPD is read from the Loan's
			``custom_days_past_due`` field), kept for API compat.
		branch: optional branch filter.
		officer: optional Employee name filter.

	Returns:
		dict with ``buckets`` (current, 1_30, 31_60, 61_90, 90_plus),
		``totals``, ``total_loans``, ``total_outstanding``.
	"""
	filters: dict = {
		"docstatus": 1,
		"status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
	}
	if branch:
		filters["custom_lms_branch"] = branch
	if officer:
		filters["custom_loan_officer"] = officer

	loans = frappe.get_all(
		"Loan",
		filters=filters,
		fields=[
			"name", "applicant", "loan_amount", "total_payment", "total_amount_paid",
			"custom_days_past_due", "custom_loan_officer", "status",
		],
		limit_page_length=0,
	)

	buckets = {"current": [], "1_30": [], "31_60": [], "61_90": [], "90_plus": []}
	totals = {"current": 0, "1_30": 0, "31_60": 0, "61_90": 0, "90_plus": 0}

	for loan in loans:
		outstanding = flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0)
		dpd = flt(loan.custom_days_past_due or 0)
		row = {
			"loan": loan.name,
			"applicant": loan.applicant,
			"customer_name": frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else "",
			"outstanding": outstanding,
			"dpd": dpd,
			"status": loan.status,
		}
		if dpd == 0:
			buckets["current"].append(row)
			totals["current"] += outstanding
		elif dpd <= 30:
			buckets["1_30"].append(row)
			totals["1_30"] += outstanding
		elif dpd <= 60:
			buckets["31_60"].append(row)
			totals["31_60"] += outstanding
		elif dpd <= 90:
			buckets["61_90"].append(row)
			totals["61_90"] += outstanding
		else:
			buckets["90_plus"].append(row)
			totals["90_plus"] += outstanding

	return {
		"buckets": buckets,
		"totals": totals,
		"total_loans": len(loans),
		"total_outstanding": sum(totals.values()),
	}


# ---------------------------------------------------------------------------
# Collections report
# ---------------------------------------------------------------------------

def collections_report(
	*,
	from_date: str | None = None,
	to_date: str | None = None,
	branch: str | None = None,
	officer: str | None = None,
) -> dict:
	"""Collections report: repayments in a date range, grouped by officer.

	Args:
		from_date: optional start date (inclusive).
		to_date: optional end date (inclusive).
		branch: optional branch filter.
		officer: optional Employee name filter. When set, only
			repayments on loans assigned to this officer are included.

	Returns:
		dict with ``repayments``, ``by_officer``, ``total_collected``,
		``count``.
	"""
	# If officer-scoped, filter by the officer's loans.
	if officer:
		loan_names = frappe.get_all(
			"Loan",
			filters={"custom_loan_officer": officer, "docstatus": 1},
			pluck="name",
		)
		if not loan_names:
			return {"repayments": [], "by_officer": [], "total_collected": 0, "count": 0}
		filters: dict = {"against_loan": ("in", loan_names), "docstatus": 1}
	else:
		filters = {"docstatus": 1}

	filters = _merge_date_window(filters, from_date, to_date, default_days=30)

	repayments = frappe.get_all(
		"Loan Repayment",
		filters=filters,
		fields=["name", "against_loan", "amount_paid", "posting_date", "docstatus"],
		order_by="posting_date desc",
		limit_page_length=0,
	)

	# Friendly status
	for r in repayments:
		r["status"] = _friendly_docstatus(r.pop("docstatus", 0))

	by_officer: dict = {}
	total = 0
	for r in repayments:
		loan = frappe.db.get_value(
			"Loan", r.against_loan,
			["custom_loan_officer", "custom_lms_branch", "applicant"],
			as_dict=True,
		)
		# Branch filter: skip if branch is set and loan is in another branch.
		if branch and loan and loan.get("custom_lms_branch") and loan["custom_lms_branch"] != branch:
			continue
		r["customer_name"] = (
			frappe.db.get_value("Customer", loan.applicant, "customer_name")
			if loan and loan.applicant else ""
		)
		officer_name = ""
		if loan and loan.custom_loan_officer:
			officer_name = (
				frappe.db.get_value("Employee", loan.custom_loan_officer, "employee_name")
				or loan.custom_loan_officer
			)
		r["officer_name"] = officer_name
		if officer_name not in by_officer:
			by_officer[officer_name] = {"officer_name": officer_name, "count": 0, "total": 0}
		by_officer[officer_name]["count"] += 1
		by_officer[officer_name]["total"] += flt(r.amount_paid)
		total += flt(r.amount_paid)

	return {
		"repayments": repayments,
		"by_officer": list(by_officer.values()),
		"total_collected": total,
		"count": len(repayments),
	}


# ---------------------------------------------------------------------------
# Disbursement report
# ---------------------------------------------------------------------------

def disbursement_report(
	*,
	from_date: str | None = None,
	to_date: str | None = None,
	branch: str | None = None,
	officer: str | None = None,
) -> dict:
	"""Disbursement report: disbursements in a date range, grouped by officer.

	Args:
		from_date: optional start date (inclusive).
		to_date: optional end date (inclusive).
		branch: optional branch filter.
		officer: optional Employee name filter.

	Returns:
		dict with ``disbursements``, ``by_officer``, ``total_disbursed``,
		``count``.
	"""
	if officer:
		loan_names = frappe.get_all(
			"Loan",
			filters={"custom_loan_officer": officer, "docstatus": 1},
			pluck="name",
		)
		if not loan_names:
			return {"disbursements": [], "by_officer": [], "total_disbursed": 0, "count": 0}
		filters: dict = {"against_loan": ("in", loan_names), "docstatus": 1}
	else:
		filters = {"docstatus": 1}

	filters = _merge_date_window(filters, from_date, to_date, default_days=30)

	disbursements = frappe.get_all(
		"Loan Disbursement",
		filters=filters,
		fields=["name", "against_loan", "disbursed_amount", "posting_date", "status"],
		order_by="posting_date desc",
		limit_page_length=0,
	)

	by_officer: dict = {}
	total = 0
	for d in disbursements:
		loan = frappe.db.get_value(
			"Loan", d.against_loan,
			["custom_loan_officer", "custom_lms_branch", "applicant"],
			as_dict=True,
		)
		if branch and loan and loan.get("custom_lms_branch") and loan["custom_lms_branch"] != branch:
			continue
		officer_name = ""
		if loan and loan.custom_loan_officer:
			officer_name = (
				frappe.db.get_value("Employee", loan.custom_loan_officer, "employee_name")
				or loan.custom_loan_officer
			)
		d["officer_name"] = officer_name
		d["customer_name"] = (
			frappe.db.get_value("Customer", loan.applicant, "customer_name")
			if loan and loan.applicant else ""
		)
		if officer_name not in by_officer:
			by_officer[officer_name] = {"officer_name": officer_name, "count": 0, "total": 0}
		by_officer[officer_name]["count"] += 1
		by_officer[officer_name]["total"] += flt(d.disbursed_amount)
		total += flt(d.disbursed_amount)

	return {
		"disbursements": disbursements,
		"by_officer": list(by_officer.values()),
		"total_disbursed": total,
		"count": len(disbursements),
	}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _merge_date_window(
	filters: dict,
	from_date: str | None,
	to_date: str | None,
	default_days: int | None = None,
) -> dict:
	"""Apply a date-window filter to ``posting_date``.

	Handles all four cases (from-only / to-only / both / neither).
	If neither is provided and ``default_days`` is set, falls back to
	``from_date = today() - default_days``.
	"""
	f = dict(filters)
	if from_date and to_date:
		f["posting_date"] = ("between", [from_date, to_date])
	elif from_date:
		f["posting_date"] = (">=", from_date)
	elif to_date:
		f["posting_date"] = ("<=", to_date)
	elif default_days and "posting_date" not in f:
		f["posting_date"] = (">=", add_days(today(), -default_days))
	return f


def _friendly_docstatus(docstatus: int) -> str:
	"""Render a 0/1/2 docstatus as a human-friendly state."""
	if docstatus == 1:
		return "Submitted"
	if docstatus == 2:
		return "Cancelled"
	return "Draft"