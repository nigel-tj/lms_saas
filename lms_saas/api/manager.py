"""Branch Manager portal API — approvals, branch metrics, team performance.

All endpoints are guarded by ``_require_manager`` which allows the portal-only
``LMS Portal Staff`` role (or System Manager / Administrator for testing).
Branch scoping is automatic via ``staff.get_current_user_branch()``.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, today, add_days, cint

from lms_saas.install import PORTAL_STAFF_ROLE


def _require_manager():
	"""Branch Manager only (per Employee.custom_lms_persona); admins allowed.

	Phase 4.4: tightened from "any LMS Portal Staff" to persona-aware check.
	Borrowers, Loan Officers, and Collectors must NOT be able to call
	manager APIs (approvals, branch metrics, team performance).
	"""
	if frappe.session.user == "Guest":
		frappe.throw("Please log in", frappe.PermissionError)
	roles = set(frappe.get_roles())
	if roles.intersection({"System Manager", "Administrator"}):
		return
	# Use the same persona helper the nav uses — single source of truth.
	from lms_saas.utils.portal import resolve_portal_persona

	persona = resolve_portal_persona()
	if persona != "Branch Manager":
		frappe.throw("Not permitted", frappe.PermissionError)


def _manager_branch() -> str | None:
	"""Resolve the manager's branch (Cost Center) for query scoping."""
	from lms_saas.api.staff import get_current_user_branch

	return get_current_user_branch()


@frappe.whitelist()
def get_manager_dashboard():
	"""Branch-scoped KPIs for the Branch Manager portal landing."""
	_require_manager()
	branch = _manager_branch()

	# Reuse the dashboard metrics engine for portfolio KPIs
	from lms_saas.api.dashboard import _portfolio_metrics

	metrics = _portfolio_metrics()
	kpis = metrics["kpis"]
	risk_buckets = metrics["risk_buckets"]

	# Approval queue count
	app_filters = {"docstatus": 0}
	if branch:
		app_filters["custom_lms_branch"] = branch
	approval_queue_count = frappe.db.count("Loan Application", app_filters)

	# Team performance summary
	team = get_team_performance()
	team_count = len(team.get("officers", []))

	return {
		"branch": branch,
		"kpis": {
			"portfolio_outstanding": kpis.get("portfolio_outstanding", 0),
			"active_loans": kpis.get("active_loans", 0),
			"par30_outstanding": kpis.get("par30_outstanding", 0),
			"par90_outstanding": kpis.get("par90_outstanding", 0),
			"npa_count": kpis.get("npa_count", 0),
			"approval_queue_count": approval_queue_count,
			"team_count": team_count,
		},
		"risk_buckets": risk_buckets,
		"team": team,
	}


@frappe.whitelist()
def get_approval_queue():
	"""Loan Applications pending approval in the manager's branch."""
	_require_manager()
	branch = _manager_branch()

	filters = {"docstatus": 0}
	if branch:
		filters["custom_lms_branch"] = branch

	applications = frappe.get_all(
		"Loan Application",
		filters=filters,
		fields=[
			"name",
			"applicant",
			"applicant_type",
			"loan_amount",
			"loan_product",
			"repayment_periods",
			"rate_of_interest",
			"status",
			"creation",
			"custom_lms_branch",
			"custom_loan_officer",
		],
		order_by="creation desc",
		limit_page_length=100,
	)

	for app in applications:
		app["customer_name"] = (
			frappe.db.get_value("Customer", app.applicant, "customer_name") if app.applicant else ""
		)
		app["product_name"] = (
			frappe.db.get_value("Loan Product", app.loan_product, "product_name") if app.loan_product else ""
		)
		app["officer_name"] = (
			frappe.db.get_value("Employee", app.custom_loan_officer, "employee_name")
			if app.custom_loan_officer
			else ""
		)

	return {"applications": applications}


@frappe.whitelist()
def approve_application(application_name: str):
	"""Approve a Loan Application: submit it and create the Loan record."""
	_require_manager()
	if not frappe.db.exists("Loan Application", application_name):
		frappe.throw(_("Loan Application {0} not found.").format(application_name))

	app = frappe.get_doc("Loan Application", application_name)

	if app.docstatus != 0:
		frappe.throw(_("Only draft applications can be approved (current status: {0}).").format(app.docstatus))

	# Submit the application (triggers compliance/credit policy hooks)
	app.flags.ignore_permissions = True
	app.submit()

	# Create the Loan record from the application
	loan = frappe.new_doc("Loan")
	loan.applicant_type = app.applicant_type
	loan.applicant = app.applicant
	loan.loan_product = app.loan_product
	loan.company = app.company
	loan.loan_amount = app.loan_amount
	loan.rate_of_interest = app.rate_of_interest or 0
	loan.repayment_method = app.repayment_method or "Repay Over Number of Periods"
	loan.repayment_periods = app.repayment_periods
	loan.custom_lms_branch = app.custom_lms_branch or ""
	loan.custom_loan_officer = app.custom_loan_officer or ""
	loan.flags.ignore_permissions = True
	loan.insert()

	return {
		"status": "approved",
		"application": application_name,
		"loan": loan.name,
		"message": _("Application approved and Loan {0} created.").format(loan.name),
	}


@frappe.whitelist()
def reject_application(application_name: str, reason: str = ""):
	"""Reject a Loan Application: cancel it with a reason comment."""
	_require_manager()
	if not frappe.db.exists("Loan Application", application_name):
		frappe.throw(_("Loan Application {0} not found.").format(application_name))

	app = frappe.get_doc("Loan Application", application_name)

	if app.docstatus != 0:
		frappe.throw(_("Only draft applications can be rejected (current status: {0}).").format(app.docstatus))

	# Add a comment with the rejection reason
	if reason:
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": "Loan Application",
				"reference_name": application_name,
				"content": f"Application rejected: {reason}",
			}
		).insert(ignore_permissions=True)

	# Delete the draft application (drafts cannot be cancelled, only deleted)
	app.flags.ignore_permissions = True
	app.delete()

	return {
		"status": "rejected",
		"application": application_name,
		"message": _("Application {0} rejected.").format(application_name),
	}


@frappe.whitelist()
def get_team_performance():
	"""Aggregate loans by loan officer for the manager's branch."""
	_require_manager()
	branch = _manager_branch()

	filters = {
		"docstatus": 1,
		"status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
	}
	if branch:
		filters["custom_lms_branch"] = branch

	loans = frappe.get_all(
		"Loan",
		filters=filters,
		fields=[
			"name",
			"loan_amount",
			"total_principal_paid",
			"written_off_amount",
			"total_payment",
			"total_amount_paid",
			"custom_days_past_due",
			"custom_loan_officer",
		],
		limit_page_length=0,
	)

	officers: dict[str, dict] = {}
	for loan in loans:
		officer = loan.custom_loan_officer or "Unassigned"
		if officer not in officers:
			officers[officer] = {
				"officer": officer,
				"officer_name": (
					frappe.db.get_value("Employee", officer, "employee_name")
					if officer != "Unassigned"
					else "Unassigned"
				),
				"loan_count": 0,
				"outstanding": 0,
				"par_count": 0,
			}
		row = officers[officer]
		row["loan_count"] += 1
		row["outstanding"] += flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0)
		if flt(loan.custom_days_past_due or 0) > 30:
			row["par_count"] += 1

	return {"officers": list(officers.values())}


@frappe.whitelist()
def get_branch_loans(status: str | None = None):
	"""Paginated list of all loans in the manager's branch."""
	_require_manager()
	branch = _manager_branch()

	filters = {"docstatus": 1}
	if branch:
		filters["custom_lms_branch"] = branch
	if status:
		filters["status"] = status

	loans = frappe.get_all(
		"Loan",
		filters=filters,
		fields=[
			"name",
			"applicant",
			"applicant_type",
			"loan_amount",
			"total_payment",
			"total_amount_paid",
			"status",
			"custom_days_past_due",
			"custom_loan_officer",
		],
		order_by="modified desc",
		limit_page_length=200,
	)

	for loan in loans:
		loan["customer_name"] = (
			frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else ""
		)
		loan["outstanding"] = flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0)
		loan["dpd"] = loan.custom_days_past_due or 0
		loan["officer_name"] = (
			frappe.db.get_value("Employee", loan.custom_loan_officer, "employee_name")
			if loan.custom_loan_officer
			else ""
		)

	return {"loans": loans}


# ---------------------------------------------------------------------------
# Borrower management
# ---------------------------------------------------------------------------

@frappe.whitelist()
def search_borrowers(query: str = "", status: str | None = None, limit: int = 50):
	"""Search borrowers (Customers) in the manager's branch by name, mobile, email, or national ID."""
	_require_manager()
	branch = _manager_branch()
	query = (query or "").strip()
	limit = cint(limit) or 50

	filters = {"disabled": 0}
	if branch:
		filters["custom_lms_branch"] = branch

	or_conditions = []
	if query:
		or_conditions = [
			["customer_name", "like", f"%{query}%"],
			["mobile_no", "like", f"%{query}%"],
			["email_id", "like", f"%{query}%"],
			["custom_national_id_number", "like", f"%{query}%"],
		]

	customers = frappe.get_all(
		"Customer",
		filters=filters,
		or_filters=or_conditions if or_conditions else None,
		fields=[
			"name", "customer_name", "email_id", "mobile_no",
			"custom_lms_branch", "custom_national_id_number", "disabled",
		],
		order_by="customer_name asc",
		limit_page_length=limit,
	)

	# Enrich with loan counts and outstanding
	for c in customers:
		loan_filters = {"applicant": c.name, "docstatus": 1}
		c["loan_count"] = frappe.db.count("Loan", loan_filters)
		c["active_loans"] = frappe.db.count(
			"Loan",
			{**loan_filters, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
		)
		# Total outstanding across all loans
		loan_rows = frappe.get_all(
			"Loan",
			filters=loan_filters,
			fields=["total_payment", "total_amount_paid"],
			limit_page_length=0,
		)
		c["total_outstanding"] = sum(
			flt(r.total_payment or 0) - flt(r.total_amount_paid or 0) for r in loan_rows
		)
		# KYC compliance status
		c["kyc_status"] = frappe.db.get_value(
			"LMS Borrower Compliance", {"customer": c.name}, "kyc_status"
		) or "Pending"

	return {"borrowers": customers}


@frappe.whitelist()
def get_borrower_detail(customer_name: str):
	"""Full borrower profile: contact info, KYC, loans, collateral, compliance."""
	_require_manager()
	if not frappe.db.exists("Customer", customer_name):
		frappe.throw(_("Customer {0} not found.").format(customer_name))

	cust = frappe.get_doc("Customer", customer_name)
	customer = {
		"name": cust.name,
		"customer_name": cust.customer_name,
		"email_id": cust.email_id or "",
		"mobile_no": cust.mobile_no or "",
		"custom_lms_branch": cust.get("custom_lms_branch", ""),
		"custom_national_id_number": cust.get("custom_national_id_number", ""),
		"customer_group": cust.customer_group or "",
		"territory": cust.territory or "",
		"disabled": cust.disabled,
	}

	# Loans
	loans = frappe.get_all(
		"Loan",
		filters={"applicant": customer_name, "docstatus": 1},
		fields=[
			"name", "loan_amount", "total_payment", "total_amount_paid",
			"status", "rate_of_interest", "repayment_periods",
			"custom_days_past_due", "disbursed_amount",
		],
		order_by="creation desc",
		limit_page_length=0,
	)
	for loan in loans:
		loan["outstanding"] = flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0)
		loan["dpd"] = loan.custom_days_past_due or 0
	customer["loans"] = loans

	# KYC / Compliance
	compliance = frappe.db.get_value(
		"LMS Borrower Compliance",
		{"customer": customer_name},
		["name", "kyc_status", "consent_given", "consent_date", "aml_status", "credit_score"],
		as_dict=True,
	)
	customer["compliance"] = compliance or {}

	# Collateral
	collateral_links = frappe.get_all(
		"LMS Loan Collateral",
		filters={"parenttype": "Loan", "parent": ("in", [l["name"] for l in loans])},
		fields=["collateral", "collateral_type", "allocated_value", "parent"],
		limit_page_length=0,
	)
	customer["collateral"] = collateral_links

	# Repayments (recent 20)
	repayments = frappe.get_all(
		"Loan Repayment",
		filters={"applicant": customer_name, "docstatus": 1},
		fields=["name", "against_loan", "amount_paid", "posting_date"],
		order_by="posting_date desc",
		limit_page_length=20,
	)
	customer["recent_repayments"] = repayments

	return {"borrower": customer}


@frappe.whitelist()
def update_borrower(
	customer_name: str,
	customer_name_new: str | None = None,
	email_id: str | None = None,
	mobile_no: str | None = None,
	national_id: str | None = None,
	disabled: bool | None = None,
):
	"""Update borrower profile fields (manager can edit customer info)."""
	_require_manager()
	if not frappe.db.exists("Customer", customer_name):
		frappe.throw(_("Customer {0} not found.").format(customer_name))

	cust = frappe.get_doc("Customer", customer_name)
	if customer_name_new is not None:
		cust.customer_name = customer_name_new
	if email_id is not None:
		cust.email_id = email_id
	if mobile_no is not None:
		cust.mobile_no = mobile_no
	if national_id is not None:
		cust.custom_national_id_number = national_id
	if disabled is not None:
		cust.disabled = cint(disabled)
	cust.flags.ignore_permissions = True
	cust.save()

	return {"status": "updated", "customer": customer_name}


@frappe.whitelist()
def get_branch_borrowers(status: str | None = None, limit: int = 100):
	"""List all borrowers in the manager's branch with loan summary."""
	_require_manager()
	branch = _manager_branch()
	limit = cint(limit) or 100

	filters = {"disabled": 0}
	if branch:
		filters["custom_lms_branch"] = branch

	customers = frappe.get_all(
		"Customer",
		filters=filters,
		fields=[
			"name", "customer_name", "email_id", "mobile_no",
			"custom_lms_branch", "custom_national_id_number",
		],
		order_by="customer_name asc",
		limit_page_length=limit,
	)

	for c in customers:
		c["loan_count"] = frappe.db.count("Loan", {"applicant": c.name, "docstatus": 1})
		c["active_loans"] = frappe.db.count(
			"Loan",
			{"applicant": c.name, "docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
		)
		c["kyc_status"] = frappe.db.get_value(
			"LMS Borrower Compliance", {"customer": c.name}, "kyc_status"
		) or "Pending"

	return {"borrowers": customers}


# ---------------------------------------------------------------------------
# Loan management
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_loan_detail(loan_name: str):
	"""Full loan detail: schedule, repayments, collateral, borrower info."""
	_require_manager()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)
	branch = _manager_branch()
	if branch and loan.get("custom_lms_branch") and loan.get("custom_lms_branch") != branch:
		frappe.throw(_("Loan is not in your branch."), frappe.PermissionError)

	# Schedule
	schedule = frappe.get_all(
		"Repayment Schedule",
		filters={"parent": loan_name, "parenttype": "Loan"},
		fields=["payment_date", "principal_amount", "interest_amount", "total_payment", "paid", "balance_loan_amount"],
		order_by="payment_date asc",
		limit_page_length=0,
	)

	# Repayments
	repayments = frappe.get_all(
		"Loan Repayment",
		filters={"against_loan": loan_name, "docstatus": 1},
		fields=["name", "amount_paid", "posting_date"],
		order_by="posting_date desc",
		limit_page_length=50,
	)

	# Disbursements
	disbursements = frappe.get_all(
		"Loan Disbursement",
		filters={"against_loan": loan_name, "docstatus": 1},
		fields=["name", "disbursed_amount", "posting_date", "status"],
		order_by="posting_date desc",
		limit_page_length=20,
	)

	# Borrower info
	borrower_name = frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else ""

	# Collateral
	collateral = frappe.get_all(
		"LMS Loan Collateral",
		filters={"parent": loan_name, "parenttype": "Loan"},
		fields=["collateral", "collateral_type", "allocated_value"],
		limit_page_length=0,
	)

	return {
		"loan": {
			"name": loan.name,
			"applicant": loan.applicant,
			"applicant_type": loan.applicant_type,
			"borrower_name": borrower_name,
			"loan_amount": loan.loan_amount,
			"rate_of_interest": loan.rate_of_interest,
			"repayment_periods": loan.repayment_periods,
			"repayment_method": loan.repayment_method,
			"total_payment": loan.total_payment,
			"total_amount_paid": loan.total_amount_paid,
			"disbursed_amount": loan.disbursed_amount,
			"status": loan.status,
			"docstatus": loan.docstatus,
			"custom_lms_branch": loan.get("custom_lms_branch", ""),
			"custom_loan_officer": loan.get("custom_loan_officer", ""),
			"custom_days_past_due": loan.get("custom_days_past_due", 0),
			"outstanding": flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0),
			"dpd": loan.get("custom_days_past_due", 0),
		},
		"schedule": schedule,
		"repayments": repayments,
		"disbursements": disbursements,
		"collateral": collateral,
	}


@frappe.whitelist()
def disburse_loan(loan_name: str, disbursed_amount: float | None = None):
	"""Create a Loan Disbursement for an approved loan (manager action)."""
	_require_manager()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)
	if loan.docstatus != 1:
		frappe.throw(_("Loan must be submitted before disbursement."))

	amount = flt(disbursed_amount) if disbursed_amount else flt(loan.loan_amount)
	if amount <= 0:
		frappe.throw(_("Disbursement amount must be positive."))

	disb = frappe.get_doc(
		{
			"doctype": "Loan Disbursement",
			"against_loan": loan_name,
			"applicant_type": loan.applicant_type,
			"applicant": loan.applicant,
			"company": loan.company,
			"disbursed_amount": amount,
			"posting_date": today(),
		}
	)
	disb.flags.ignore_permissions = True
	disb.insert()
	disb.submit()

	return {
		"status": "disbursed",
		"loan": loan_name,
		"disbursement": disb.name,
		"amount": amount,
		"message": _("Loan {0} disbursed — {1}.").format(loan_name, disb.name),
	}


@frappe.whitelist()
def write_off_loan(loan_name: str, write_off_amount: float | None = None, reason: str = ""):
	"""Create a Loan Write Off for a non-performing loan."""
	_require_manager()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)
	if loan.docstatus != 1:
		frappe.throw(_("Loan must be submitted before write-off."))

	amount = flt(write_off_amount) if write_off_amount else flt(loan.loan_amount) - flt(loan.total_amount_paid or 0)
	if amount <= 0:
		frappe.throw(_("Write-off amount must be positive."))

	wo = frappe.get_doc(
		{
			"doctype": "Loan Write Off",
			"against_loan": loan_name,
			"applicant_type": loan.applicant_type,
			"applicant": loan.applicant,
			"company": loan.company,
			"write_off_amount": amount,
			"posting_date": today(),
		}
	)
	if reason:
		wo.remarks = reason
	wo.flags.ignore_permissions = True
	wo.insert()
	wo.submit()

	return {
		"status": "written_off",
		"loan": loan_name,
		"write_off": wo.name,
		"amount": amount,
		"message": _("Loan {0} written off — {1}.").format(loan_name, wo.name),
	}


@frappe.whitelist()
def record_repayment(loan_name: str, amount: float, payment_mode: str = "Cash", posting_date: str | None = None):
	"""Record a loan repayment (manager can record on behalf of borrower)."""
	_require_manager()
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Repayment amount must be positive."))

	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)
	repayment = frappe.get_doc(
		{
			"doctype": "Loan Repayment",
			"against_loan": loan_name,
			"applicant_type": loan.applicant_type,
			"applicant": loan.applicant,
			"company": loan.company,
			"posting_date": posting_date or today(),
			"amount_paid": amount,
		}
	)
	repayment.flags.ignore_permissions = True
	repayment.insert()
	repayment.submit()

	return {
		"status": "recorded",
		"loan": loan_name,
		"repayment": repayment.name,
		"amount": amount,
		"message": _("Repayment of {0} recorded for loan {1}.").format(amount, loan_name),
	}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_arrears_aging_report(as_on_date: str | None = None):
	"""Arrears aging report: loans grouped by DPD bucket (Current, 1-30, 31-60, 61-90, 90+)."""
	_require_manager()
	branch = _manager_branch()
	as_on = getdate(as_on_date) if as_on_date else getdate(today())

	filters = {"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])}
	if branch:
		filters["custom_lms_branch"] = branch

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
		"as_on_date": str(as_on),
		"buckets": buckets,
		"totals": totals,
		"total_loans": len(loans),
		"total_outstanding": sum(totals.values()),
	}


@frappe.whitelist()
def get_disbursement_report(from_date: str | None = None, to_date: str | None = None):
	"""Disbursement report: total disbursed in a date range, grouped by officer."""
	_require_manager()
	branch = _manager_branch()

	filters = {"docstatus": 1}
	if from_date:
		filters["posting_date"] = (">=", from_date)
	if to_date:
		if "posting_date" in filters:
			filters["posting_date"] = ("between", [from_date, to_date])
		else:
			filters["posting_date"] = ("<=", to_date)
	if not from_date:
		filters["posting_date"] = (">=", add_days(today(), -30))

	disbursements = frappe.get_all(
		"Loan Disbursement",
		filters=filters,
		fields=["name", "against_loan", "disbursed_amount", "posting_date", "status"],
		order_by="posting_date desc",
		limit_page_length=0,
	)

	by_officer = {}
	total = 0
	for d in disbursements:
		loan = frappe.db.get_value("Loan", d.against_loan, ["custom_loan_officer", "custom_lms_branch", "applicant"], as_dict=True)
		if branch and loan and loan.get("custom_lms_branch") and loan["custom_lms_branch"] != branch:
			continue
		officer = (loan.custom_loan_officer if loan else "") or "Unassigned"
		officer_name = frappe.db.get_value("Employee", officer, "employee_name") if officer != "Unassigned" else "Unassigned"
		if officer not in by_officer:
			by_officer[officer] = {"officer_name": officer_name, "count": 0, "total": 0}
		by_officer[officer]["count"] += 1
		by_officer[officer]["total"] += flt(d.disbursed_amount)
		total += flt(d.disbursed_amount)
		d["officer_name"] = officer_name
		d["customer_name"] = frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan and loan.applicant else ""

	return {
		"disbursements": disbursements,
		"by_officer": list(by_officer.values()),
		"total_disbursed": total,
		"count": len(disbursements),
	}


@frappe.whitelist()
def get_collections_report(from_date: str | None = None, to_date: str | None = None):
	"""Collections report: total collected in a date range, grouped by officer."""
	_require_manager()
	branch = _manager_branch()

	filters = {"docstatus": 1}
	if from_date:
		filters["posting_date"] = (">=", from_date)
	if to_date:
		if "posting_date" in filters:
			filters["posting_date"] = ("between", [from_date, to_date])
		else:
			filters["posting_date"] = ("<=", to_date)
	if not from_date:
		filters["posting_date"] = (">=", add_days(today(), -30))

	repayments = frappe.get_all(
		"Loan Repayment",
		filters=filters,
		fields=["name", "against_loan", "amount_paid", "posting_date", "status"],
		order_by="posting_date desc",
		limit_page_length=0,
	)

	by_officer = {}
	total = 0
	for r in repayments:
		loan = frappe.db.get_value("Loan", r.against_loan, ["custom_loan_officer", "custom_lms_branch", "applicant"], as_dict=True)
		if branch and loan and loan.get("custom_lms_branch") and loan["custom_lms_branch"] != branch:
			continue
		officer = (loan.custom_loan_officer if loan else "") or "Unassigned"
		officer_name = frappe.db.get_value("Employee", officer, "employee_name") if officer != "Unassigned" else "Unassigned"
		if officer not in by_officer:
			by_officer[officer] = {"officer_name": officer_name, "count": 0, "total": 0}
		by_officer[officer]["count"] += 1
		by_officer[officer]["total"] += flt(r.amount_paid)
		total += flt(r.amount_paid)
		r["officer_name"] = officer_name
		r["customer_name"] = frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan and loan.applicant else ""

	return {
		"repayments": repayments,
		"by_officer": list(by_officer.values()),
		"total_collected": total,
		"count": len(repayments),
	}


@frappe.whitelist()
def get_portfolio_summary():
	"""Portfolio at risk summary: outstanding, PAR buckets, NPA count, active loans."""
	_require_manager()
	branch = _manager_branch()

	filters = {"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])}
	if branch:
		filters["custom_lms_branch"] = branch

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
			summary["current_outstanding"] += outstanding

	summary["par_ratio"] = (
		(summary["par30_outstanding"] + summary["par60_outstanding"] + summary["par90_outstanding"])
		/ summary["total_outstanding"]
		if summary["total_outstanding"]
		else 0
	)

	return {"summary": summary}


@frappe.whitelist()
def get_loan_statement(loan_name: str, from_date: str | None = None, to_date: str | None = None):
	"""Loan statement of account: all transactions (disbursements + repayments) in date range."""
	_require_manager()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)
	branch = _manager_branch()
	if branch and loan.get("custom_lms_branch") and loan.get("custom_lms_branch") != branch:
		frappe.throw(_("Loan is not in your branch."), frappe.PermissionError)

	transactions = []

	# Disbursements
	disb_filters = {"against_loan": loan_name, "docstatus": 1}
	if from_date:
		disb_filters["posting_date"] = (">=", from_date)
	if to_date:
		disb_filters["posting_date"] = ("<=", to_date) if "posting_date" not in disb_filters else ("between", [from_date, to_date])

	disbursements = frappe.get_all(
		"Loan Disbursement",
		filters=disb_filters,
		fields=["name", "disbursed_amount", "posting_date", "status"],
		order_by="posting_date asc",
	)
	for d in disbursements:
		transactions.append({
			"date": d.posting_date,
			"type": "Disbursement",
			"reference": d.name,
			"debit": flt(d.disbursed_amount),
			"credit": 0,
			"balance": 0,  # running balance computed below
		})

	# Repayments
	rep_filters = {"against_loan": loan_name, "docstatus": 1}
	if from_date:
		rep_filters["posting_date"] = (">=", from_date)
	if to_date:
		rep_filters["posting_date"] = ("<=", to_date) if "posting_date" not in rep_filters else ("between", [from_date, to_date])

	repayments = frappe.get_all(
		"Loan Repayment",
		filters=rep_filters,
		fields=["name", "amount_paid", "posting_date", "status"],
		order_by="posting_date asc",
	)
	for r in repayments:
		transactions.append({
			"date": r.posting_date,
			"type": "Repayment",
			"reference": r.name,
			"debit": 0,
			"credit": flt(r.amount_paid),
			"balance": 0,
		})

	# Sort by date and compute running balance
	transactions.sort(key=lambda t: str(t["date"]))
	running = 0
	for t in transactions:
		running += t["debit"] - t["credit"]
		t["balance"] = round(running, 2)

	return {
		"loan": loan_name,
		"borrower": frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else "",
		"loan_amount": loan.loan_amount,
		"transactions": transactions,
		"opening_balance": 0,
		"closing_balance": round(running, 2),
	}


# ---------------------------------------------------------------------------
# Staff / team management
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_branch_staff():
	"""List all staff (Employees) in the manager's branch with their personas."""
	_require_manager()
	branch = _manager_branch()

	filters = {"status": "Active"}
	if branch:
		# OR-match across all branch-type fields that exist on the Employee meta.
		# Previously this broke after the first matching field, which excluded
		# employees whose branch was stored in a different field.
		emp_meta = frappe.get_meta("Employee")
		branch_fields = [bf for bf in ("branch", "cost_center", "custom_lms_branch") if emp_meta.has_field(bf)]
		if len(branch_fields) == 1:
			filters[branch_fields[0]] = branch
		elif len(branch_fields) > 1:
			or_conditions = " OR ".join(f"`{bf}` = %(branch)s" for bf in branch_fields)
			employees = frappe.db.sql(
				f"""SELECT name, employee_name, user_id, designation, status
					FROM `tabEmployee`
					WHERE status = 'Active' AND ({or_conditions})
					ORDER BY employee_name ASC
					LIMIT 100""",
				{"branch": branch},
				as_dict=True,
			)
			for emp in employees:
				emp["persona"] = frappe.db.get_value("Employee", emp.name, "custom_lms_persona") or ""
				emp["loan_count"] = frappe.db.count("Loan", {"custom_loan_officer": emp.name, "docstatus": 1})
			return {"staff": employees}

	employees = frappe.get_all(
		"Employee",
		filters=filters,
		fields=["name", "employee_name", "user_id", "designation", "status"],
		order_by="employee_name asc",
		limit_page_length=100,
	)

	for emp in employees:
		emp["persona"] = frappe.db.get_value("Employee", emp.name, "custom_lms_persona") or ""
		emp["loan_count"] = frappe.db.count("Loan", {"custom_loan_officer": emp.name, "docstatus": 1})

	return {"staff": employees}


@frappe.whitelist()
def get_branch_overview():
	"""Branch-level overview: KPIs, officer performance, arrears, disbursement summary."""
	_require_manager()
	branch = _manager_branch()

	# Reuse portfolio summary
	portfolio = get_portfolio_summary()

	# Today's collections
	today_collections = frappe.get_all(
		"Loan Repayment",
		filters={"docstatus": 1, "posting_date": today()},
		fields=["sum(amount_paid) as total"],
	)
	today_total = flt(today_collections[0].total) if today_collections else 0

	# Pending approvals
	app_filters = {"docstatus": 0}
	if branch:
		app_filters["custom_lms_branch"] = branch
	pending_approvals = frappe.db.count("Loan Application", app_filters)

	# Team performance
	team = get_team_performance()

	return {
		"branch": branch,
		"portfolio": portfolio.get("summary", {}),
		"today_collections": today_total,
		"pending_approvals": pending_approvals,
		"team": team,
	}


# ---------------------------------------------------------------------------
# Collateral management
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_collateral_register(loan_status: str | None = None):
	"""Collateral register: all pledged assets in the branch with linked loan info."""
	_require_manager()
	branch = _manager_branch()

	collateral = frappe.get_all(
		"LMS Collateral",
		fields=[
			"name", "collateral_type", "collateral_title", "market_value",
			"net_realizable_value", "status", "owner_customer",
		],
		order_by="creation desc",
		limit_page_length=200,
	)

	result = []
	for c in collateral:
		# Find linked loans
		links = frappe.get_all(
			"LMS Loan Collateral",
			filters={"collateral": c.name},
			fields=["parent", "allocated_value"],
			limit_page_length=0,
		)
		linked_loans = []
		for link in links:
			loan = frappe.db.get_value(
				"Loan", link.parent, ["name", "status", "applicant", "custom_lms_branch"], as_dict=True
			) if frappe.db.exists("Loan", link.parent) else None
			if loan:
				if branch and loan.get("custom_lms_branch") and loan["custom_lms_branch"] != branch:
					continue
				if loan_status and loan.status != loan_status:
					continue
				linked_loans.append({
					"loan": loan.name,
					"borrower": frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else "",
					"status": loan.status,
					"allocated_value": flt(link.allocated_value),
				})
		if linked_loans or not branch:
			result.append({**c, "linked_loans": linked_loans})

	return {"collateral": result}