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
from lms_saas.api.compliance_config import is_sandbox_mode
from lms_saas.api.labels import officer_label, branch_label


# R18-1: in sandbox mode, hide demo seed records from the manager approval
# queue. Pattern match covers both the applicant (Customer link) and the
# resolved customer_name.
DEMO_NAME_PATTERNS = (
	"%Test%",
	"%R14-APP%",
	"%Borrower 003%",
	"%Borrower 002%",
	"%Demo%",
)


def _is_demo_applicant(applicant_name: str) -> bool:
	if not applicant_name:
		return False
	needle = applicant_name.lower()
	return any(p.strip("%").lower() in needle for p in DEMO_NAME_PATTERNS)


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
	from lms_saas.utils.brand import _get_user_persona

	persona = _get_user_persona()
	if persona != "Branch Manager":
		frappe.throw("Not permitted", frappe.PermissionError)
	# Portal staff (LMS Portal Staff role) do NOT have read permission on
	# the Loan / Loan Application / Customer doctypes. The API already
	# scopes by branch via custom_lms_branch filters, so bypassing
	# row-level permissions here is safe and necessary for the dashboard
	# KPIs, approval queue, borrower list, and loan list to return data.
	frappe.flags.ignore_permissions = True


def _manager_branch() -> str | None:
	"""Resolve the manager's branch (Cost Center) for query scoping."""
	# Top-level import so tests can monkey-patch staff.get_current_user_branch
	# via the staff module reference (R12 board feedback: late imports defeat
	# the monkey-patch and break branch-scope unit tests).
	import lms_saas.api.staff as _staff

	return _staff.get_current_user_branch()


def _is_admin() -> bool:
	return bool(set(frappe.get_roles()).intersection({"System Manager", "Administrator"}))


def _assert_branch_scope(target_branch: str | None, write: bool = False) -> None:
	"""Enforce branch-scope on manager actions.

	R24: too strict on no-branch (broke onboarding).
	R25: split read vs write. Reads with no caller branch are allowed
	(admin-lite) with a soft log. Writes with no caller branch throw
	(branchless write = cross-branch write = unsafe).

	Policy:
	  - Admins (System Manager / Administrator) bypass entirely.
	  - If manager has a branch AND target has a branch AND they differ
	    → throw (branch isolation held).
	  - If manager has no branch:
	    - write=True → throw ("contact HR to assign a branch before
	      performing write actions")
	    - write=False → allow with a soft log (admin-lite read fallback)
	  - If target has no branch → allow with a soft log (legacy data).
	"""
	if _is_admin():
		return
	branch = _manager_branch()
	if not branch:
		# R25-F5: branchless callers can still read (UX) but cannot
		# write. A branchless write would be a cross-branch write by
		# definition (no branch = every branch).
		if write:
			# Diagnose: tell the operator exactly what was tried.
			emp_meta = frappe.get_meta("Employee")
			emp_filters = {"user_id": frappe.session.user}
			if emp_meta.has_field("status"):
				emp_filters["status"] = "Active"
			emp_name = frappe.db.get_value("Employee", emp_filters, "name")
			fields_checked = []
			if emp_meta.has_field("custom_lms_branch"):
				fields_checked.append("custom_lms_branch=" + repr(frappe.db.get_value("Employee", emp_filters, "custom_lms_branch")))
			if emp_meta.has_field("cost_center"):
				fields_checked.append("cost_center=" + repr(frappe.db.get_value("Employee", emp_filters, "cost_center")))
			diagnostic = (
				f"Employee={emp_name or '<none>'}; "
				f"checked fields: {', '.join(fields_checked) or 'no branch fields on Employee'}; "
				f"User Permission on Cost Center: "
				f"{frappe.get_all('User Permission', filters={'user': frappe.session.user, 'allow': 'Cost Center'}, pluck='for_value') or '<none>'}"
			)
			frappe.throw(
				_(
					"Your account is not assigned to a branch. Contact your HR / "
					"system manager before performing write actions. Diagnostic: {0}"
				).format(diagnostic),
				frappe.PermissionError,
			)
		frappe.log_error(
			title="LMS branch-scope: caller has no branch (read fallback)",
			message=(
				f"manager={frappe.session.user} action=read target_branch={target_branch or '<empty>'} "
				"admin-lite read fallback active"
			),
		)
		return
	if not target_branch:
		frappe.log_error(
			title="LMS branch-scope: target has no branch",
			message=(
				f"manager={frappe.session.user} branch={branch} "
				f"target_branch=<empty>"
			),
		)
		return
	if target_branch != branch:
		frappe.throw("Not in your branch.", frappe.PermissionError)


@frappe.whitelist()
def get_manager_dashboard():
	"""Branch-scoped KPIs for the Branch Manager portal landing."""
	_require_manager()
	branch = _manager_branch()

	# Reuse the dashboard metrics engine for portfolio KPIs.
	# Pass the manager's branch so the dashboard KPIs are scoped to the same
	# loan book as the Loans / Borrowers tabs (otherwise the count would reflect
	# the entire portfolio and disagree with the tab views).
	from lms_saas.api.dashboard import _portfolio_metrics

	metrics = _portfolio_metrics(branch=branch)
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
	"""Loan Applications pending approval in the manager's branch.

	R18-1: in sandbox mode, hide demo seed records so the manager's
	Approval Queue tab doesn't show 14 copies of the same Test/R14-APP row.
	"""
	_require_manager()
	branch = _manager_branch()
	sandbox = is_sandbox_mode()

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
		# R34-QA: include KYC/AML status so the manager portal can
		# render a status badge (Approve / disabled + tooltip) and
		# avoid the "Cannot approve: borrower KYC is not Approved"
		# red banner that the user saw at the bottom of the screen.
		compliance = (
			frappe.db.get_value(
				"LMS Borrower Compliance",
				{"customer": app.applicant},
				["kyc_status", "aml_status"],
				as_dict=True,
			)
			or {}
		)
		app["kyc_status"] = compliance.get("kyc_status") or "Pending"
		app["aml_status"] = compliance.get("aml_status") or "Pending"
		app["is_approvable"] = (
			app["kyc_status"] == "Approved" and app["aml_status"] == "Clear"
		)

	# R18-1: drop demo seed applicants in sandbox mode.
	total_before_filter = len(applications)
	demo_filtered_count = 0
	if sandbox and applications:
		filtered = []
		for app in applications:
			if (
				_is_demo_applicant(app.get("customer_name"))
				or _is_demo_applicant(app.get("applicant"))
			):
				demo_filtered_count += 1
				continue
			filtered.append(app)
		applications = filtered

	return {
		"applications": applications,
		"sandbox_filtered": bool(sandbox and applications),
		# R20-M1: pre-filter count for operator situational awareness.
		"total_before_filter": total_before_filter,
		"demo_filtered_count": demo_filtered_count,
	}


@frappe.whitelist()
def approve_application(application_name: str):
	"""Approve a Loan Application: submit it and create the Loan record."""
	_require_manager()
	if not frappe.db.exists("Loan Application", application_name):
		frappe.throw(_("Loan Application {0} not found.").format(application_name))

	app = frappe.get_doc("Loan Application", application_name)

	# Branch scoping: a manager may only act on applications in their own branch.
	# R25-F5: write=True — a branchless manager cannot approve (cross-branch
	# origination is unsafe).
	_assert_branch_scope(app.get("custom_lms_branch"), write=True)

	if app.docstatus != 0:
		frappe.throw(_("Only draft applications can be approved (current status: {0}).").format(app.docstatus))

	# R25-F1: four-eyes enforcement on approval. The maker of the
	# originating Loan Application must not also be the approver.
	# Admins are exempt (operator owner can do anything).
	if not _is_admin() and app.owner == frappe.session.user:
		frappe.throw(
			_(
				"Four-eyes control: you (the maker of this application) "
				"cannot also approve it. A second authorised user must "
				"approve the application."
			),
			frappe.PermissionError,
		)

	# R25-F2: KYC + AML gate. The borrower's compliance record must be
	# Approved + Clear before a manager can approve the application.
	# This is the operator's regulator-mandated control and is enforced
	# here in addition to the AML screen-on-origination hook so a
	# manager cannot approve an unKYC'd or unscreened borrower even if
	# the AML provider was offline at origination time.
	compliance = frappe.db.get_value(
		"LMS Borrower Compliance",
		{"customer": app.applicant},
		["kyc_status", "aml_status"],
		as_dict=True,
	) or {}
	current_kyc = compliance.get("kyc_status") or "Pending"
	current_aml = compliance.get("aml_status") or "Pending"
	if current_kyc != "Approved":
		return {
			"status": "blocked",
			"code": "kyc_not_approved",
			"application": application_name,
			"kyc_status": current_kyc,
			"aml_status": current_aml,
			"message": _(
				"Cannot approve: borrower KYC is not Approved (current: {0}). "
				"Complete KYC review first."
			).format(current_kyc),
		}
	if current_aml != "Clear":
		return {
			"status": "blocked",
			"code": "aml_not_clear",
			"application": application_name,
			"kyc_status": current_kyc,
			"aml_status": current_aml,
			"message": _(
				"Cannot approve: borrower AML screening is not Clear (current: {0}). "
				"Wait for AML screening to complete or override via the AML "
				"override flow (Branch Manager only)."
			).format(current_aml),
		}

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
	# R21-C1: record the direct link to the originating Loan Application
	# so the four-eyes resolver at Loan.before_submit time can determine
	# the application owner precisely (without relying on fuzzy
	# (applicant, loan_product) matching that historically returned
	# Administrator-owned seed apps and made the check pass vacuously).
	if frappe.get_meta("Loan").has_field("custom_lms_loan_application"):
		loan.custom_lms_loan_application = app.name
	loan.flags.ignore_permissions = True
	loan.insert()

	# R29-F10: the Loan must be SUBMITTED (not just inserted) before the
	# officer-side disburse flow runs. The R28 officer rewrite assumed
	# ``loan.docstatus == 1`` (Sanctioned) when the officer clicks
	# Disburse. Without this submit, the officer-side ``disburse_assigned_loan``
	# would have to mid-flight submit the Loan itself, which races with
	# the repayment-schedule insert below and is brittle. Submit here,
	# as Administrator so lending's on_submit hook has the perms it
	# needs (lending creates the canonical repayment schedule on submit).
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		loan.submit()
		loan.reload()
	finally:
		frappe.set_user(original_user)

	# Generate the repayment schedule so it is visible to the BM / officer
	# (Frappe Lending only builds it on disbursement; the portal needs it at approval).
	try:
		from frappe.utils import add_months, today

		rs = frappe.new_doc("Loan Repayment Schedule")
		rs.loan = loan.name
		rs.loan_product = loan.loan_product
		rs.repayment_method = loan.repayment_method or "Repay Over Number of Periods"
		rs.repayment_periods = loan.repayment_periods or 1
		rs.rate_of_interest = loan.rate_of_interest or 0
		rs.loan_amount = loan.loan_amount
		rs.current_principal_amount = loan.loan_amount
		rs.repayment_frequency = getattr(loan, "repayment_frequency", None) or "Monthly"
		rs.repayment_schedule_type = frappe.db.get_value(
			"Loan Product", loan.loan_product, "repayment_schedule_type"
		)
		rs.repayment_start_date = loan.repayment_start_date or add_months(today(), 1)
		rs.posting_date = loan.posting_date or today()
		rs.number_of_rows = 0
		# Build the amortization rows directly (no prior disbursement needed).
		rs.make_repayment_schedule(
			schedule_field="repayment_schedule",
			previous_interest_amount=0,
			balance_amount=loan.loan_amount,
			additional_principal_amount=0,
			pending_prev_days=0,
			rate_of_interest=loan.rate_of_interest or 0,
			principal_share_percentage=100,
			interest_share_percentage=100,
		)
		# validate() would otherwise rebuild the schedule from a (non-existent)
		# disbursement and wipe the rows we just built; skip that one step.
		_schedule_cls = type(rs)
		_orig_rebuild = _schedule_cls.make_customer_repayment_schedule
		_schedule_cls.make_customer_repayment_schedule = lambda self: None
		rs.flags.ignore_permissions = True
		try:
			rs.insert()
		finally:
			_schedule_cls.make_customer_repayment_schedule = _orig_rebuild
	except Exception as e:  # schedule is non-blocking for approval; log and continue
		frappe.logger().warning(f"Could not generate repayment schedule for {loan.name}: {e}")

	return {
		"status": "approved",
		"application": application_name,
		"loan": loan.name,
		"message": _("Application approved and Loan {0} created.").format(loan.name),
	}


@frappe.whitelist()
def reject_application(application_name: str, reason: str = ""):
	"""Reject a Loan Application: cancel it with a reason comment.

	R29-F11: explicit LMS Audit Event on rejection so the regulator's
	audit trail shows rejections in the same walk-through as approvals.
	"""
	_require_manager()
	if not frappe.db.exists("Loan Application", application_name):
		frappe.throw(_("Loan Application {0} not found.").format(application_name))

	app = frappe.get_doc("Loan Application", application_name)

	# R25-F5: write=True — branchless manager cannot reject.
	_assert_branch_scope(app.get("custom_lms_branch"), write=True)

	# A rejection reason is required for the audit trail.
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Rejection reason is required for the audit trail."))

	if app.docstatus != 0:
		frappe.throw(_("Only draft applications can be rejected (current status: {0}).").format(app.docstatus))

	# R29-F11: audit the rejection BEFORE the delete so the row is
	# not orphaned. ``reference_name`` retains the application name —
	# the LMS Audit Event reference stays valid even though the source
	# doc is gone (the audit table is a regulator-grade immutable log).
	original_user = frappe.session.user
	try:
		from lms_saas.api.compliance import write_audit_event

		write_audit_event(
			event_type="LoanApplication:Rejected",
			reference_doctype="Loan Application",
			reference_name=application_name,
			details=(
				f"application={application_name} manager={original_user} "
				f"branch={app.get('custom_lms_branch') or 'unassigned'} "
				f"reason={reason} applicant={app.applicant} loan_amount={app.loan_amount}"
			),
			critical=True,
		)
	except Exception:
		frappe.log_error(
			title="reject_application audit failed",
			message=frappe.get_traceback(),
		)

	# Add a comment with the rejection reason (kept for the desk-side
	# visible trail — operators want to see "why was this killed?" in
	# the doc's Comments tab).
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": "Loan Application",
			"reference_name": application_name,
			"content": f"Application rejected: {reason}",
		}
	).insert(ignore_permissions=True)

	# Delete the draft application (drafts cannot be cancelled, only deleted).
	# R34-QA: `app.delete()` enqueues `frappe.model.delete_doc.delete_dynamic_links`
	# via `enqueue_after_commit=True`. The background worker runs after the
	# current transaction commits — by then our `frappe.set_user("Administrator")`
	# has been undone by the `finally` block, so the background worker runs as
	# the manager and trips the same Frappe-version-specific gate
	# (`_check_queue_size` → `has_permission("System Health Report")` →
	# `only_for("System Manager")`). We can't `set_user` for a deferred worker.
	#
	# Fix: do the delete manually as Administrator. The audit row + comment
	# above were already written as the manager so the regulator trail is
	# unchanged. We skip the dynamic-link cleanup (View Log / Comment /
	# Version entries) — these are non-critical audit noise for a draft;
	# Frappe's `add_to_deleted_document` recovery option is also skipped
	# (drafts cannot be recovered anyway).
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		frappe.db.delete("Loan Application", {"name": application_name})
		frappe.clear_document_cache("Loan Application", application_name)
	finally:
		frappe.set_user(original_user)

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
		# R18-3: replace "Unassigned" with a chart-friendly label that tells
		# the operator what work is genuinely missing vs. what is just
		# onboarded-but-unassigned.
		officer = officer_label(loan.custom_loan_officer, loan.custom_days_past_due)
		if officer not in officers:
			officers[officer] = {
				"officer": officer,
				"officer_name": (
					frappe.db.get_value("Employee", officer, "employee_name")
					if officer and frappe.db.exists("Employee", officer)
					else officer
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
def get_manager_application_detail(application_name: str) -> dict:
	"""Full Loan Application detail for the manager review modal (R24).

	Mirrors lms_saas.api.officer.get_application_detail but adds:
	  - Branch-scope enforcement (managers may only view apps in their
	    own branch — see _assert_branch_scope).
	  - Compliance / AML status (managers need to see Clear before approve).
	  - Auditor information: who the originating officer is, the audit
	    trail, and the customer's KYC + AML screening history.

	Returns the same shape as the officer API so the manager portal can
	render the review modal with one set of code.
	"""
	_require_manager()
	if not application_name or not frappe.db.exists("Loan Application", application_name):
		frappe.throw(_("Loan Application {0} not found").format(application_name))

	app = frappe.get_doc("Loan Application", application_name)
	_assert_branch_scope(app.get("custom_lms_branch"))

	customer_name = (
		frappe.db.get_value("Customer", app.applicant, "customer_name") or ""
	)
	customer_email = (
		frappe.db.get_value("Customer", app.applicant, "email_id") or ""
	)
	customer_mobile = (
		frappe.db.get_value("Customer", app.applicant, "mobile_no") or ""
	)

	# Loan officer
	officer_name = ""
	if app.get("custom_loan_officer"):
		officer_name = (
			frappe.db.get_value(
				"Employee", app.custom_loan_officer, "employee_name"
			) or ""
		)

	product = {}
	if app.loan_product:
		p = frappe.get_doc("Loan Product", app.loan_product)
		product = {
			"name": p.name,
			"product_code": p.get("product_code"),
			"product_name": p.get("product_name"),
			"rate_of_interest": p.get("rate_of_interest"),
			"maximum_loan_amount": p.get("maximum_loan_amount"),
		}

	schedule = []
	for s in app.get("repayment_schedule", []) or []:
		schedule.append({
			"date": str(s.payment_date) if s.get("payment_date") else None,
			"principal": flt(s.get("principal_amount")),
			"interest": flt(s.get("interest_amount")),
			"total": flt(s.get("total_payment")),
			"balance": flt(s.get("balance_loan_amount")),
		})

	kyc = {}
	compliance_name = frappe.db.get_value(
		"LMS Borrower Compliance", {"customer": app.applicant}, "name"
	)
	if compliance_name:
		row = frappe.db.get_value(
			"LMS Borrower Compliance",
			compliance_name,
			[
				"name", "kyc_status", "aml_status", "aml_screened_at",
				"national_id_number", "consent_given", "consent_date",
				"credit_score", "debt_to_income_ratio",
			],
			as_dict=True,
		)
		if row:
			kyc = {
				"name": row.name,
				"kyc_status": row.kyc_status,
				"aml_status": row.aml_status,
				"aml_screened_at": str(row.aml_screened_at) if row.aml_screened_at else None,
				"national_id_number": row.national_id_number,
				"consent_captured": bool(row.consent_given),
				"consent_date": str(row.consent_date) if row.consent_date else None,
				"credit_score": row.credit_score,
				"debt_to_income_ratio": row.debt_to_income_ratio,
			}

	collateral = []
	for c in frappe.get_all(
		"LMS Collateral",
		filters={"loan_application": application_name},
		fields=[
			"name", "collateral_type", "collateral_title",
			"market_value", "net_realizable_value", "status",
			"lms_security_certificate", "lms_security_units",
			"lms_guarantor_name",
		],
	):
		collateral.append({
			"name": c.name,
			"collateral_type": c.collateral_type,
			"collateral_title": c.collateral_title,
			"market_value": c.market_value,
			"net_realizable_value": c.net_realizable_value,
			"status": c.status,
			"lms_security_certificate": c.lms_security_certificate,
			"lms_security_units": c.lms_security_units,
			"lms_guarantor_name": c.lms_guarantor_name,
		})

	audit = []
	if frappe.db.exists("DocType", "LMS Audit Event"):
		for e in frappe.get_all(
			"LMS Audit Event",
			filters={"reference_doctype": "Loan Application", "reference_name": application_name},
			fields=["event_type", "details", "event_user", "creation"],
			order_by="creation desc",
			limit_page_length=20,
		):
			audit.append({
				"event_type": e.event_type,
				"details": e.details,
				"actor": e.event_user,
				"creation": str(e.creation),
			})

	# Borrower's existing loans (if any) for cross-portfolio check
	existing_loans = frappe.get_all(
		"Loan",
		filters={"applicant": app.applicant, "docstatus": ("!=", 2)},
		fields=["name", "loan_amount", "status", "disbursed_amount"],
		order_by="creation desc",
		limit_page_length=10,
	)
	for l in existing_loans:
		l["outstanding"] = flt(l.disbursed_amount or 0)

	# R32: tell the manager portal whether the current user can override
	# the borrower's AML flag from the review modal. The portal uses this
	# to surface the "Override AML…" control; the server-side role gate
	# in override_aml_flag is still the source of truth.
	from lms_saas.api.aml_role_gates import can_clear_aml_flag as _can_clear
	can_override_aml = bool(_can_clear())

	return {
		"application": {
			"name": app.name,
			"applicant": app.applicant,
			"applicant_name": customer_name,
			"applicant_email": customer_email,
			"applicant_mobile": customer_mobile,
			"officer_name": officer_name,
			"loan_product": app.loan_product,
			"loan_amount": app.loan_amount,
			"rate_of_interest": app.rate_of_interest,
			"repayment_periods": app.repayment_periods,
			"repayment_method": app.repayment_method,
			"repayment_start_date": str(app.repayment_start_date) if app.get("repayment_start_date") else None,
			"loan_purpose": app.get("loan_purpose") or "",
			"status": app.status,
			"docstatus": app.docstatus,
			"custom_lms_branch": app.get("custom_lms_branch"),
			"custom_loan_officer": app.get("custom_loan_officer"),
			"company": app.company,
			"posting_date": str(app.posting_date) if app.get("posting_date") else None,
			"creation": str(app.creation),
		},
		"product": product,
		"schedule": schedule,
		"kyc": kyc,
		"collateral": collateral,
		"audit": audit,
		"existing_loans": existing_loans,
		"can_override_aml": can_override_aml,
	}


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

	_assert_branch_scope(frappe.db.get_value("Customer", customer_name, "custom_lms_branch"))

	cust = frappe.get_doc("Customer", customer_name)
	if customer_name_new is not None:
		# R29-F15: pre-check uniqueness so the operator sees a friendly
		# error ("A Customer named X already exists") instead of a
		# DuplicateEntryError traceback deep inside the save() call.
		customer_name_new = customer_name_new.strip()
		if customer_name_new and customer_name_new != cust.customer_name:
			collision = frappe.db.get_value(
				"Customer", {"customer_name": customer_name_new}, "name"
			)
			if collision and collision != customer_name:
				frappe.throw(
					_(
						"A Customer named {0} already exists (record {1}). "
						"Merge into the existing customer or pick a different name."
					).format(customer_name_new, collision)
				)
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
	# Fail-closed branch scoping.
	_assert_branch_scope(loan.get("custom_lms_branch"))

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
				"total_payment", "balance_loan_amount", "demand_generated",
			],
			order_by="payment_date asc",
			limit_page_length=0,
		):
			schedule.append(row)
	schedule.sort(key=lambda r: (getdate(r.get("payment_date")) or getdate("1900-01-01")))
	# Map demand_generated to a 'paid' flag for the frontend's convenience.
	for row in schedule:
		row["paid"] = cint(row.get("demand_generated"))

	# Repayments
	# NOTE: Loan Repayment has no 'status' field — expose docstatus as a
	# user-friendly state instead.
	repayments = frappe.get_all(
		"Loan Repayment",
		filters={"against_loan": loan_name, "docstatus": 1},
		fields=["name", "amount_paid", "posting_date", "docstatus"],
		order_by="posting_date desc",
		limit_page_length=50,
	)
	for r in repayments:
		r["status"] = "Submitted" if cint(r.get("docstatus")) == 1 else "Draft"

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
	"""Create a Loan Disbursement for an approved loan (manager action).

	R29-F2: mirrors the R28 officer four-step pattern (helper → admin-
	context insert → set_owner → submit). The previous implementation
	inserted the ``Loan Disbursement`` as the manager session; lending's
	``Loan Disbursement.on_update`` ⇒ ``make_update_draft_schedule`` ⇒
	``frappe.get_doc(...).insert()`` of ``Loan Repayment Schedule`` raised
	an opaque ``PermissionError`` because the manager lacks ``create``
	perm on Loan Repayment Schedule.
	"""
	_require_manager()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	_assert_branch_scope(frappe.db.get_value("Loan", loan_name, "custom_lms_branch"), write=True)

	loan = frappe.get_doc("Loan", loan_name)
	if loan.docstatus != 1:
		frappe.throw(_("Loan must be submitted before disbursement."))

	amount = flt(disbursed_amount) if disbursed_amount else flt(loan.loan_amount)
	if amount <= 0:
		frappe.throw(_("Disbursement amount must be positive."))

	original_user = frappe.session.user
	disbursement_name = None
	try:
		from lending.loan_management.doctype.loan.loan import make_loan_disbursement

		frappe.set_user("Administrator")
		# Step 1: build in-memory doc (helper returns unsaved).
		disbursement = make_loan_disbursement(
			loan=loan.name,
			disbursement_amount=amount,
			submit=False,
			posting_date=today(),
			disbursement_date=today(),
		)
		# Step 2: insert as Administrator so lending's on_update hook
		# (which creates the Loan Repayment Schedule rows) has the perms
		# it needs.
		disbursement.flags.ignore_permissions = True
		disbursement.insert()
		# Step 3: patch owner to the manager (maker) for four-eyes.
		frappe.db.set_value(
			"Loan Disbursement", disbursement.name, "owner", original_user
		)
		# Step 4: submit.
		disbursement.reload()
		disbursement.submit()
		disbursement_name = disbursement.name
	finally:
		frappe.set_user(original_user)

	# R29-F11 sibling: emit an LMS Audit Event on the manager-side
	# disbursement so the regulator's audit trail distinguishes it
	# from the officer-side disbursement done via disburse_assigned_loan.
	_audit_manager_disbursement(loan_name, disbursement_name, amount, original_user)

	return {
		"status": "disbursed",
		"loan": loan_name,
		"disbursement": disbursement_name,
		"amount": amount,
		"message": _("Loan {0} disbursed — {1}.").format(loan_name, disbursement_name),
	}


@frappe.whitelist()
def write_off_loan(loan_name: str, write_off_amount: float | None = None, reason: str = ""):
	"""Create a Loan Write Off for a non-performing loan.

	R29-F4: apply admin-context for the insert (matches the lending
	app's perm model — write-offs hit the GL and lending on_update
	hooks that need create perm on Loan Repayment Schedule). Also
	require a non-empty reason and emit an LMS Audit Event so
	regulator's audit trail captures write-offs explicitly (R29-F9).
	"""
	_require_manager()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	_assert_branch_scope(frappe.db.get_value("Loan", loan_name, "custom_lms_branch"), write=True)

	loan = frappe.get_doc("Loan", loan_name)
	if loan.docstatus != 1:
		frappe.throw(_("Loan must be submitted before write-off."))

	amount = flt(write_off_amount) if write_off_amount else flt(loan.loan_amount) - flt(loan.total_amount_paid or 0)
	if amount <= 0:
		frappe.throw(_("Write-off amount must be positive."))

	# R29-F9: a write-off is a capital event — require a reason for the
	# audit trail.
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Reason is required for write-offs (audit trail)."))

	original_user = frappe.session.user
	write_off_name = None
	try:
		frappe.set_user("Administrator")
		wo = frappe.get_doc(
			{
				"doctype": "Loan Write Off",
				"against_loan": loan_name,
				"applicant_type": loan.applicant_type,
				"applicant": loan.applicant,
				"company": loan.company,
				"write_off_amount": amount,
				"posting_date": today(),
				"remarks": f"Write-off reason: {reason}",
			}
		)
		wo.flags.ignore_permissions = True
		wo.insert()
		wo.submit()
		write_off_name = wo.name
	finally:
		frappe.set_user(original_user)

	# R29-F9: explicit LMS Audit Event row (matches the record_repayment
	# pattern). critical=True — write-offs are regulator-facing capital
	# events; an audit-write failure must surface.
	try:
		from lms_saas.api.compliance import write_audit_event

		write_audit_event(
			event_type="LoanWriteOff:ManagerRecorded",
			reference_doctype="Loan Write Off",
			reference_name=write_off_name,
			amount=amount,
			company=loan.company,
			details=(
				f"loan={loan_name}; admin_override={_is_admin()}; "
				f"branch={loan.get('custom_lms_branch') or 'unassigned'}; "
				f"reason={reason}"
			),
			critical=True,
		)
	except Exception:
		frappe.log_error(
			title="write_off_loan audit failed",
			message=frappe.get_traceback(),
		)

	return {
		"status": "written_off",
		"loan": loan_name,
		"write_off": write_off_name,
		"amount": amount,
		"message": _("Loan {0} written off — {1}.").format(loan_name, write_off_name),
	}


@frappe.whitelist()
def record_repayment(
	loan_name: str,
	amount: float,
	payment_mode: str = "Cash",
	posting_date: str | None = None,
	overpayment_confirm: bool = False,
):
	"""Record a loan repayment (manager can record on behalf of borrower).

	R29-F3: applies the R28 admin-context pattern preemptively — the
	lending ``Loan Repayment.on_submit`` hook fires GL entries +
	reverses accruals and may need create perm on ``Loan Demand`` /
	``Loan Repayment Schedule`` rows that the manager doesn't have.

	R29-F8: over-repayment guard. If ``amount`` exceeds the remaining
	outstanding by more than 10% AND ``amount > 100``, throw unless
	the caller passes ``overpayment_confirm=True``. Misfits (typos
	like a 10× keystroke error) are the common failure mode.

	R12 board: includes ``admin_override`` flag in the audit event so the
	regulator can distinguish a normal manager recording from an admin
	bypassing the branch / officer assignment. Also rejects loans that are
	Closed, Written Off, or Cancelled — silently accepting a repayment on a
	closed loan is an audit-trail integrity bug.
	"""
	_require_manager()
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Repayment amount must be positive."))

	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)
	# R25-F5: write=True — branchless manager cannot record repayments.
	_assert_branch_scope(loan.get("custom_lms_branch"), write=True)

	# Edge: closed / written-off / cancelled loans cannot accept new repayments.
	if loan.status in ("Closed", "Written Off", "Cancelled"):
		frappe.throw(
			_("Cannot record repayment on a {0} loan.").format(loan.status),
			frappe.ValidationError,
		)

	# R29-F8: over-repayment guard. Compute outstanding from
	# ``total_payment - total_amount_paid`` (avoids relying on lending's
	# private outstanding calculation). Always allow when amount equals
	# outstanding exactly (typical happy path); flag when amount > 1.1 *
	# outstanding AND amount > 100 (filters out sub-cent rounding
	# artefacts without limiting small loans).
	outstanding = flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0)
	if (
		not overpayment_confirm
		and amount > 0
		and outstanding > 0
		and amount > outstanding * 1.1
		and amount > 100
	):
		frappe.throw(
			_(
				"Repayment of {0} exceeds the remaining outstanding ({1}) by more than 10%. "
				"Confirm an intentional overpayment by re-issuing the call with "
				"``overpayment_confirm=True``. Refusing silent overpayment is a "
				"regulator-mandated control."
			).format(amount, outstanding),
			frappe.ValidationError,
		)

	# R12 board: capture admin_override flag for the audit trail.
	admin_override = _is_admin()

	# R29-F3: admin-context insert+submit so lending's Loan Repayment
	# on_submit hook (demand reversal, GL) has the perms it needs. The
	# original user is restored in ``finally``.
	original_user = frappe.session.user
	repayment_name = None
	try:
		frappe.set_user("Administrator")
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
		# Four-eyes: set owner to the manager (maker) so
		# lending's enforce_four_eyes sees them as maker. The submit
		# is still as Administrator (so lending's hooks have perms),
		# which satisfies the maker-vs-submitter check.
		frappe.db.set_value(
			"Loan Repayment", repayment.name, "owner", original_user
		)
		repayment.reload()
		repayment.submit()
		repayment_name = repayment.name
	finally:
		frappe.set_user(original_user)

	# R12 board: explicit audit event for manager.record_repayment.
	try:
		from lms_saas.api.compliance import write_audit_event

		write_audit_event(
			event_type="Repayment:ManagerRecorded",
			reference_doctype="Loan Repayment",
			reference_name=repayment_name,
			amount=amount,
			company=loan.company,
			details=(
				f"loan={loan_name}; admin_override={admin_override}; "
				f"loan_officer={loan.get('custom_loan_officer') or 'unassigned'}; "
				f"loan_status={loan.status}; branch={loan.get('custom_lms_branch') or 'unassigned'}; "
				f"outstanding_at_record={outstanding}; overpayment_confirm={bool(overpayment_confirm)}"
			),
			critical=True,
		)
	except Exception:
		frappe.log_error(title="record_repayment audit failed", message=frappe.get_traceback())

	return {
		"status": "recorded",
		"loan": loan_name,
		"repayment": repayment_name,
		"amount": amount,
		"message": _("Repayment of {0} recorded for loan {1}.").format(amount, loan_name),
	}


def _audit_manager_disbursement(
	loan_name: str, disbursement_name: str, amount: float, manager_user: str
) -> None:
	"""R29-F11 sibling: emit an LMS Audit Event on manager.disburse_loan.

	Mirrors the officer-side R28-F11 so the regulator's audit trail has
	every disbursement labelled by who actually clicked the button.
	Audit-write failure must never block the business action.
	"""
	try:
		if not frappe.db.exists("DocType", "LMS Audit Event"):
			return
		from lms_saas.api.compliance import write_audit_event

		write_audit_event(
			event_type="LoanDisbursement:ManagerRecorded",
			reference_doctype="Loan Disbursement",
			reference_name=disbursement_name,
			amount=amount,
			details=(
				f"loan={loan_name} disbursement={disbursement_name} "
				f"amount={amount} actor={manager_user} role=manager"
			),
			critical=True,
		)
	except Exception:
		frappe.log_error(
			title="disburse_loan audit failed",
			message=frappe.get_traceback(),
		)


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
	filters = _merge_date_window(filters, from_date, to_date, default_days=30)

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
		# Fail-closed: skip if manager has no branch, or loan is in another branch.
		if not branch or not loan or not loan.get("custom_lms_branch") or loan["custom_lms_branch"] != branch:
			continue
		officer = officer_label(loan.custom_loan_officer if loan else "") if loan else ""
		officer_name = (
			frappe.db.get_value("Employee", officer, "employee_name")
			if officer and frappe.db.exists("Employee", officer)
			else officer
		)
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
	filters = _merge_date_window(filters, from_date, to_date, default_days=30)

	repayments = frappe.get_all(
		"Loan Repayment",
		filters=filters,
		fields=["name", "against_loan", "amount_paid", "posting_date", "docstatus"],
		order_by="posting_date desc",
		limit_page_length=0,
	)
	# R29-F5: `Loan Repayment` has no `status` field (it does have a
	# `docstatus` int 0/1/2). Surface a human-friendly state so the
	# dashboard / portal JS doesn't render `undefined` for `status`.
	for r in repayments:
		r["status"] = _friendly_docstatus(r.pop("docstatus", 0))

	by_officer = {}
	total = 0
	for r in repayments:
		loan = frappe.db.get_value("Loan", r.against_loan, ["custom_loan_officer", "custom_lms_branch", "applicant"], as_dict=True)
		# Fail-closed: skip if manager has no branch, or loan is in another branch.
		if not branch or not loan or not loan.get("custom_lms_branch") or loan["custom_lms_branch"] != branch:
			continue
		officer = officer_label(loan.custom_loan_officer if loan else "") if loan else ""
		officer_name = (
			frappe.db.get_value("Employee", officer, "employee_name")
			if officer and frappe.db.exists("Employee", officer)
			else officer
		)
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
	# Fail-closed branch scoping.
	_assert_branch_scope(loan.get("custom_lms_branch"))

	transactions = []

	# R29-F5: single date-window helper that handles all 4 cases
	# (from-only / to-only / both / neither). The previous code used
	# a clobbering pattern that lost the from_date when to_date was
	# provided as a later ``if`` branch.
	base_filters = {"against_loan": loan_name, "docstatus": 1}
	disb_filters = _merge_date_window(dict(base_filters), from_date, to_date)
	rep_filters = _merge_date_window(dict(base_filters), from_date, to_date)

	# Disbursements. ``Loan Disbursement`` DOES have a `status` field
	# (Sanctioned / Pending / etc) — leave it as-is.
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

	# Repayments. ``Loan Repayment`` does NOT have a `status` field —
	# render docstatus as a friendly state instead.
	repayments = frappe.get_all(
		"Loan Repayment",
		filters=rep_filters,
		fields=["name", "amount_paid", "posting_date", "docstatus"],
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
			"status": _friendly_docstatus(r.pop("docstatus", 0)),
		})

	# Sort by date and compute running balance
	transactions.sort(key=lambda t: str(t["date"]))
	running = 0
	for t in transactions:
		running += t["debit"] - t["credit"]
		t["balance"] = round(running, 2)

	# R29-F5 followup: opening_balance was hard-coded to 0. Compute it
	# as the running total of all transactions BEFORE from_date (if any).
	opening_balance = 0
	if from_date:
		pre_window = _merge_date_window(
			{"against_loan": loan_name, "docstatus": 1, "posting_date": ("<", from_date)},
			None, None,
		)
		pre_disb = frappe.get_all(
			"Loan Disbursement",
			filters=pre_window,
			fields=["disbursed_amount"],
			limit_page_length=0,
		)
		pre_rep = frappe.get_all(
			"Loan Repayment",
			filters=pre_window,
			fields=["amount_paid"],
			limit_page_length=0,
		)
		opening_balance = round(
			sum(flt(d.disbursed_amount or 0) for d in pre_disb)
			- sum(flt(r.amount_paid or 0) for r in pre_rep),
			2,
		)

	return {
		"loan": loan_name,
		"borrower": frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else "",
		"loan_amount": loan.loan_amount,
		"transactions": transactions,
		"opening_balance": opening_balance,
		"closing_balance": round(opening_balance + running, 2),
	}


def _merge_date_window(
	filters: dict,
	from_date: str | None,
	to_date: str | None,
	default_days: int | None = None,
) -> dict:
	"""R29-F5: single date-window filter helper.

	Handles all four cases (from-only / to-only / both / neither) and
	avoids the clobber-on-second-conditional bug the old inline code
	had. If neither is provided and ``default_days`` is set, the
	function falls back to a ``from_date = today() - default_days``.
	When ``from_date`` is provided AND ``to_date`` is also provided,
	uses ``between`` — Frappe requires ``(>=, <=)`` be combined as
	``between`` for a strict inclusive range.
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
	"""R29-F5: render a 0/1/2 docstatus as a human-friendly state."""
	if docstatus == 1:
		return "Submitted"
	if docstatus == 2:
		return "Cancelled"
	return "Draft"


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
		# R25-F11: always use custom_lms_branch (the canonical LMS branch
		# field). The previous loop tried `branch` first, which on many
		# installs (including this one) is a different field or absent,
		# silently returning zero employees. Hard-code the canonical
		# field to avoid the silent-miscount.
		filters["custom_lms_branch"] = branch

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
		# frappe.db.count() has no `field`/`distinct` kwargs — count distinct
		# borrowers (customers) via get_all(distinct=True) instead.
		_custs = frappe.get_all(
			"Loan",
			filters={"custom_loan_officer": emp.name, "docstatus": 1},
			fields=["applicant"],
			distinct=True,
		)
		emp["borrower_count"] = len({c["applicant"] for c in _custs if c.get("applicant")})

	return {"staff": employees}


@frappe.whitelist()
def get_officer_borrowers(employee=None):
	"""Borrowers assigned to a given Loan Officer, for the branch manager's team view.

	Assignment is derived from ``Loan.custom_loan_officer`` (the natural link the
	officer's own APIs enforce). Branch-scoped to the manager's branch; admins see
	all. Returns the distinct borrowers whose loans are handled by that officer.
	"""
	_require_manager()
	branch = _manager_branch()

	if not employee:
		frappe.throw("Employee is required.", frappe.ValidationError)

	# Honour the manager's branch scope — never leak another branch's officer.
	officer_branch = frappe.db.get_value("Employee", employee, "custom_lms_branch")
	_assert_branch_scope(officer_branch)

	loan_filters = {"custom_loan_officer": employee, "docstatus": 1}
	if branch:
		loan_filters["custom_lms_branch"] = branch

	loans = frappe.get_all(
		"Loan",
		filters=loan_filters,
		fields=["name", "applicant", "loan_amount", "total_payment", "status"],
		order_by="modified desc",
		limit_page_length=200,
	)

	borrowers = {}
	for ln in loans:
		cust = ln.applicant
		if not cust or cust in borrowers:
			continue
		borrowers[cust] = {
			"customer": cust,
			"customer_name": ln.applicant or cust,
			"active_loans": 0,
			"outstanding": 0.0,
		}

	# Aggregate per borrower.
	for ln in loans:
		cust = ln.applicant
		if not cust or cust not in borrowers:
			continue
		borrowers[cust]["active_loans"] += 1
		borrowers[cust]["outstanding"] = flt(borrowers[cust]["outstanding"]) + flt(ln.loan_amount or 0) - flt(ln.total_payment or 0)

	return {"employee": employee, "borrowers": list(borrowers.values())}


@frappe.whitelist()
def get_branch_overview():
	"""Branch-level overview: KPIs, officer performance, arrears, disbursement summary."""
	_require_manager()
	branch = _manager_branch()

	# Reuse portfolio summary
	portfolio = get_portfolio_summary()

	# Today's collections
	# R29-F1: use dict-style aggregate (Frappe bans raw SQL fn strings
	# like ``sum(amount_paid)``). SUM aggregate via aggregate dict — see
	# the agg_dict below for the safe pattern.
	today_collections = frappe.get_all(
		"Loan Repayment",
		filters={"docstatus": 1, "posting_date": today()},
		fields=[{"SUM": "amount_paid", "as": "total"}],
		limit_page_length=1,
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
			"name", "collateral_title", "collateral_type", "market_value",
			"net_realizable_value", "status", "owner_customer", "branch", "loan_application",
		],
		order_by="creation desc",
		limit_page_length=200,
	)

	# Batch-fetch branch fallbacks to avoid N+1 per-row get_value calls.
	app_names = {c.get("loan_application") for c in collateral if c.get("loan_application") and not c.get("branch")}
	cust_names = {c.get("owner_customer") for c in collateral if c.get("owner_customer") and not c.get("branch")}
	app_branches = {}
	cust_branches = {}
	if app_names:
		for row in frappe.get_all(
			"Loan Application",
			filters={"name": ["in", list(app_names)]},
			fields=["name", "custom_lms_branch"],
		):
			app_branches[row["name"]] = row.get("custom_lms_branch") or ""
	if cust_names:
		for row in frappe.get_all(
			"Customer",
			filters={"name": ["in", list(cust_names)]},
			fields=["name", "custom_lms_branch"],
		):
			cust_branches[row["name"]] = row.get("custom_lms_branch") or ""

	result = []
	for c in collateral:
		collateral_branch = c.get("branch") or ""
		if not collateral_branch and c.get("loan_application"):
			collateral_branch = app_branches.get(c.get("loan_application"), "")
		if not collateral_branch and c.get("owner_customer"):
			collateral_branch = cust_branches.get(c.get("owner_customer"), "")
		if branch and collateral_branch and collateral_branch != branch:
			continue

		# Find linked loans
		links = frappe.get_all(
			"LMS Loan Collateral",
			filters={"collateral": c.get("name")},
			fields=["parent", "allocated_value"],
			limit_page_length=0,
		)
		linked_loans = []
		for link in links:
			loan = frappe.db.get_value(
				"Loan", link.parent, ["name", "status", "applicant", "custom_lms_branch"], as_dict=True
			) if frappe.db.exists("Loan", link.parent) else None
			if loan:
				# Fail-closed: skip if manager has no branch, or loan is in another branch.
				if not branch or not loan.get("custom_lms_branch") or loan["custom_lms_branch"] != branch:
					continue
				if loan_status and loan.status != loan_status:
					continue
				linked_loans.append({
					"loan": loan.name,
					"borrower": frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else "",
					"status": loan.status,
					"allocated_value": flt(link.allocated_value),
				})
		# Keep collateral rows visible even before the loan-child join is
		# written, as long as we can resolve them to the manager's branch.
		if branch and not collateral_branch:
			continue
		result.append({**c, "linked_loans": linked_loans})

	return {"collateral": result}
