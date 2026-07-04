"""Loan Officer portal API — onboarding, applications, assigned loans.

All endpoints are guarded by ``_require_officer`` which allows the portal-only
``LMS Portal Staff`` role (or System Manager / Administrator for testing).
Branch scoping is automatic via ``staff.get_current_user_branch()``.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, today, cint, getdate

from lms_saas.install import PORTAL_STAFF_ROLE


def _require_officer():
	"""Loan Officer or Branch Manager only (per Employee.custom_lms_persona).

	Phase 4.4: tightened to persona-aware check. Collectors and Borrowers
	cannot call officer APIs (onboarding, applications, dashboard).
	"""
	if frappe.session.user == "Guest":
		frappe.throw("Please log in", frappe.PermissionError)
	roles = set(frappe.get_roles())
	if roles.intersection({"System Manager", "Administrator"}):
		return
	from lms_saas.utils.portal import resolve_portal_persona

	persona = resolve_portal_persona()
	if persona not in ("Loan Officer", "Branch Manager"):
		frappe.throw("Not permitted", frappe.PermissionError)


def _officer_branch() -> str | None:
	"""Resolve the officer's branch (Cost Center) for query scoping."""
	from lms_saas.api.staff import get_current_user_branch

	return get_current_user_branch()


def _officer_employee() -> str | None:
	"""Return the Employee name linked to the current user."""
	user = frappe.session.user
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


@frappe.whitelist()
def get_officer_dashboard():
	"""Branch-scoped KPIs for the Loan Officer portal landing."""
	_require_officer()
	branch = _officer_branch()
	employee = _officer_employee()
	company = frappe.db.get_single_value("Global Defaults", "default_company")

	# Pending applications in officer's branch
	app_filters = {"docstatus": 0, "custom_lms_branch": branch} if branch else {"docstatus": 0}
	pending_apps = frappe.db.count("Loan Application", app_filters)

	# Active loans assigned to this officer
	loan_filters = {
		"docstatus": 1,
		"status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
	}
	if employee:
		loan_filters["custom_loan_officer"] = employee
	my_active_loans = frappe.db.count("Loan", loan_filters)

	# Disbursed this month
	from frappe.utils import get_first_day, get_last_day

	month_start = get_first_day(today())
	month_end = get_last_day(today())
	disb_filters = {"docstatus": 1, "posting_date": (">=", month_start), "posting_date": ("<=", month_end)}
	disbursed_this_month = frappe.db.count("Loan Disbursement", disb_filters)

	# PAR ratio for officer's loans
	par_count = 0
	if employee:
		par_count = frappe.db.count(
			"Loan",
			{
				"docstatus": 1,
				"custom_loan_officer": employee,
				"custom_days_past_due": (">", 30),
			},
		)

	par_ratio = flt(par_count) / flt(my_active_loans) if my_active_loans else 0

	# Leads in branch
	lead_filters = {"custom_lms_branch": branch} if branch else {}
	branch_leads = frappe.db.count("Lead", lead_filters)

	return {
		"branch": branch,
		"employee": employee,
		"kpis": {
			"pending_applications": pending_apps,
			"my_active_loans": my_active_loans,
			"disbursed_this_month": disbursed_this_month,
			"par_ratio": par_ratio,
			"par_count": par_count,
			"branch_leads": branch_leads,
		},
	}


@frappe.whitelist()
def get_pending_applications():
	"""Loan Applications pending review — prefers branch, falls back to all."""
	_require_officer()
	branch = _officer_branch()

	applications = []
	if branch:
		applications = frappe.get_all(
			"Loan Application",
			filters={"docstatus": 0, "custom_lms_branch": branch},
			fields=[
				"name",
				"applicant",
				"applicant_type",
				"loan_amount",
				"loan_product",
				"repayment_periods",
				"status",
				"creation",
				"custom_lms_branch",
				"custom_loan_officer",
			],
			order_by="creation desc",
			limit_page_length=50,
		)

	# Fallback: if no apps in branch, show all pending
	if not applications:
		applications = frappe.get_all(
			"Loan Application",
			filters={"docstatus": 0},
			fields=[
				"name",
				"applicant",
				"applicant_type",
				"loan_amount",
				"loan_product",
				"repayment_periods",
				"status",
				"creation",
				"custom_lms_branch",
				"custom_loan_officer",
			],
			order_by="creation desc",
			limit_page_length=50,
		)

	for app in applications:
		app["customer_name"] = (
			frappe.db.get_value("Customer", app.applicant, "customer_name") if app.applicant else ""
		)
		app["product_name"] = (
			frappe.db.get_value("Loan Product", app.loan_product, "product_name") if app.loan_product else ""
		)

	return {"applications": applications}


@frappe.whitelist()
def get_my_loans_as_officer():
	"""Active loans assigned to the current officer."""
	_require_officer()
	employee = _officer_employee()
	if not employee:
		return {"loans": []}

	loans = frappe.get_all(
		"Loan",
		filters={
			"docstatus": 1,
			"custom_loan_officer": employee,
			"status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
		},
		fields=[
			"name",
			"applicant",
			"applicant_type",
			"loan_amount",
			"total_payment",
			"total_amount_paid",
			"status",
			"custom_days_past_due",
			"custom_lms_branch",
		],
		order_by="modified desc",
		limit_page_length=100,
	)

	for loan in loans:
		loan["customer_name"] = (
			frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else ""
		)
		loan["outstanding"] = flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0)
		loan["dpd"] = loan.custom_days_past_due or 0

	return {"loans": loans}


@frappe.whitelist()
def submit_application_on_behalf(
	customer: str,
	loan_amount: float,
	loan_product: str | None = None,
	repayment_periods: int = 6,
):
	"""Officer submits a Loan Application on behalf of a borrower.

	Automatically tags the application with the officer's branch and Employee
	record so the manager portal can filter by branch.
	"""
	_require_officer()
	branch = _officer_branch()
	employee = _officer_employee()
	company = frappe.db.get_single_value("Global Defaults", "default_company")

	if not loan_product:
		loan_product = frappe.db.get_value(
			"Loan Product", {"company": company, "product_code": "LMS-STD"}, "name"
		)

	loan_amount = flt(loan_amount)
	if loan_amount <= 0:
		frappe.throw(_("Loan amount must be positive."))

	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found.").format(customer))

	app = frappe.get_doc(
		{
			"doctype": "Loan Application",
			"applicant_type": "Customer",
			"applicant": customer,
			"company": company,
			"loan_product": loan_product,
			"loan_amount": loan_amount,
			"repayment_periods": int(repayment_periods),
			"rate_of_interest": frappe.db.get_value("Loan Product", loan_product, "rate_of_interest") or 0,
			"custom_lms_branch": branch or "",
			"custom_loan_officer": employee or "",
		}
	)
	app.flags.ignore_permissions = True
	app.insert()

	return {"application": app.name, "status": "Draft"}


@frappe.whitelist()
def get_officer_leads():
	"""Leads for the officer — prefers branch, falls back to all."""
	_require_officer()
	branch = _officer_branch()

	leads = []
	if branch:
		leads = frappe.get_all(
			"Lead",
			filters={"custom_lms_branch": branch},
			fields=[
				"name",
				"lead_name",
				"email_id",
				"mobile_no",
				"status",
				"source",
				"custom_consent_given",
				"custom_lms_branch",
			],
			order_by="creation desc",
			limit_page_length=50,
		)

	if not leads:
		leads = frappe.get_all(
			"Lead",
			filters={"status": ["not in", ["Converted", "Do Not Contact"]]},
			fields=[
				"name",
				"lead_name",
				"email_id",
				"mobile_no",
				"status",
				"source",
				"custom_consent_given",
				"custom_lms_branch",
			],
			order_by="creation desc",
			limit_page_length=50,
		)

	return {"leads": leads}


@frappe.whitelist()
def convert_lead(lead_name: str):
	"""Convert a Lead to a Customer (wraps crm.convert_lead_to_borrower)."""
	_require_officer()
	from lms_saas.api.crm import convert_lead_to_borrower

	return convert_lead_to_borrower(lead_name)


@frappe.whitelist()
def get_officer_customers():
	"""List customers for the application form.

	Prefers customers in the officer's branch; falls back to all customers
	if none are found in the branch (e.g. demo data without branch tags).
	"""
	_require_officer()
	branch = _officer_branch()

	customers = []
	if branch:
		customers = frappe.get_all(
			"Customer",
			filters={"disabled": 0, "custom_lms_branch": branch},
			fields=["name", "customer_name", "email_id", "mobile_no"],
			order_by="customer_name asc",
			limit_page_length=100,
		)

	# Fallback: if no customers in branch, show all non-test customers
	if not customers:
		customers = frappe.get_all(
			"Customer",
			filters={"disabled": 0, "customer_name": ["not like", "_Test%"]},
			fields=["name", "customer_name", "email_id", "mobile_no"],
			order_by="customer_name asc",
			limit_page_length=100,
		)

	return {"customers": customers}


@frappe.whitelist()
def create_borrower(
	first_name: str,
	last_name: str = "",
	email: str = "",
	mobile_no: str = "",
	national_id: str = "",
):
	"""Officer onboards a new borrower: creates Customer + Contact + User.

	Returns the Customer name so the officer can immediately submit a loan
	application for them from the same modal.
	"""
	_require_officer()
	branch = _officer_branch()

	if not first_name or not first_name.strip():
		frappe.throw(_("First name is required."))

	full_name = " ".join(p for p in (first_name, last_name) if p).strip()

	# Create User (optional — email may be blank for walk-in borrowers)
	user_name = None
	if email and not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name,
				"last_name": last_name or "",
				"mobile_no": mobile_no or "",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		)
		if frappe.db.exists("Role", "Customer"):
			user.append("roles", {"role": "Customer"})
		user.flags.ignore_permissions = True
		user.insert()
		user_name = user.name

	# Create Customer
	customer_group = (
		frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		or frappe.db.get_single_value("Selling Settings", "customer_group")
		or ""
	)
	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or ""
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": full_name,
			"email_id": email or "",
			"mobile_no": mobile_no or "",
			"customer_group": customer_group or "",
			"territory": territory,
			"custom_lms_branch": branch or "",
			"custom_national_id_number": national_id or "",
		}
	)
	customer.flags.ignore_permissions = True
	customer.insert()

	# Create Contact linked to Customer
	if email or mobile_no:
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": first_name,
				"last_name": last_name or "",
				"email_ids": [{"email_id": email}] if email else [],
				"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			}
		)
		contact.flags.ignore_permissions = True
		contact.insert()

	return {"customer": customer.name, "customer_name": full_name}


@frappe.whitelist()
def get_loan_products():
	"""Available loan products for the application form."""
	_require_officer()
	company = frappe.db.get_single_value("Global Defaults", "default_company")

	products = frappe.get_all(
		"Loan Product",
		filters={"company": company, "disabled": 0},
		fields=["name", "product_name", "rate_of_interest", "maximum_loan_amount"],
	)

	return {"products": products}


# ---------------------------------------------------------------------------
# Borrower management (officer-level)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def search_borrowers(query: str = "", limit: int = 50):
	"""Search borrowers (Customers) by name, mobile, email, or national ID."""
	_require_officer()
	branch = _officer_branch()
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


@frappe.whitelist()
def get_borrower_detail(customer_name: str):
	"""Full borrower profile: contact info, KYC, loans, collateral."""
	_require_officer()
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

	# Recent repayments
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
):
	"""Update borrower profile fields (officer can edit customer info)."""
	_require_officer()
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
	cust.flags.ignore_permissions = True
	cust.save()

	return {"status": "updated", "customer": customer_name}


# ---------------------------------------------------------------------------
# Loan management (officer-level)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_loan_detail(loan_name: str):
	"""Full loan detail: schedule, repayments, collateral, borrower info."""
	_require_officer()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)

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
def record_repayment(loan_name: str, amount: float, payment_mode: str = "Cash", posting_date: str | None = None):
	"""Record a loan repayment (officer can record on behalf of borrower)."""
	_require_officer()
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


@frappe.whitelist()
def get_loan_estimate(loan_product: str, loan_amount: float, repayment_periods: int = 6):
	"""Estimate monthly payment for a loan product (officer calculator)."""
	_require_officer()
	loan_amount = flt(loan_amount)
	repayment_periods = cint(repayment_periods)
	if loan_amount <= 0 or repayment_periods <= 0:
		frappe.throw(_("Loan amount and repayment periods must be positive."))

	if not frappe.db.exists("Loan Product", loan_product):
		frappe.throw(_("Loan product {0} not found.").format(loan_product))

	product = frappe.db.get_value(
		"Loan Product", loan_product, ["rate_of_interest", "maximum_loan_amount"], as_dict=True
	)

	rate = flt(product.rate_of_interest or 0) / 100 / 12
	if rate > 0:
		monthly = loan_amount * rate * (1 + rate) ** repayment_periods / ((1 + rate) ** repayment_periods - 1)
	else:
		monthly = loan_amount / repayment_periods

	total_payment = monthly * repayment_periods
	total_interest = total_payment - loan_amount

	return {
		"loan_product": loan_product,
		"loan_amount": loan_amount,
		"rate_of_interest": flt(product.rate_of_interest or 0),
		"repayment_periods": repayment_periods,
		"monthly_payment": round(monthly, 2),
		"total_payment": round(total_payment, 2),
		"total_interest": round(total_interest, 2),
	}


# ---------------------------------------------------------------------------
# Leads management (extended)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_lead(
	first_name: str,
	last_name: str = "",
	email: str = "",
	mobile_no: str = "",
	source: str = "",
	notes: str = "",
):
	"""Officer creates a new Lead (prospective borrower)."""
	_require_officer()
	branch = _officer_branch()

	if not first_name or not first_name.strip():
		frappe.throw(_("First name is required."))

	full_name = " ".join(p for p in (first_name, last_name) if p).strip()

	lead = frappe.get_doc(
		{
			"doctype": "Lead",
			"lead_name": full_name,
			"first_name": first_name,
			"last_name": last_name or "",
			"email_id": email or "",
			"mobile_no": mobile_no or "",
			"source": source or "",
			"custom_lms_branch": branch or "",
			"notes": notes or "",
		}
	)
	lead.flags.ignore_permissions = True
	lead.insert()

	return {"lead": lead.name, "lead_name": full_name}


@frappe.whitelist()
def get_lead_detail(lead_name: str):
	"""Full lead detail with conversion status."""
	_require_officer()
	if not frappe.db.exists("Lead", lead_name):
		frappe.throw(_("Lead {0} not found.").format(lead_name))

	lead = frappe.get_doc("Lead", lead_name)
	return {
		"lead": {
			"name": lead.name,
			"lead_name": lead.lead_name,
			"email_id": lead.email_id or "",
			"mobile_no": lead.mobile_no or "",
			"status": lead.status,
			"source": lead.source or "",
			"custom_lms_branch": lead.get("custom_lms_branch", ""),
			"custom_consent_given": lead.get("custom_consent_given", False),
			"custom_consent_date": str(lead.get("custom_consent_date", "")) if lead.get("custom_consent_date") else "",
		}
	}


# ---------------------------------------------------------------------------
# Officer reports
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_my_portfolio_summary():
	"""Portfolio summary for loans assigned to this officer."""
	_require_officer()
	employee = _officer_employee()
	if not employee:
		return {"summary": {}}

	loans = frappe.get_all(
		"Loan",
		filters={
			"docstatus": 1,
			"custom_loan_officer": employee,
			"status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
		},
		fields=[
			"name", "loan_amount", "total_payment", "total_amount_paid",
			"custom_days_past_due", "status",
		],
		limit_page_length=0,
	)

	summary = {
		"total_loans": len(loans),
		"total_outstanding": 0,
		"par30_count": 0,
		"par60_count": 0,
		"par90_count": 0,
		"current_count": 0,
	}

	for loan in loans:
		outstanding = flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0)
		dpd = flt(loan.custom_days_past_due or 0)
		summary["total_outstanding"] += outstanding
		if dpd > 90:
			summary["par90_count"] += 1
		elif dpd > 60:
			summary["par60_count"] += 1
		elif dpd > 30:
			summary["par30_count"] += 1
		else:
			summary["current_count"] += 1

	return {"summary": summary}


@frappe.whitelist()
def get_my_arrears_report():
	"""Arrears aging for loans assigned to this officer."""
	_require_officer()
	employee = _officer_employee()
	if not employee:
		return {"buckets": {}, "loans": []}

	loans = frappe.get_all(
		"Loan",
		filters={
			"docstatus": 1,
			"custom_loan_officer": employee,
			"status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
		},
		fields=[
			"name", "applicant", "loan_amount", "total_payment", "total_amount_paid",
			"custom_days_past_due", "status",
		],
		limit_page_length=0,
	)

	buckets = {"current": [], "1_30": [], "31_60": [], "61_90": [], "90_plus": []}

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
		elif dpd <= 30:
			buckets["1_30"].append(row)
		elif dpd <= 60:
			buckets["31_60"].append(row)
		elif dpd <= 90:
			buckets["61_90"].append(row)
		else:
			buckets["90_plus"].append(row)

	return {"buckets": buckets, "total_loans": len(loans)}


@frappe.whitelist()
def get_my_collections_report(from_date: str | None = None, to_date: str | None = None):
	"""Collections report for loans assigned to this officer."""
	_require_officer()
	employee = _officer_employee()
	if not employee:
		return {"repayments": [], "total_collected": 0}

	# Get officer's loans
	loan_names = frappe.get_all(
		"Loan",
		filters={"custom_loan_officer": employee, "docstatus": 1},
		pluck="name",
	)
	if not loan_names:
		return {"repayments": [], "total_collected": 0}

	filters = {"against_loan": ("in", loan_names), "docstatus": 1}
	if from_date:
		filters["posting_date"] = (">=", from_date)
	if to_date:
		filters["posting_date"] = ("<=", to_date) if "posting_date" not in filters else ("between", [from_date, to_date])
	if not from_date:
		filters["posting_date"] = (">=", getdate(today().replace(day=1)))

	repayments = frappe.get_all(
		"Loan Repayment",
		filters=filters,
		fields=["name", "against_loan", "amount_paid", "posting_date", "status"],
		order_by="posting_date desc",
		limit_page_length=0,
	)

	total = sum(flt(r.amount_paid) for r in repayments)
	for r in repayments:
		r["customer_name"] = frappe.db.get_value(
			"Customer",
			frappe.db.get_value("Loan", r.against_loan, "applicant"),
			"customer_name",
		)

	return {"repayments": repayments, "total_collected": total, "count": len(repayments)}