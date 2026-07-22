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


def _is_admin() -> bool:
	return bool(set(frappe.get_roles()).intersection({"System Manager", "Administrator"}))


@frappe.whitelist()
def get_officer_dashboard():
	"""Branch-scoped KPIs for the Loan Officer portal landing."""
	_require_officer()
	branch = _officer_branch()
	employee = _officer_employee()
	company = frappe.db.get_single_value("Global Defaults", "default_company")

	# Pending applications in officer's branch — fail closed if unscoped.
	if branch:
		pending_apps = frappe.db.count(
			"Loan Application", {"docstatus": 0, "custom_lms_branch": branch}
		)
	elif _is_admin():
		pending_apps = frappe.db.count("Loan Application", {"docstatus": 0})
	else:
		pending_apps = 0

	# Active loans assigned to this officer
	loan_filters = {
		"docstatus": 1,
		"status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
	}
	if employee:
		loan_filters["custom_loan_officer"] = employee
	my_active_loans = frappe.db.count("Loan", loan_filters)

	# Loans awaiting disbursement (Drafts assigned to me, plus Sanctioned-but-
	# not-yet-disbursed). Surfaced on the dashboard so the officer sees an
	# actionable count, not just the active-loan number.
	pending_disbursement = 0
	if employee:
		pending_disbursement = frappe.db.count(
			"Loan",
			{
				"docstatus": ("in", [0, 1]),
				"custom_loan_officer": employee,
				"status": ("in", ["Draft", "Sanctioned"]),
			},
		)

	# Disbursed this month — scoped to the officer's loans (P1 fix: was system-wide).
	from frappe.utils import get_first_day, get_last_day

	month_start = get_first_day(today())
	month_end = get_last_day(today())
	disb_filters = {"docstatus": 1, "posting_date": (">=", month_start), "posting_date": ("<=", month_end)}
	if employee:
		officer_loans = frappe.get_all("Loan", {"custom_loan_officer": employee, "docstatus": 1}, pluck="name")
		if officer_loans:
			disb_filters["against_loan"] = ("in", officer_loans)
		else:
			disb_filters["against_loan"] = ("in", ["__none__"])
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

	# Leads in branch — fail closed if unscoped.
	if branch:
		branch_leads = frappe.db.count("Lead", {"custom_lms_branch": branch})
	elif _is_admin():
		branch_leads = frappe.db.count("Lead")
	else:
		branch_leads = 0

	return {
		"branch": branch,
		"employee": employee,
		"kpis": {
			"pending_applications": pending_apps,
			"my_active_loans": my_active_loans,
			"pending_disbursement": pending_disbursement,
			"disbursed_this_month": disbursed_this_month,
			"par_ratio": par_ratio,
			"par_count": par_count,
			"branch_leads": branch_leads,
		},
	}


@frappe.whitelist()
def get_pending_applications():
	"""Loan Applications pending review — branch-scoped; fail closed if unscoped."""
	_require_officer()
	branch = _officer_branch()

	if not branch and not _is_admin():
		return {"applications": []}

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
def get_assigned_loans():
	"""Loans assigned to the current officer, including pending disbursement.

	Returns two sections so the officer can act on approved-but-not-disbursed
	loans (drafts/sanctioned) and monitor active ones:

	  - ``pending``: docstatus=0 (Draft) — manager approved, awaiting disbursement
	  - ``active``:  docstatus=1 + status in (Disbursed, Active, Partially Disbursed)
	"""
	_require_officer()
	employee = _officer_employee()
	if not employee:
		return {"pending": [], "active": []}

	def _enrich(loans):
		for loan in loans:
			loan["customer_name"] = (
				frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else ""
			)
			loan["outstanding"] = flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0)
			loan["dpd"] = loan.custom_days_past_due or 0
		return loans

	# Drafts: manager approved, awaiting the officer to disburse.
	pending = _enrich(
		frappe.get_all(
			"Loan",
			filters={
				"docstatus": 0,
				"custom_loan_officer": employee,
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
				"repayment_periods",
				"rate_of_interest",
				"loan_product",
				"creation",
			],
			order_by="creation asc",
			limit_page_length=100,
		)
	)

	# Sanctioned (submitted but not yet disbursed) — the officer is allowed to
	# disburse these too in case the manager submitted without auto-disbursing.
	sanctioned = _enrich(
		frappe.get_all(
			"Loan",
			filters={
				"docstatus": 1,
				"custom_loan_officer": employee,
				"status": "Sanctioned",
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
				"repayment_periods",
				"rate_of_interest",
				"loan_product",
				"creation",
			],
			order_by="creation asc",
			limit_page_length=100,
		)
	)

	# Active (disbursed / ongoing).
	active = _enrich(
		frappe.get_all(
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
				"repayment_periods",
				"rate_of_interest",
				"loan_product",
				"creation",
			],
			order_by="modified desc",
			limit_page_length=100,
		)
	)

	return {"pending": pending + sanctioned, "active": active}


@frappe.whitelist()
def disburse_assigned_loan(loan_name: str, disbursed_amount: float | None = None):
	"""Disburse a loan assigned to the current officer.

	Two-phase operation:

	1. If the Loan is still a draft (``docstatus=0``), submit it first so
	   the lending app's ``on_submit`` hook can build the repayment schedule
	   and set status to ``Sanctioned``.
	2. Create a Loan Disbursement for the full amount (or ``disbursed_amount``
	   if provided) and submit it. Submission of the disbursement flips the
	   loan's status to ``Disbursed`` / ``Active`` and updates portfolio KPIs.

	Only loans where ``custom_loan_officer == current Employee`` can be
	disbursed by the officer — prevents cross-portal tampering.

	Round-1 expert-board fixes:
	- Idempotency: refuse if a non-cancelled Loan Disbursement already
	  exists for this loan. Prevents duplicate disbursements on a network
	  blip / double-click.
	- KYC re-validation: re-read the borrower's KYC status at disbursement
	  time. If KYC has flipped to "Rejected" or expired between approval
	  and disbursement, refuse with a structured error.
	"""
	_require_officer()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	employee = _officer_employee()
	loan = frappe.get_doc("Loan", loan_name)

	if not employee or loan.get("custom_loan_officer") != employee:
		frappe.throw(_("This loan is not assigned to you."), frappe.PermissionError)

	# Refuse to disburse a loan that is already closed, written off, or cancelled.
	if loan.status in ("Closed", "Written Off", "Cancelled"):
		frappe.throw(_("Loan status is {0}. Cannot disburse.").format(loan.status))

	# Refuse to re-disburse a loan that is already disbursed/active.
	# The idempotency guard below catches existing Loan Disbursement docs,
	# but this extra check prevents the edge case where a disbursement was
	# cancelled and the loan is already in Disbursed/Active status from
	# a prior (non-cancelled) disbursement.
	if loan.status in ("Disbursed", "Active"):
		frappe.throw(
			_("Loan is already {0}. Cannot disburse again.").format(loan.status)
		)

	# Idempotency guard. A successful (non-cancelled) disbursement already
	# exists for this loan — refuse the second one.
	existing = frappe.get_all(
		"Loan Disbursement",
		filters={"against_loan": loan.name, "docstatus": ("<", 2)},
		fields=["name", "disbursed_amount", "posting_date"],
		limit_page_length=1,
	)
	if existing:
		frappe.throw(
			_("Loan {0} has already been disbursed via {1} on {2}. "
			  "Cancel that disbursement first if you need to redo it.").format(
				loan.name, existing[0].name, existing[0].posting_date
			)
		)

	# KYC re-check at disbursement time. KYC can be flipped to Rejected or
	# expire between approval and disbursement — refuse to release funds.
	if loan.applicant:
		kyc = frappe.db.get_value(
			"LMS Borrower Compliance",
			{"customer": loan.applicant},
			["kyc_status", "kyc_expiry_date"],
			as_dict=True,
		)
		if kyc:
			kyc_status = (kyc.get("kyc_status") or "").lower()
			if kyc_status in ("rejected", "expired", "blocked"):
				frappe.throw(
					_("KYC for borrower is {0}. Disbursement blocked — "
					  "re-verify KYC before disbursing.").format(kyc.get("kyc_status"))
				)
			# Check expiry date if present.
			expiry = kyc.get("kyc_expiry_date")
			if expiry and getdate(expiry) < getdate(today()):
				frappe.throw(
					_("KYC expired on {0}. Disbursement blocked — renew KYC first.").format(expiry)
				)

	amount = flt(disbursed_amount) if disbursed_amount else flt(loan.loan_amount)
	if amount <= 0:
		frappe.throw(_("Disbursement amount must be positive."))
	if amount > flt(loan.loan_amount):
		frappe.throw(
			_("Disbursement amount {0} exceeds the approved loan amount {1}. " 
			  "Partial disbursements must not exceed the sanctioned principal.").format(
				amount, flt(loan.loan_amount)
			)
		)

	# Phase 1: submit the Loan if it's still a draft.
	if loan.docstatus == 0:
		loan.flags.ignore_permissions = True
		loan.submit()
		loan.reload()

	# Phase 2: create + submit a Loan Disbursement.
	# Portal staff lack create/submit perms on Loan Disbursement and nested
	# Loan Repayment Schedule docs. Bypass via ignore_permissions / flags —
	# never swap session user to Administrator.
	# Pull mode_of_payment / disbursement_account from the loan or fall back to
	# the first available Mode of Payment (set up by install hooks). Without
	# these the lending app refuses to submit with a generic error.
	mop = loan.get("mode_of_payment") or frappe.db.get_value("Mode of Payment", {}, "name")
	if not mop:
		frappe.throw(
			_("Disbursement account is not configured. Set up a Mode of Payment in Accounting before disbursing loans.")
		)
	disb_account = loan.get("disbursement_account") or loan.get("payment_account")
	disb = frappe.get_doc(
		{
			"doctype": "Loan Disbursement",
			"against_loan": loan.name,
			"applicant_type": loan.applicant_type,
			"applicant": loan.applicant,
			"company": loan.company,
			"disbursed_amount": amount,
			"posting_date": today(),
			"disbursement_date": today(),
			"mode_of_payment": mop,
			"disbursement_account": disb_account,
		}
	)
	disb.flags.ignore_permissions = True
	disb.insert()
	disb.submit()

	# Append-only LMS Audit Event for the disbursement (round-1 audit fix).
	from lms_saas.api.compliance import write_audit_event
	write_audit_event(
		event_type="Loan Disbursement:officer",
		reference_doctype="Loan Disbursement",
		reference_name=disb.name,
		amount=flt(amount),
		company=loan.company,
		details=f"loan={loan.name}; officer={frappe.session.user}",
		critical=True,
	)

	# Notify the borrower that funds have been released (R4 fix).
	try:
		from lms_saas.api.manager import _notify_borrower_disbursement
		_notify_borrower_disbursement(loan, disb)
	except Exception:
		pass

	# Invalidate dashboard cache so KPIs reflect the new active loan.
	from lms_saas.api.dashboard import invalidate_dashboard_cache
	invalidate_dashboard_cache()

	return {
		"status": "disbursed",
		"loan": loan.name,
		"disbursement": disb.name,
		"amount": amount,
		"message": _("Loan {0} disbursed — {1}.").format(loan.name, disb.name),
	}



@frappe.whitelist()
def submit_application_on_behalf(
	customer: str,
	loan_amount: float,
	loan_product: str | None = None,
	repayment_periods: int = 6,
	repayment_method: str = "Repay Over Number of Periods",
	repayment_start_date: str | None = None,
	rate_of_interest: float | None = None,
	posting_date: str | None = None,
):
	"""Officer submits a Loan Application on behalf of a borrower.

	Automatically tags the application with the officer's branch and Employee
	record so the manager portal can filter by branch. Defaults to the
	product's configured rate / start date if not supplied.
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

	# Round-3 expert-board fix: KYC gate at submission time. An officer
	# cannot create a loan application for a borrower whose KYC is not
	# in a state we can act on. Mirrors the manager-side checklist so
	# the two paths never disagree.
	kyc_name = frappe.db.get_value(
		"LMS Borrower Compliance", {"customer": customer}, "name"
	)
	if not kyc_name:
		frappe.throw(
			_("Borrower has no KYC record. Capture KYC (ID + consent + proof of address) before submitting a loan application.")
		)
	kyc = frappe.get_doc("LMS Borrower Compliance", kyc_name)
	kyc_status = (kyc.get("kyc_status") or "").lower()
	if kyc_status not in ("approved", "verified", "complete"):
		frappe.throw(
			_("KYC status is {0}. Cannot submit a loan application until KYC is approved.").format(kyc.get("kyc_status"))
		)
	if not cint(kyc.get("consent_given")):
		frappe.throw(
			_("Borrower consent is not on file. Get the borrower's signed consent (data + credit bureau) before submission.")
		)

	# If the officer didn't override the rate, use the product's default.
	if rate_of_interest is None or flt(rate_of_interest) <= 0:
		rate_of_interest = (
			frappe.db.get_value("Loan Product", loan_product, "rate_of_interest") or 0
		)

	app = frappe.get_doc(
		{
			"doctype": "Loan Application",
			"applicant_type": "Customer",
			"applicant": customer,
			"company": company,
			"loan_product": loan_product,
			"loan_amount": loan_amount,
			"repayment_periods": int(repayment_periods),
			"repayment_method": repayment_method or "Repay Over Number of Periods",
			"repayment_start_date": repayment_start_date or "",
			"rate_of_interest": flt(rate_of_interest),
			"posting_date": posting_date or frappe.utils.nowdate(),
			"custom_lms_branch": branch or "",
			"custom_loan_officer": employee or "",
		}
	)
	app.flags.ignore_permissions = True
	app.insert()

	return {"application": app.name, "status": "Draft"}


@frappe.whitelist()
def get_officer_leads():
	"""Leads for the officer — branch-scoped; fail closed if unscoped."""
	_require_officer()
	branch = _officer_branch()

	if not branch and not _is_admin():
		return {"leads": []}

	filters = {}
	if branch:
		filters["custom_lms_branch"] = branch
	else:
		filters["status"] = ["not in", ["Converted", "Do Not Contact"]]

	leads = frappe.get_all(
		"Lead",
		filters=filters,
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
	"""List customers for the application form — branch-scoped; fail closed."""
	_require_officer()
	branch = _officer_branch()

	if not branch and not _is_admin():
		return {"customers": []}

	filters = {"disabled": 0}
	if branch:
		filters["custom_lms_branch"] = branch
	else:
		filters["customer_name"] = ["not like", "_Test%"]

	customers = frappe.get_all(
		"Customer",
		filters=filters,
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
	# New KYC fields — officer captures consent + proof of ID at onboarding
	# so we don't have to ask the borrower to upload separately.
	date_of_birth: str = "",
	gender: str = "",
	address_line1: str = "",
	city: str = "",
	id_document_proof: str = "",
	proof_of_address: str = "",
	consent_given: int | bool = 0,
	kyc_status: str = "Pending",
	customer_group: str = "",
	territory: str = "",
):
	"""Officer onboards a new borrower: creates Customer + Contact + User + KYC.

	Returns the Customer name + the LMS Borrower Compliance record name so
	the officer can immediately submit a loan application for the borrower
	from the same modal.

	All KYC fields are optional EXCEPT ``first_name``; if the officer can't
	capture consent + ID at the counter the customer is created with
	``kyc_status = "Pending"`` and the manager can require approval later.
	"""
	_require_officer()
	branch = _officer_branch()

	if not first_name or not first_name.strip():
		frappe.throw(_("First name is required."))

	full_name = " ".join(p for p in (first_name, last_name) if p).strip()
	# Fall back to defaults if the form didn't pass these.
	if not customer_group:
		customer_group = (
			frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
			or frappe.db.get_single_value("Selling Settings", "customer_group")
			or ""
		)
	if not territory:
		territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or ""

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
				"phone_nos": [{"phone": mobile_no}] if mobile_no else [],
				"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			}
		)
		contact.flags.ignore_permissions = True
		contact.insert()

	# Create LMS Borrower Compliance (KYC) record — required for origination.
	# Skip silently if the doctype isn't installed (fresh / dev sites).
	kyc_name = None
	if frappe.db.exists("DocType", "LMS Borrower Compliance"):
		kyc = frappe.get_doc(
			{
				"doctype": "LMS Borrower Compliance",
				"customer": customer.name,
				"national_id_number": national_id or "",
				"kyc_status": kyc_status or "Pending",
				"consent_given": cint(consent_given),
				"id_document_proof": id_document_proof or "",
				"proof_of_address": proof_of_address or "",
			}
		)
		kyc.flags.ignore_permissions = True
		kyc.insert()
		kyc_name = kyc.name

		# If consent given at onboarding, stamp the date.
		if cint(consent_given):
			kyc.consent_date = frappe.utils.now()
			kyc.flags.ignore_permissions = True
			kyc.save()

	return {
		"customer": customer.name,
		"customer_name": full_name,
		"kyc": kyc_name,
		"kyc_status": kyc_status or "Pending",
	}


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
	# Escape LIKE wildcards to prevent wildcard injection.
	query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	# Cap limit to prevent full-database PII dumps (P0 fix).
	limit = min(cint(limit) or 50, 100)

	if not branch and not _is_admin():
		return {"borrowers": []}

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
	branch = _officer_branch()
	if not _is_admin():
		if not branch:
			frappe.throw(_("No branch assigned — cannot view borrower."), frappe.PermissionError)
		if (cust.get("custom_lms_branch") or "") != branch:
			frappe.throw(_("Customer is not in your branch."), frappe.PermissionError)

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
	# Branch scoping — fail closed.
	branch = _officer_branch()
	if not _is_admin():
		if not branch:
			frappe.throw(_("No branch assigned — cannot update borrower."), frappe.PermissionError)
		if (cust.get("custom_lms_branch") or "") != branch:
			frappe.throw(_("Customer is not in your branch."), frappe.PermissionError)
	changed = []
	audit_bits = []
	if customer_name_new is not None:
		cust.customer_name = customer_name_new
		changed.append("customer_name")
	if email_id is not None:
		cust.email_id = email_id
		changed.append("email_id")
	if mobile_no is not None:
		cust.mobile_no = mobile_no
		changed.append("mobile_no")
	if national_id is not None:
		old_nid = cust.get("custom_national_id_number") or ""
		cust.custom_national_id_number = national_id
		changed.append("national_id")
		audit_bits.append(f"national_id:{old_nid}->{national_id}")
	cust.flags.ignore_permissions = True
	cust.save()

	# Audit event for customer update (P0 fix — officer-side was missing).
	try:
		from lms_saas.api.compliance import write_audit_event
		details = f"updated_by={frappe.session.user}; fields={','.join(changed) if changed else '-'}"
		if audit_bits:
			details += "; " + "; ".join(audit_bits)
		write_audit_event(
			event_type="Customer:update",
			reference_doctype="Customer",
			reference_name=customer_name,
			details=details,
		)
	except Exception:
		frappe.log_error(
			title="LMS audit event failed (officer customer update)",
			reference_doctype="Customer",
			reference_name=customer_name,
			message=frappe.get_traceback(),
		)

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

	# Branch scoping — fail closed.
	branch = _officer_branch()
	if not _is_admin():
		if not branch:
			frappe.throw(_("No branch assigned — cannot view loan."), frappe.PermissionError)
		if (loan.get("custom_lms_branch") or "") != branch:
			frappe.throw(_("Loan is not in your branch."), frappe.PermissionError)

	# Schedule
	# NOTE: Repayment Schedule has no 'paid' column — use 'demand_generated'
	# (Check) as a proxy for "this instalment has been billed/settled".
	schedule = frappe.get_all(
		"Repayment Schedule",
		filters={"parent": loan_name, "parenttype": "Loan"},
		fields=["payment_date", "principal_amount", "interest_amount", "total_payment", "balance_loan_amount", "demand_generated"],
		order_by="payment_date asc",
		limit_page_length=0,
	)
	# Map demand_generated to a 'paid' flag for the frontend's convenience.
	for row in schedule:
		row["paid"] = cint(row.get("demand_generated"))

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
	"""Record a loan repayment (officer can record on behalf of borrower).

	Round-4 expert-board fixes:
	- Officer-assignment check: refuse if loan is not assigned to this officer.
	- Branch scoping (fail closed).
	- Loan status check: refuse if loan is Closed, Written Off, or Cancelled.
	- Audit event with recorded_by context.
	"""
	_require_officer()
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Repayment amount must be positive."))

	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)
	employee = _officer_employee()

	# Officer-assignment check — an officer can only record repayments on
	# loans assigned to them (prevents cross-officer tampering).
	if not _is_admin() and employee and loan.get("custom_loan_officer") != employee:
		frappe.throw(_("This loan is not assigned to you."), frappe.PermissionError)

	# Branch scoping — fail closed.
	branch = _officer_branch()
	if not _is_admin():
		if not branch:
			frappe.throw(_("No branch assigned — cannot record repayment."), frappe.PermissionError)
		if (loan.get("custom_lms_branch") or "") != branch:
			frappe.throw(_("Loan is not in your branch."), frappe.PermissionError)

	# Refuse to record a repayment on a closed/written-off/cancelled loan.
	if loan.status in ("Closed", "Written Off", "Cancelled"):
		frappe.throw(_("Loan status is {0}. Cannot record repayment.").format(loan.status))

	# Idempotency guard — refuse duplicate repayments (P0 fix).
	existing_repay = frappe.get_all(
		"Loan Repayment",
		filters={
			"against_loan": loan_name,
			"amount_paid": amount,
			"posting_date": posting_date or today(),
			"docstatus": ("<", 2),
		},
		limit_page_length=1,
	)
	if existing_repay:
		frappe.throw(
			_("A repayment of {0} on {1} already exists for this loan (ref {2}). "
			  "Cancel it first if you need to redo it.").format(
				amount, posting_date or today(), existing_repay[0].name
			)
		)

	repayment = frappe.get_doc(
		{
			"doctype": "Loan Repayment",
			"against_loan": loan_name,
			"applicant_type": loan.applicant_type,
			"applicant": loan.applicant,
			"company": loan.company,
			"posting_date": posting_date or today(),
			"amount_paid": amount,
			"mode_of_payment": payment_mode or "Cash",
		}
	)
	repayment.flags.ignore_permissions = True
	repayment.insert()
	repayment.submit()

	# Audit event with portal context.
	from lms_saas.api.compliance import write_audit_event
	write_audit_event(
		event_type="Loan Repayment:officer",
		reference_doctype="Loan Repayment",
		reference_name=repayment.name,
		amount=flt(amount),
		company=loan.company,
		details=f"loan={loan_name}; recorded_by={frappe.session.user}; on_behalf_of=borrower",
		critical=True,
	)

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
	# Branch scoping — fail closed (P0 fix).
	branch = _officer_branch()
	if not _is_admin():
		if not branch:
			frappe.throw(_("No branch assigned — cannot view lead."), frappe.PermissionError)
		if (lead.get("custom_lms_branch") or "") != branch:
			frappe.throw(_("Lead is not in your branch."), frappe.PermissionError)
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