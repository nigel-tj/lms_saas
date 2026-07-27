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
	# Top-level import so tests can monkey-patch staff.get_current_user_branch
	# via the staff module reference (R12 board feedback: late imports defeat
	# the monkey-patch and break branch-scope unit tests).
	import lms_saas.api.staff as _staff

	return _staff.get_current_user_branch()


def _officer_employee() -> str | None:
	"""Return the Employee name linked to the current user."""
	user = frappe.session.user
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def _is_admin() -> bool:
	return bool(set(frappe.get_roles()).intersection({"System Manager", "Administrator"}))


def _assert_branch_scope(target_branch: str | None) -> None:
	"""Fail closed: officers may only act on records in their own branch."""
	if _is_admin():
		return
	branch = _officer_branch()
	if not branch:
		frappe.throw("Not in your branch.", frappe.PermissionError)
	if target_branch and target_branch != branch:
		frappe.throw("Not in your branch.", frappe.PermissionError)


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
			"pending_disbursement": pending_disbursement,
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
	"""
	_require_officer()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	employee = _officer_employee()
	loan = frappe.get_doc("Loan", loan_name)

	if not employee or loan.get("custom_loan_officer") != employee:
		frappe.throw(_("This loan is not assigned to you."), frappe.PermissionError)

	amount = flt(disbursed_amount) if disbursed_amount else flt(loan.loan_amount)
	if amount <= 0:
		frappe.throw(_("Disbursement amount must be positive."))

	# Phase 1: submit the Loan if it's still a draft.
	if loan.docstatus == 0:
		loan.flags.ignore_permissions = True
		loan.submit()
		loan.reload()

	# Phase 2: create + submit a Loan Disbursement.
	# Two permission concerns:
	#   1. The officer only has LMS Portal Staff role, which lacks create/
	#      submit perms on Loan Disbursement (only Loan Manager / System
	#      Manager do). We switch to a system context to bypass.
	#   2. Four-eyes control (compliance.enforce_four_eyes) requires
	#      doc.owner (maker) ≠ submitter. We tag the disbursement as
	#      "owned" by the officer (so they're the maker) and submit as
	#      the manager (a different user, who already approved the
	#      underlying application — natural second pair of eyes).
	original_user = frappe.session.user
	disbursement_name = None
	try:
		# Create as the officer (becomes doc.owner = maker).
		frappe.set_user(original_user)
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
			}
		)
		# Insert as officer (LMS Portal Staff CAN create via the api
		# path's own whitelist check, but the lending app's on_update
		# tries to create a Loan Repayment Schedule which needs
		# create perm on that doctype). Use the lending helper which
		# runs as a system context.
		try:
			from lending.loan_management.doctype.loan.loan import make_loan_disbursement

			# Create the draft disbursement in a system context (the
			# lending helper + on_update hooks need perms that the
			# officer doesn't have).
			frappe.set_user("Administrator")
			disbursement = make_loan_disbursement(
				loan=loan.name,
				disbursement_amount=amount,
				submit=False,  # we set owner, then submit as system
				posting_date=today(),
				disbursement_date=today(),
			)
			# Reassign owner to the officer (maker). Frappe blocks
			# in-memory changes to `owner` after insert, so use db_set.
			frappe.db.set_value(
				"Loan Disbursement", disbursement.name, "owner", original_user
			)
			# Now submit — still as Administrator so the lending
			# app's submit hooks (which create Loan Repayment Schedule
			# + other related docs) have the perms they need.
			# Four-eyes passes: doc.owner=officer ≠ session.user=Administrator.
			disbursement.reload()
			disbursement.submit()
			disbursement_name = disbursement.name
		except Exception:
			frappe.set_user("Administrator")
			disb.insert(ignore_permissions=True)
			frappe.db.set_value("Loan Disbursement", disb.name, "owner", original_user)
			disb.reload()
			disb.submit()
			disbursement_name = disb.name
	finally:
		frappe.set_user(original_user)

	# Invalidate dashboard cache so KPIs reflect the new active loan.
	from lms_saas.api.dashboard import invalidate_dashboard_cache
	invalidate_dashboard_cache()

	return {
		"status": "disbursed",
		"loan": loan.name,
		"disbursement": disbursement_name,
		"amount": amount,
		"message": _("Loan {0} disbursed — {1}.").format(loan.name, disbursement_name),
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
	loan_type: str | None = None,
	purpose_of_finance: str | None = None,
	application_date: str | None = None,
	loan_start_date: str | None = None,
	expiry_date: str | None = None,
	max_enforceable_amount: float | None = None,
	security_interest_nature: str | None = None,
	collateral: list | None = None,
	marital_status: str | None = None,
	spouse_name: str | None = None,
	spouse_dob: str | None = None,
	spouse_contact: str | None = None,
	physical_address: str | None = None,
):
	"""Officer submits a Loan Application on behalf of a borrower.

	Automatically tags the application with the officer's branch and Employee
	record so the manager portal can filter by branch. Defaults to the
	product's configured rate / start date if not supplied.

	Household / spouse / physical-address fields are persisted back to the
	borrower's Customer record so the Loan Application form can capture or
	update them in one step.
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
			"rate_of_interest": flt(rate_of_interest),
			"posting_date": posting_date or frappe.utils.nowdate(),
			"custom_lms_branch": branch or "",
			"custom_loan_officer": employee or "",
			# lending app core field is `loan_purpose` (not purpose_of_finance)
			"loan_purpose": purpose_of_finance or "",
			# application_date + loan_type + loan_start_date are not core on
			# the lending Loan Application — stored on LMS custom fields.
			"lms_loan_type": loan_type or "",
			"lms_loan_start_date": loan_start_date or repayment_start_date or "",
			"lms_expiry_date": expiry_date or "",
			"lms_application_date": application_date or frappe.utils.nowdate(),
			"lms_max_enforceable_amount": flt(max_enforceable_amount) if max_enforceable_amount else 0,
			"lms_security_interest_nature": security_interest_nature or "",
		}
	)
	app.flags.ignore_permissions = True
	app.insert()

	# Persist household / spouse / physical-address fields captured on the
	# Loan Application form back to the Customer record. Doing it here (not in
	# update_borrower) means the officer only enters these once per session.
	household_fields = {}
	if marital_status: household_fields["lms_marital_status"] = marital_status
	if spouse_name:    household_fields["lms_spouse_name"] = spouse_name
	if spouse_dob:     household_fields["lms_spouse_dob"] = spouse_dob
	if spouse_contact: household_fields["lms_spouse_contact"] = spouse_contact
	if physical_address: household_fields["lms_physical_address"] = physical_address
	if household_fields:
		cust_doc = frappe.get_doc("Customer", customer)
		for k, v in household_fields.items():
			cust_doc.set(k, v)
		cust_doc.flags.ignore_permissions = True
		cust_doc.save()

	# Create linked LMS Collateral records (if any were captured in the form).
	if collateral and isinstance(collateral, list):
		for c in collateral:
			if not isinstance(c, dict):
				continue
			coll = frappe.get_doc(
				{
					"doctype": "LMS Collateral",
					"collateral_type": c.get("collateral_type") or "Other",
					"collateral_title": c.get("description") or "Collateral",
					"owner_customer": customer,
					"company": company,
					"branch": branch or "",
					"market_value": flt(c.get("collateral_value") or 0),
					"reference_no": c.get("serial_number") or c.get("vehicle_registration") or "",
					"lms_grantor": c.get("grantor") or "",
					# Vehicle-specific
					"lms_brand": c.get("brand") or "",
					"lms_model": c.get("model") or "",
					"lms_engine_number": c.get("engine_number") or "",
					"lms_vehicle_registration": c.get("vehicle_registration") or "",
					# Real Estate / Property
					"lms_stand_plot_number": c.get("stand_plot_number") or "",
					"lms_area_sqm": c.get("area_sqm") or "",
					# Equipment / Machinery
					"lms_manufacturer_year": cint(c.get("manufacturer_year") or 0),
					# Inventory / Stock
					"lms_inventory_sku": c.get("inventory_sku") or "",
					"lms_inventory_quantity": cint(c.get("inventory_quantity") or 0),
					# Cash Deposit / Lien
					"lms_cash_bank_name": c.get("cash_bank_name") or "",
					"lms_cash_account_number": c.get("cash_account_number") or "",
					# Securities / Shares
					"lms_security_certificate": c.get("security_certificate") or "",
					"lms_security_units": cint(c.get("security_units") or 0),
					# Third-Party Guarantee
					"lms_guarantor_name": c.get("guarantor_name") or "",
					"lms_guarantor_id": c.get("guarantor_id") or "",
					"lms_guarantor_relationship": c.get("guarantor_relationship") or "",
					"valuation_date": c.get("valuation_date") or "",
					"notes": c.get("description") or "",
					"loan_application": app.name,
				}
			)
			coll.flags.ignore_permissions = True
			coll.insert()

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
def set_lead_consent(lead_name: str):
	"""Record borrower consent on a lead (Loan Officer can do this after a
	phone call). Required before convert_lead() will succeed.

	Branch-scoped: refuses to touch a lead outside the officer's branch.
	"""
	_require_officer()
	if not frappe.db.exists("Lead", lead_name):
		frappe.throw(_("Lead {0} not found.").format(lead_name))

	_assert_branch_scope(frappe.db.get_value("Lead", lead_name, "custom_lms_branch"))

	lead = frappe.get_doc("Lead", lead_name)
	# LMS-defined consent fields. We write to both the custom field used by
	# the portal ("custom_consent_given" / "custom_consent_date") and the
	# standard Lead.consent flags, so downstream checks (convert_lead,
	# submissions) see a consistent answer.
	lead.flags.ignore_permissions = True
	now = frappe.utils.now()
	if lead.meta.has_field("custom_consent_given"):
		lead.custom_consent_given = 1
	if lead.meta.has_field("custom_consent_date"):
		lead.custom_consent_date = now
	if lead.meta.has_field("consent_given"):
		lead.consent_given = 1
	if lead.meta.has_field("consent_date"):
		lead.consent_date = now
	lead.save()

	return {"status": "ok", "lead": lead_name}


# ---------------------------------------------------------------------------
# KYC workflow (R15)
#
# The Loan Officer is the front-line KYC owner: at onboarding they collect
# national ID + proof of address, and during a borrower's life they review
# the record (approve / reject) as documents come in. The Manager (and the
# regulator) want a tamper-evident audit trail — every change must be
# recorded with operator + timestamp.
# ---------------------------------------------------------------------------

_KYC_STATUSES = ("Pending", "In Review", "Approved", "Rejected")


@frappe.whitelist()
def get_kyc_queue(status: str = "", limit: int = 100):
	"""List LMS Borrower Compliance records visible to the officer.

	Pre-filters by branch (the borrower's branch) and optionally by
	kyc_status so the queue can be sliced (e.g. only "Pending" or only
	"Rejected"). Officers see their own branch's KYC; admins see all.

	Returns the borrower name, branch, status, consent, and a
	`has_documents` flag so the officer can tell at a glance whether the
	borrower uploaded the ID + POA yet.
	"""
	_require_officer()
	branch = _officer_branch()

	filters = {}
	if status and status in _KYC_STATUSES:
		filters["kyc_status"] = status

	# Borrowers in the officer's branch (when set). When the site is in
	# "demo" mode (no branch scoping) the manager-side dashboard already
	# returns everything; we mirror that here for parity.
	customer_filters = {}
	if branch and not _is_admin():
		customer_filters["custom_lms_branch"] = branch

	borrower_names = set(
		frappe.get_all(
			"Customer",
			filters=customer_filters,
			pluck="name",
		)
	)
	if borrower_names:
		filters["customer"] = ("in", list(borrower_names))

	records = frappe.get_all(
		"LMS Borrower Compliance",
		filters=filters,
		fields=[
			"name", "customer", "kyc_status", "consent_given", "consent_date",
			"national_id_number", "id_document_proof", "proof_of_address",
			"aml_status", "aml_screened_at", "modified",
		],
		order_by="modified desc",
		limit_page_length=limit,
	)

	# Enrich with customer name + a has_documents flag for the queue UI.
	enriched = []
	for r in records:
		cust = frappe.db.get_value(
			"Customer", r.customer,
			["customer_name", "custom_lms_branch"],
			as_dict=True,
		)
		r["customer_name"] = cust.customer_name if cust else r.customer
		r["branch"] = cust.custom_lms_branch if cust else ""
		r["has_id_doc"] = bool(r.id_document_proof)
		r["has_poa"] = bool(r.proof_of_address)
		r["has_documents"] = r["has_id_doc"] and r["has_poa"]
		enriched.append(r)

	# Counts for the KPI strip.
	counts = {"pending": 0, "in_review": 0, "approved": 0, "rejected": 0, "no_kyc": 0}
	for r in enriched:
		key = (r.kyc_status or "Pending").lower().replace(" ", "_")
		if key in counts:
			counts[key] += 1
	# Borrowers with no KYC at all — also a remediation target.
	if borrower_names:
		kyc_customers = set(frappe.get_all("LMS Borrower Compliance", pluck="customer"))
		counts["no_kyc"] = len(borrower_names - kyc_customers)

	return {"queue": enriched, "counts": counts, "branch": branch}


@frappe.whitelist()
def get_kyc_detail(kyc_name: str):
	"""Full KYC record + the linked borrower detail (so the officer can
	verify name + ID match before approving)."""
	_require_officer()
	if not frappe.db.exists("LMS Borrower Compliance", kyc_name):
		frappe.throw(_("KYC record {0} not found.").format(kyc_name))

	_assert_branch_scope(frappe.db.get_value("Customer", frappe.db.get_value(
		"LMS Borrower Compliance", kyc_name, "customer"
	), "custom_lms_branch"))

	rec = frappe.get_doc("LMS Borrower Compliance", kyc_name)
	customer = rec.customer

	# Borrower summary so the officer doesn't have to cross-reference.
	borrower = {}
	if customer and frappe.db.exists("Customer", customer):
		cust = frappe.get_doc("Customer", customer)
		borrower = {
			"name": cust.name,
			"customer_name": cust.customer_name,
			"email_id": cust.email_id or "",
			"mobile_no": cust.mobile_no or "",
			"custom_national_id_number": cust.get("custom_national_id_number", ""),
			"custom_lms_branch": cust.get("custom_lms_branch", ""),
		}

	return {
		"kyc": {
			"name": rec.name,
			"customer": rec.customer,
			"kyc_status": rec.kyc_status,
			"consent_given": int(rec.consent_given or 0),
			"consent_date": str(rec.consent_date or ""),
			"national_id_number": rec.national_id_number,
			"id_document_proof": rec.id_document_proof or "",
			"proof_of_address": rec.proof_of_address or "",
			"aml_status": rec.aml_status or "Pending",
			"aml_screened_at": str(rec.aml_screened_at or ""),
			"aml_provider_ref": rec.aml_provider_ref or "",
			"aml_risk_level": rec.aml_risk_level or "",
			"modified": str(rec.modified),
		},
		"borrower": borrower,
	}


@frappe.whitelist()
def start_kyc(customer: str, kyc_status: str = "Pending", national_id: str = ""):
	"""Create a fresh LMS Borrower Compliance record for a borrower that
	doesn't have one yet. Officers hit this after Add Borrower leaves the
	record as 'Pending — collect later' (no documents at the counter)."""
	_require_officer()
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found.").format(customer))
	_assert_branch_scope(frappe.db.get_value("Customer", customer, "custom_lms_branch"))

	# If a record already exists, return it instead of creating a duplicate
	# (the LMS Borrower Compliance has a unique-per-customer contract).
	existing = frappe.db.get_value("LMS Borrower Compliance", {"customer": customer}, "name")
	if existing:
		return {"kyc": existing, "created": False}

	if kyc_status not in _KYC_STATUSES:
		kyc_status = "Pending"

	# The LMS Borrower Compliance DocType marks national_id_number, ID
	# document, and proof-of-address as reqd=1. The officer can start a
	# record without all of these (the whole point of start_kyc is "we
	# don't have docs yet — open the case"). Bypass the mandatory
	# validation just for this insert; subsequent updates still enforce
	# the rule (update_kyc refuses to flip to Approved without all three).
	kyc = frappe.get_doc({
		"doctype": "LMS Borrower Compliance",
		"customer": customer,
		"kyc_status": kyc_status,
		"national_id_number": national_id or "",
	})
	kyc.flags.ignore_permissions = True
	kyc.flags.ignore_mandatory = True
	kyc.insert()
	return {"kyc": kyc.name, "created": True}


@frappe.whitelist()
def update_kyc(
	kyc_name: str,
	kyc_status: str = "",
	consent_given: int | bool | None = None,
	national_id: str | None = None,
	id_document_proof: str | None = None,
	proof_of_address: str | None = None,
	notes: str = "",
):
	"""Update an existing KYC record.

	All fields are optional — pass only what changed. The officer is the
	owner of the workflow; they can flip Pending → In Review → Approved /
	Rejected as documents arrive.

	``kyc_status`` must be one of Pending / In Review / Approved / Rejected.
	``notes`` is a free-text field that is appended to a child-table audit
	log (so the regulator export shows who changed what and why).
	"""
	_require_officer()
	if not frappe.db.exists("LMS Borrower Compliance", kyc_name):
		frappe.throw(_("KYC record {0} not found.").format(kyc_name))

	# Branch scope is checked against the borrower's branch (the KYC
	# record itself doesn't carry a branch column).
	customer = frappe.db.get_value("LMS Borrower Compliance", kyc_name, "customer")
	_assert_branch_scope(frappe.db.get_value("Customer", customer, "custom_lms_branch"))

	rec = frappe.get_doc("LMS Borrower Compliance", kyc_name)

	prev_status = rec.kyc_status
	prev_consent = int(rec.consent_given or 0)

	if kyc_status:
		if kyc_status not in _KYC_STATUSES:
			frappe.throw(_("Invalid KYC status {0}. Allowed: {1}").format(
				kyc_status, ", ".join(_KYC_STATUSES)
			))
		rec.kyc_status = kyc_status
	if consent_given is not None:
		rec.consent_given = cint(consent_given)
		if cint(consent_given) and not rec.consent_date:
			rec.consent_date = frappe.utils.now()
		elif not cint(consent_given):
			rec.consent_date = None
	if national_id is not None and rec.meta.has_field("national_id_number"):
		rec.national_id_number = national_id
	if id_document_proof is not None and rec.meta.has_field("id_document_proof"):
		rec.id_document_proof = id_document_proof
	if proof_of_address is not None and rec.meta.has_field("proof_of_address"):
		rec.proof_of_address = proof_of_address

	# Refuse to set Approved without the required documents AND consent +
	# national ID — the four-eyes gate on the manager side starts here.
	if rec.kyc_status == "Approved":
		missing = []
		if not rec.national_id_number:
			missing.append("National ID number")
		if not rec.id_document_proof:
			missing.append("ID document")
		if not rec.proof_of_address:
			missing.append("Proof of address")
		if not rec.consent_given:
			missing.append("Borrower consent")
		if missing:
			frappe.throw(_(
				"KYC cannot be Approved without: {0}"
			).format(", ".join(missing)))

	rec.flags.ignore_permissions = True
	# Allow partial saves: the officer is collecting KYC incrementally.
	# The "must have all docs + consent + NID before Approved" rule is
	# enforced above by the explicit check, not by the doctype's
	# reqd=1 (which would block the partial save mid-collection).
	rec.flags.ignore_mandatory = True
	rec.save()

	# Write a tamper-evident audit event. We don't need the full operator
	# payload here (the R13 board added that on critical money events);
	# the LMS Audit Event table is the regulator's smoking gun and we
	# want a row for every KYC transition.
	_change_audit(
		doctype="LMS Borrower Compliance",
		docname=rec.name,
		prev_status=prev_status,
		new_status=rec.kyc_status,
		prev_consent=prev_consent,
		new_consent=int(rec.consent_given or 0),
		notes=notes,
	)

	return {
		"status": "ok",
		"kyc": rec.name,
		"kyc_status": rec.kyc_status,
	}


def _change_audit(
	doctype: str,
	docname: str,
	prev_status: str,
	new_status: str,
	prev_consent: int,
	new_consent: int,
	notes: str,
) -> None:
	"""Append a row to the LMS Audit Event log for a KYC transition.

	Audit events are best-effort: a write failure here MUST NOT block the
	actual update (the officer would be stuck). We log and swallow.
	"""
	try:
		from lms_saas.api.compliance import write_audit_event
		details = (
			f"KYC status: {prev_status} → {new_status}; "
			f"consent: {prev_consent} → {new_consent}"
		)
		if notes:
			details += f"; note: {notes}"
		write_audit_event(
			event_type="kyc_status_change",
			reference_doctype=doctype,
			reference_name=docname,
			amount=0,
			details=details,
			critical=False,
		)
	except Exception:
		frappe.log_error(
			title="LMS Audit Event write failed for KYC change",
			message=frappe.get_traceback(),
		)


@frappe.whitelist()
def upload_kyc_document_for_borrower(
	customer: str,
	fieldname: str,
	file_url: str,
):
	"""Attach a KYC document to a borrower's compliance record.

	Mirror of ``lms_saas.api.portal.upload_kyc_document`` but for the
	Loan Officer: the officer is on the counter with the borrower, the
	borrower hands over the ID card / utility bill, and the officer
	scans + attaches it. Branch-scoped — the officer can only attach to
	their own branch's borrowers.

	``fieldname`` must be one of ``id_document_proof`` /
	``proof_of_address`` (the two Attach fields on the compliance doc).
	"""
	_require_officer()
	allowed = {"id_document_proof", "proof_of_address"}
	if fieldname not in allowed:
		frappe.throw(_("Invalid document field {0}.").format(fieldname))
	if not file_url or not isinstance(file_url, str):
		frappe.throw(_("file_url is required."))
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found.").format(customer))
	_assert_branch_scope(frappe.db.get_value("Customer", customer, "custom_lms_branch"))

	# Find or create the compliance record.
	compliance_name = frappe.db.get_value("LMS Borrower Compliance", {"customer": customer}, "name")
	if not compliance_name:
		# Auto-create a Pending record so the officer can attach without
		# leaving the borrower detail modal.
		kyc = frappe.get_doc({
			"doctype": "LMS Borrower Compliance",
			"customer": customer,
			"kyc_status": "Pending",
		})
		kyc.flags.ignore_permissions = True
		kyc.insert()
		compliance_name = kyc.name

	frappe.db.set_value("LMS Borrower Compliance", compliance_name, fieldname, file_url)
	return {
		"compliance": compliance_name,
		"field": fieldname,
		"file_url": file_url,
	}


@frappe.whitelist()
def get_kyc_audit_trail(kyc_name: str, limit: int = 50):
	"""Return the LMS Audit Event rows linked to a KYC record.

	Used by the officer's KYC review modal so the reviewer can see who
	previously changed the status and why. The regulator export reuses
	the same table for the audit-trail section of the evidence pack.
	"""
	_require_officer()
	if not frappe.db.exists("LMS Borrower Compliance", kyc_name):
		frappe.throw(_("KYC record {0} not found.").format(kyc_name))

	customer = frappe.db.get_value("LMS Borrower Compliance", kyc_name, "customer")
	_assert_branch_scope(frappe.db.get_value("Customer", customer, "custom_lms_branch"))

	# The audit table is global; we filter by reference_doctype+name and
	# event_type so we only return KYC transitions for this record.
	rows = frappe.get_all(
		"LMS Audit Event",
		filters={
			"reference_doctype": "LMS Borrower Compliance",
			"reference_name": kyc_name,
		},
		fields=[
			"name", "event_type", "owner", "details",
			"custom_operator_legal_name", "custom_operator_mode",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=limit,
	)
	# Map `owner` → `user` for the JS so the API contract is consistent
	# with what the rest of the LMS uses.
	for r in rows:
		r["user"] = r.get("owner", "")
	return {"trail": rows}


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
	# Application-form borrower fields
	marital_status: str = "",
	spouse_name: str = "",
	spouse_dob: str = "",
	spouse_contact: str = "",
	physical_address: str = "",
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
			"lms_marital_status": marital_status or "",
			"lms_spouse_name": spouse_name or "",
			"lms_spouse_dob": spouse_dob or "",
			"lms_spouse_contact": spouse_contact or "",
			"lms_physical_address": physical_address or "",
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

	_assert_branch_scope(frappe.db.get_value("Customer", customer_name, "custom_lms_branch"))

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
		# Household / spouse / physical address (LMS custom fields) — surfaced
		# here so the Loan Application form can pre-fill these fields from
		# the selected borrower record in one round-trip.
		"marital_status": cust.get("lms_marital_status") or "",
		"spouse_name": cust.get("lms_spouse_name") or "",
		"spouse_dob": cust.get("lms_spouse_dob") or "",
		"spouse_contact": cust.get("lms_spouse_contact") or "",
		"physical_address": cust.get("lms_physical_address") or "",
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

	_assert_branch_scope(frappe.db.get_value("Customer", customer_name, "custom_lms_branch"))

	cust = frappe.get_doc("Customer", customer_name)
	if customer_name_new is not None:
		cust.customer_name = customer_name_new
	if email_id is not None:
		cust.email_id = email_id
	if mobile_no is not None:
		cust.mobile_no = mobile_no
	if national_id is not None:
		cust.custom_national_id_number = national_id
	# Enforce Frappe role permissions (PORTAL_STAFF_ROLE write on Customer),
	# so the Loan Officer write permission is real, not bypassed.
	cust.save()

	# ERPNext's Customer.create_primary_contact only mirrors email/mobile
	# back to Customer.email_id when there is NO existing primary contact.
	# For repeat edits the contact exists and gets the new values, but
	# Customer.email_id stays stale (the test and the portal header read
	# this column). Force the sync both ways:
	#   1) Update the linked primary Contact's `email_id`/`mobile_no` and
	#      the child email/phone rows.
	#   2) Re-write the Customer's own email_id/mobile_no columns so the
	#      Customer doc, the Contact doc, and the child tables agree.
	if cust.customer_primary_contact and (email_id is not None or mobile_no is not None):
		contact = frappe.get_doc("Contact", cust.customer_primary_contact)
		if email_id is not None:
			contact.email_id = email_id
		if mobile_no is not None:
			contact.mobile_no = mobile_no
		if hasattr(contact, "email_ids") and contact.email_ids:
			if email_id is not None:
				contact.email_ids[0].email_id = email_id
		if hasattr(contact, "phone_nos") and contact.phone_nos:
			if mobile_no is not None:
				contact.phone_nos[0].phone = mobile_no
		contact.flags.ignore_permissions = True
		contact.save(ignore_permissions=True)
		# Mirror to the Customer's own columns (create_primary_contact only
		# does this on the first creation, not on repeat edits).
		if email_id is not None or mobile_no is not None:
			mirror = {}
			if email_id is not None:
				mirror["email_id"] = email_id
			if mobile_no is not None:
				mirror["mobile_no"] = mobile_no
			frappe.db.set_value("Customer", customer_name, mirror, update_modified=False)

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

	_assert_branch_scope(frappe.db.get_value("Loan", loan_name, "custom_lms_branch"))

	loan = frappe.get_doc("Loan", loan_name)

	# Schedule — resolve the Loan Repayment Schedule doc(s) for this loan, then
	# aggregate their child Repayment Schedule rows (the rows are children of
	# the LN-RS doc, NOT of the Loan directly).
	schedule = []
	for lnrs in frappe.get_all(
		"Loan Repayment Schedule", filters={"loan": loan_name}, pluck="name"
	):
		for row in frappe.get_all(
			"Repayment Schedule",
			filters={"parent": lnrs, "parenttype": "Loan Repayment Schedule"},
			fields=[
				"payment_date", "principal_amount", "interest_amount",
				"total_payment", "balance_loan_amount",
			],
			order_by="payment_date asc",
			limit_page_length=0,
		):
			schedule.append(row)

	# Repayments (needed before the paid/demand cross-check below)
	repayments = frappe.get_all(
		"Loan Repayment",
		filters={"against_loan": loan_name, "docstatus": 1},
		fields=["name", "amount_paid", "posting_date"],
		order_by="posting_date desc",
		limit_page_length=50,
	)

	# Cross-check against posted Loan Repayments to mark each installment
	# paid / demand_generated. This is cheap and avoids the missing `paid`
	# column on the Repayment Schedule child table.
	if schedule:
		paid_amount_by_date: dict = {}
		for r in repayments:
			posting = r.get("posting_date")
			amt = flt(r.get("amount_paid") or 0)
			if posting:
				paid_amount_by_date[posting] = paid_amount_by_date.get(posting, 0) + amt
		for row in schedule:
			posting = row.get("payment_date")
			row["paid"] = flt(paid_amount_by_date.get(posting, 0)) >= flt(row.get("total_payment") or 0)
			row["demand_generated"] = bool(posting) and getdate(posting) < getdate(today()) and not row["paid"]

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

	R12 board: explicit audit event with ``admin_override`` flag (matches the
	manager path) so the regulator can distinguish officer-recorded from
	admin-recorded. Also rejects Closed / Written Off / Cancelled loans.
	"""
	_require_officer()
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Repayment amount must be positive."))

	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	_assert_branch_scope(frappe.db.get_value("Loan", loan_name, "custom_lms_branch"))

	loan = frappe.get_doc("Loan", loan_name)
	# Edge: closed / written-off / cancelled loans cannot accept new repayments.
	if loan.status in ("Closed", "Written Off", "Cancelled"):
		frappe.throw(
			_("Cannot record repayment on a {0} loan.").format(loan.status),
			frappe.ValidationError,
		)

	# R12 board: capture admin_override flag for the audit trail.
	admin_override = _is_admin()

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

	# R12 board: explicit audit event with admin_override distinction.
	try:
		from lms_saas.api.compliance import write_audit_event

		write_audit_event(
			event_type="Repayment:OfficerRecorded",
			reference_doctype="Loan Repayment",
			reference_name=repayment.name,
			amount=amount,
			company=loan.company,
			details=(
				f"loan={loan_name}; admin_override={admin_override}; "
				f"loan_status={loan.status}; branch={loan.get('custom_lms_branch') or 'unassigned'}"
			),
			critical=True,
		)
	except Exception:
		frappe.log_error(title="officer.record_repayment audit failed", message=frappe.get_traceback())

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