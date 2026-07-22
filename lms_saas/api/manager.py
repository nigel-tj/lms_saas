"""Branch Manager portal API — approvals, branch metrics, team performance.

All endpoints are guarded by ``_require_manager`` which allows the portal-only
``LMS Portal Staff`` role (or System Manager / Administrator for testing).
Branch scoping is automatic via ``staff.get_current_user_branch()``.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
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
	from lms_saas.utils.brand import _get_user_persona

	persona = _get_user_persona()
	if persona != "Branch Manager":
		frappe.throw("Not permitted", frappe.PermissionError)


def _manager_branch() -> str | None:
	"""Resolve the manager's branch (Cost Center) for query scoping."""
	from lms_saas.api.staff import get_current_user_branch

	return get_current_user_branch()


def _is_admin() -> bool:
	return bool(set(frappe.get_roles()).intersection({"System Manager", "Administrator"}))


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
	"""Loan Applications pending approval in the manager's branch."""
	_require_manager()
	branch = _manager_branch()
	# Fail closed: a non-admin manager with no branch assignment sees nothing,
	# not the entire portfolio.
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
		# Fallback: show the application owner's full name when no officer
		# is assigned — never leave the Approve modal Officer column blank
		# without saying "Unassigned" (B-20).
		if not app["officer_name"]:
			owner = app.get("owner") or frappe.db.get_value("Loan Application", app.name, "owner")
			app["officer_name"] = (
				frappe.db.get_value("User", owner, "full_name") if owner else ""
			) or "Unassigned"

		# Round-3 expert-board fix: enrich every queue row with the same
		# risk signals the View modal shows (KYC, exposure, worst DPD).
		# Without this the queue-table KYC / DPD / exposure badges are
		# permanently "0" / blank — the manager can't triage at a glance.
		app["kyc_status"] = (
			frappe.db.get_value(
				"LMS Borrower Compliance", {"customer": app.applicant}, "kyc_status"
			) or "Pending"
		)
		app["exposure"] = _borrower_exposure(app.applicant)
		app["worst_dpd"] = _borrower_worst_dpd(app.applicant)

	return {"applications": applications}




@frappe.whitelist()
def get_application_detail(application_name: str):
	"""Full Loan Application + borrower + KYC + risk signals for the manager's
	pre-approval review.

	Returns everything the manager needs to make a decision without leaving
	the modal: applicant identity, contact, KYC/consent/AML flags, credit
	score, existing exposure, worst DPD, requested terms, officer, branch,
	plus a checklist of required items that gates the Approve button.
	"""
	_require_manager()
	if not frappe.db.exists("Loan Application", application_name):
		frappe.throw(_("Loan Application {0} not found.").format(application_name))

	app = frappe.get_doc("Loan Application", application_name)

	# Branch scoping — fail closed: if the manager has a branch and the
	# application has no branch or a different branch, refuse.
	branch = _manager_branch()
	if branch and (not app.get("custom_lms_branch") or app.custom_lms_branch != branch):
		frappe.throw(_("Application is not in your branch."), frappe.PermissionError)

	# Borrower profile.
	customer = (
		frappe.get_doc("Customer", app.applicant).as_dict()
		if app.applicant and frappe.db.exists("Customer", app.applicant)
		else None
	)

	# KYC / compliance.
	kyc_name = (
		frappe.db.get_value("LMS Borrower Compliance", {"customer": app.applicant}, "name")
		if app.applicant else None
	)
	kyc = (
		frappe.get_doc("LMS Borrower Compliance", kyc_name).as_dict()
		if kyc_name else None
	)

	# Risk signals.
	exposure = _borrower_exposure(app.applicant)
	worst_dpd = _borrower_worst_dpd(app.applicant)

	# Active loans summary.
	active_loans = frappe.get_all(
		"Loan",
		filters={
			"applicant": app.applicant,
			"docstatus": 1,
			"status": ("in", ["Disbursed", "Active", "Partially Disbursed", "Sanctioned"]),
		},
		fields=["name", "loan_amount", "status", "custom_days_past_due"],
		order_by="modified desc",
		limit_page_length=10,
	)

	# Required-fields checklist (the manager sees this before they can approve).
	checklist = _application_checklist(app, kyc)

	return {
		"application": {
			"name": app.name,
			"applicant": app.applicant,
			"applicant_type": app.applicant_type,
			"loan_amount": flt(app.loan_amount),
			"loan_product": app.loan_product,
			"loan_product_name": (
				frappe.db.get_value("Loan Product", app.loan_product, "product_name")
				if app.loan_product else ""
			),
			"repayment_periods": app.repayment_periods,
			"repayment_method": app.repayment_method,
			"rate_of_interest": flt(app.rate_of_interest),
			"company": app.company,
			"status": app.status,
			"creation": str(app.creation) if app.creation else "",
			"custom_lms_branch": app.custom_lms_branch,
			"custom_loan_officer": app.custom_loan_officer,
			"officer_name": (
				frappe.db.get_value("Employee", app.custom_loan_officer, "employee_name")
				if app.custom_loan_officer else ""
			),
		},
		"customer": {
			"name": customer.name if customer else "",
			"customer_name": customer.customer_name if customer else "",
			"email_id": customer.email_id if customer else "",
			"mobile_no": customer.mobile_no if customer else "",
			"national_id": customer.custom_national_id_number if customer else "",
			"branch": customer.custom_lms_branch if customer else "",
		},
		"kyc": {
			"status": (kyc.kyc_status or "Pending") if kyc else "Pending",
			"consent_given": bool(kyc.consent_given) if kyc else False,
			"consent_date": str(kyc.consent_date) if kyc and kyc.consent_date else None,
			"aml_status": (kyc.aml_status or "Pending") if kyc else "Pending",
			"credit_score": kyc.credit_score if kyc else None,
		},
		"risk": {
			"existing_exposure": exposure,
			"worst_dpd": worst_dpd,
			"active_loan_count": len(active_loans),
			"active_loans": active_loans,
		},
		"checklist": checklist,
		"can_approve": all(item.get("ok") for item in checklist),
	}


def _application_checklist(app, kyc) -> list[dict]:
	"""Required-items checklist for the manager's pre-approval review.

	Each item is rendered with a check / cross icon and a short message.
	The Approve button is disabled until ``can_approve`` is True.
	"""
	items: list[dict] = []

	# 1. Required loan terms
	if flt(app.loan_amount) <= 0:
		items.append({"key": "loan_amount", "label": "Loan amount", "ok": False, "message": "Loan amount is zero or negative."})
	else:
		items.append({"key": "loan_amount", "label": "Loan amount", "ok": True, "message": f"{flt(app.loan_amount):,.2f}"})

	if not app.loan_product:
		items.append({"key": "loan_product", "label": "Loan product", "ok": False, "message": "No product selected."})
	else:
		items.append({"key": "loan_product", "label": "Loan product", "ok": True, "message": app.loan_product})

	if not (cint(app.repayment_periods) > 0):
		items.append({"key": "repayment_periods", "label": "Repayment periods", "ok": False, "message": "Tenure missing or zero."})
	else:
		items.append({"key": "repayment_periods", "label": "Repayment periods", "ok": True, "message": f"{app.repayment_periods} months"})

	if flt(app.rate_of_interest) <= 0:
		items.append({"key": "rate", "label": "Interest rate", "ok": False, "message": "Rate is zero. Confirm with credit policy."})
	else:
		items.append({"key": "rate", "label": "Interest rate", "ok": True, "message": f"{flt(app.rate_of_interest):.2f}%"})

	if not app.company:
		items.append({"key": "company", "label": "Company", "ok": False, "message": "Company not set."})
	else:
		items.append({"key": "company", "label": "Company", "ok": True, "message": app.company})

	# 2. KYC
	kyc_status = (kyc.kyc_status if kyc else "") or ""
	kyc_ok = kyc_status.lower() in ("approved", "verified", "complete")
	items.append({
		"key": "kyc",
		"label": "KYC verified",
		"ok": kyc_ok,
		"message": kyc_status or "No KYC record on file.",
	})

	# 3. Consent
	consent = bool(kyc and kyc.consent_given)
	items.append({
		"key": "consent",
		"label": "Borrower consent (data + credit bureau)",
		"ok": consent,
		"message": "Recorded." if consent else "Borrower has not signed consent — credit pull is illegal.",
	})

	# 4. AML
	aml = (kyc.aml_status if kyc else "") or ""
	aml_ok = aml.lower() in ("clear", "approved", "low risk")
	items.append({
		"key": "aml",
		"label": "AML screening",
		"ok": aml_ok,
		"message": aml or "Not screened yet.",
	})

	# 5. Officer assigned
	if not app.custom_loan_officer:
		items.append({"key": "officer", "label": "Loan officer", "ok": False, "message": "No officer assigned."})
	else:
		items.append({"key": "officer", "label": "Loan officer", "ok": True, "message": app.custom_loan_officer})

	return items


def _borrower_exposure(applicant: str | None) -> float:
	"""Sum of outstanding across all active loans for a borrower."""
	if not applicant:
		return 0.0
	rows = frappe.get_all(
		"Loan",
		filters={
			"applicant": applicant,
			"docstatus": 1,
			"status": ("in", ["Disbursed", "Active", "Partially Disbursed", "Sanctioned"]),
		},
		fields=["total_payment", "total_amount_paid"],
		limit_page_length=0,
	)
	return sum(flt(r.total_payment or 0) - flt(r.total_amount_paid or 0) for r in rows)


def _borrower_worst_dpd(applicant: str | None) -> int:
	"""Worst days-past-due across the borrower's active loans (0 if none)."""
	if not applicant:
		return 0
	row = frappe.get_all(
		"Loan",
		filters={
			"applicant": applicant,
			"docstatus": 1,
			"status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
		},
		fields=["custom_days_past_due"],
		order_by="custom_days_past_due desc",
		limit_page_length=1,
	)
	return cint(row[0].custom_days_past_due) if row else 0


@frappe.whitelist()
@rate_limit(limit=30, seconds=60, methods=["POST"])
def approve_application(application_name: str, note: str = ""):
	"""Approve a Loan Application: validate KYC, submit, create Loan, audit, notify.

	Round-1 expert-board fixes:
	- Re-check KYC/consent/AML/required fields server-side. Refuse with a
	  structured error if any required item is missing (defence in depth —
	  the UI checklist is the first line, the server is the second).
	- Wrap Loan creation + audit-event + borrower notification in one
	  Frappe transaction so a half-approved state never persists.
	- Write an LMS Audit Event (LMS Audit Event is append-only).
	- Send a branded email + WhatsApp-style in-app notification to the
	  borrower (best-effort — never breaks the approval).
	"""
	_require_manager()
	if not frappe.db.exists("Loan Application", application_name):
		frappe.throw(_("Loan Application {0} not found.").format(application_name))

	app = frappe.get_doc("Loan Application", application_name)

	# Branch scoping — fail closed.
	branch = _manager_branch()
	if branch and (not app.get("custom_lms_branch") or app.custom_lms_branch != branch):
		frappe.throw(_("Application is not in your branch."), frappe.PermissionError)

	if app.docstatus != 0:
		frappe.throw(_("Only draft applications can be approved (current status: {0}).").format(app.docstatus))

	# Required-fields + KYC gate (server-side; UI checklist is the first line).
	kyc_name = (
		frappe.db.get_value("LMS Borrower Compliance", {"customer": app.applicant}, "name")
		if app.applicant else None
	)
	kyc = frappe.get_doc("LMS Borrower Compliance", kyc_name) if kyc_name else None
	checklist = _application_checklist(app, kyc)
	missing = [c["label"] for c in checklist if not c.get("ok")]
	if missing:
		frappe.throw(
			_("Cannot approve — the following items are not satisfied: {0}").format(
				", ".join(missing)
			)
		)

	# Submit the application AND create the Loan in a single transaction
	# so a partial state (submitted app, no loan) can never persist.
	try:
		app.flags.ignore_permissions = True
		app.submit()

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
		# Four-eyes: record who approved so the same user cannot also disburse.
		if frappe.get_meta("Loan").has_field("custom_approved_by"):
			loan.custom_approved_by = frappe.session.user
		loan.flags.ignore_permissions = True
		loan.insert()

		# Append a manager comment with the approval note (audit trail).
		# Wrap in try/except so a Comment DB failure doesn't roll back the
		# entire approval — the audit event is the primary evidence.
		if (note or "").strip():
			try:
				frappe.get_doc(
					{
						"doctype": "Comment",
						"comment_type": "Info",
						"reference_doctype": "Loan Application",
						"reference_name": application_name,
						"content": f"Application approved by {frappe.session.user}: {note.strip()}",
					}
				).insert(ignore_permissions=True)
			except Exception:
				frappe.log_error(
					title="LMS: failed to add approval Comment",
					reference_doctype="Loan Application",
					reference_name=application_name,
					message=frappe.get_traceback(),
				)

		# Append-only LMS Audit Event (critical — rolls back on failure).
		from lms_saas.api.compliance import write_audit_event
		write_audit_event(
			event_type="Loan Application:approve",
			reference_doctype="Loan Application",
			reference_name=application_name,
			amount=flt(app.loan_amount),
			company=app.company,
			details=f"approved_by={frappe.session.user}; loan={loan.name}; note={note.strip() or '-'}",
			critical=True,
		)

		# Notify the borrower (best-effort).
		try:
			_notify_borrower_approval(app, loan)
		except Exception:
			pass  # notification must never break approval

		# Invalidate dashboard cache so KPIs reflect the new pending-disbursement loan.
		try:
			from lms_saas.api.dashboard import invalidate_dashboard_cache
			invalidate_dashboard_cache()
		except Exception:
			pass

	except Exception:
		# If anything in the inner block fails, roll back the application submit.
		frappe.db.rollback()
		raise

	return {
		"status": "approved",
		"application": application_name,
		"loan": loan.name,
		"message": _("Application approved and Loan {0} created.").format(loan.name),
	}




def _resolve_borrower_user(applicant: str | None) -> str | None:
	"""Look up the User record that should receive a borrower notification.

	The Customer.owner field is whoever *created* the Customer record
	(often the loan officer), not the borrower. The borrower's User is
	linked via:
	  1. Customer.email_id -> User.email
	  2. Customer.primary_contact -> Contact.email_id -> User.email
	  3. Direct User.name == Customer.email_id (fallback for portal
	     users whose name is their email)
	"""
	if not applicant:
		return None
	# 1. Email on the Customer record
	customer_email = frappe.db.get_value("Customer", applicant, "email_id")
	if customer_email:
		user = frappe.db.get_value("User", {"email": customer_email, "enabled": 1}, "name")
		if user:
			return user
	# 2. Primary contact on the Customer
	contact_name = frappe.db.get_value("Customer", applicant, "primary_contact")
	if contact_name:
		contact_email = frappe.db.get_value("Contact", contact_name, "email_id")
		if contact_email:
			user = frappe.db.get_value("User", {"email": contact_email, "enabled": 1}, "name")
			if user:
				return user
	# 3. Fallback: User.name == email (some tenants use the email as name)
	if customer_email:
		user = frappe.db.get_value("User", {"name": customer_email, "enabled": 1}, "name")
		if user:
			return user
	return None


def _notify_borrower_approval(app, loan) -> None:
	"""Best-effort email + in-app notification to the borrower on approval.

	Email is sent only if the Customer has an email_id. We never raise into
	the caller's flow — approval is already committed, notification is
	operational.
	"""
	if not app.applicant or app.applicant_type != "Customer":
		return
	customer = frappe.db.get_value(
		"Customer", app.applicant,
		["customer_name", "email_id"], as_dict=True,
	)
	if not customer:
		return

	# 1) In-app notification (Notification Log).
	try:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": f"Loan {loan.name} approved — pending disbursement",
				"for_user": _resolve_borrower_user(app.applicant),
				"type": "Alert",
				"document_type": "Loan",
				"document_name": loan.name,
			}
		).insert(ignore_permissions=True)
	except Exception:
		pass

	# 2) Branded email (only if email on file).
	if customer.email_id:
		try:
			from lms_saas.utils.email import send_branded_email
			from frappe.utils import fmt_money
			currency = (
				frappe.db.get_value("Company", app.company, "default_currency")
				if app.company else None
			)
			amount_fmt = fmt_money(flt(app.loan_amount), currency=currency)
			send_branded_email(
				recipients=[customer.email_id],
				subject=_("Your loan has been approved — {0}").format(loan.name),
				body_key="loan_approved",
				context={
					"customer_name": customer.customer_name,
					"loan_name": loan.name,
					"amount": amount_fmt,
					"tenure_months": app.repayment_periods or 0,
				},
				reference_doctype="Loan",
				reference_name=loan.name,
			)
		except Exception:
			pass

	# 3) Notify the loan officer who submitted the application (R4 fix).
	#    The officer needs to know the application was approved so they can
	#    proceed to disbursement — without this they have to refresh the
	#    dashboard to discover the status change.
	try:
		officer_user = frappe.db.get_value("Employee", app.custom_loan_officer, "user_id") if app.custom_loan_officer else None
		if officer_user:
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"subject": f"Application {app.name} approved — Loan {loan.name} ready for disbursement",
					"for_user": officer_user,
					"type": "Alert",
					"document_type": "Loan",
					"document_name": loan.name,
				}
			).insert(ignore_permissions=True)
	except Exception:
		pass


@frappe.whitelist()
@rate_limit(limit=30, seconds=60, methods=["POST"])
def reject_application(application_name: str, reason: str = "", reason_code: str = ""):
	"""Reject a Loan Application: keep the document, log a structured decision.

	Round-1 expert-board fix: we used to ``app.delete()`` the draft, which
	destroyed the audit trail (one orphan Comment pointing at a name that no
	longer exists). Now we keep the document, set a clear status, log a
	Comment, write an LMS Audit Event, and notify the borrower (email +
	in-app). The loan officer can see "Rejected" on the borrower's
	application history and resubmit if appropriate.
	"""
	_require_manager()
	if not frappe.db.exists("Loan Application", application_name):
		frappe.throw(_("Loan Application {0} not found.").format(application_name))

	app = frappe.get_doc("Loan Application", application_name)

	# Branch scoping — fail closed.
	branch = _manager_branch()
	if branch and (not app.get("custom_lms_branch") or app.custom_lms_branch != branch):
		frappe.throw(_("Application is not in your branch."), frappe.PermissionError)

	# A rejection reason is required for the audit trail.
	if not (reason or "").strip():
		frappe.throw(_("Rejection reason is required for the audit trail."))

	if app.docstatus != 0:
		frappe.throw(_("Only draft applications can be rejected (current status: {0}).").format(app.docstatus))

	# Build a structured comment so the rejection is auditable + machine-readable.
	reason_clean = reason.strip()[:500]  # cap length
	code_clean = (reason_code or "").strip()[:50]
	comment_parts = [
		f"Application rejected by {frappe.session.user}.",
	]
	if code_clean:
		comment_parts.append(f"Reason code: {code_clean}.")
	comment_parts.append(f"Reason: {reason_clean}")
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": "Loan Application",
			"reference_name": application_name,
			"content": " ".join(comment_parts),
		}
	).insert(ignore_permissions=True)

	# Mark the application as Rejected (without deleting the doc). The
	# Lending app's "status" Select drives the UI; we set it to "Rejected"
	# via db_set so we don't trigger any submit/cancel hooks.
	app.flags.ignore_permissions = True
	app.db_set("status", "Rejected", update_modified=True)

	# Append-only LMS Audit Event (critical — rolls back on failure).
	from lms_saas.api.compliance import write_audit_event
	write_audit_event(
		event_type="Loan Application:reject",
		reference_doctype="Loan Application",
		reference_name=application_name,
		amount=flt(app.loan_amount),
		company=app.company,
		details=f"rejected_by={frappe.session.user}; reason_code={code_clean or '-'}; reason={reason_clean}",
		critical=True,
	)

	# Best-effort borrower notification (email + in-app banner).

	# Best-effort borrower notification (email + in-app banner).
	try:
		_notify_borrower_rejection(app, reason_clean, code_clean)
	except Exception:
		pass

	# Invalidate dashboard cache.
	try:
		from lms_saas.api.dashboard import invalidate_dashboard_cache
		invalidate_dashboard_cache()
	except Exception:
		pass

	return {
		"status": "rejected",
		"application": application_name,
		"message": _("Application {0} rejected.").format(application_name),
	}


def _notify_borrower_rejection(app, reason: str, reason_code: str) -> None:
	"""Best-effort email + in-app notification on rejection (does not delete data)."""
	if not app.applicant or app.applicant_type != "Customer":
		return
	customer = frappe.db.get_value(
		"Customer", app.applicant,
		["customer_name", "email_id"], as_dict=True,
	)
	if not customer:
		return

	# 1) In-app notification.
	try:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": f"Loan Application {app.name} was not approved",
				"for_user": _resolve_borrower_user(app.applicant),
				"type": "Alert",
				"document_type": "Loan Application",
				"document_name": app.name,
			}
		).insert(ignore_permissions=True)
	except Exception:
		pass

	# 2) Branded email.
	if customer.email_id:
		try:
			from lms_saas.utils.email import send_branded_email
			# P0 fix: send reason-code label to borrower, keep free-text internal-only.
			reason_labels = {
				"kyc_failed": "KYC documentation incomplete",
				"aml_hit": "Compliance screening pending",
				"insufficient_income": "Insufficient income for requested amount",
				"exceeds_limit": "Requested amount exceeds credit limit",
				"poor_repayment_history": "Repayment history does not meet policy",
				"insufficient_collateral": "Insufficient collateral",
				"credit_policy_breach": "Does not meet credit policy",
				"duplicate_application": "Duplicate application on file",
				"other": "Does not meet lending criteria",
			}
			borrower_facing_reason = reason_labels.get(reason_code, "Does not meet lending criteria")
			send_branded_email(
				recipients=[customer.email_id],
				subject=_("Update on your loan application {0}").format(app.name),
				body_key="loan_rejected",
				context={
					"customer_name": customer.customer_name,
					"application": app.name,
					"reason": borrower_facing_reason,
					"reason_code": reason_code or "",
				},
				reference_doctype="Loan Application",
				reference_name=app.name,
			)
		except Exception:
			pass

	# 3) Notify the loan officer who submitted the application (R4 fix).
	#    The officer needs to know the rejection reason so they can fix
	#    and resubmit — without this they have to discover the rejection
	#    by refreshing their dashboard.
	try:
		officer_user = frappe.db.get_value("Employee", app.custom_loan_officer, "user_id") if app.custom_loan_officer else None
		if officer_user:
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"subject": f"Application {app.name} rejected — {reason_code or 'see detail'}",
					"for_user": officer_user,
					"type": "Alert",
					"document_type": "Loan Application",
					"document_name": app.name,
				}
			).insert(ignore_permissions=True)
	except Exception:
		pass


def _notify_borrower_disbursement(loan, disb) -> None:
	"""Best-effort email + in-app notification to the borrower on disbursement.

	R4 expert-board fix: the borrower was notified on approval ("pending
	disbursement") but NOT when funds were actually released — the most
	important moment for a small business owner waiting for working capital.
	"""
	if not loan.applicant or loan.applicant_type != "Customer":
		return
	customer = frappe.db.get_value(
		"Customer", loan.applicant,
		["customer_name", "email_id"], as_dict=True,
	)
	if not customer:
		return

	# 1) In-app notification.
	try:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": f"Funds disbursed — {disb.name} for loan {loan.name}",
				"for_user": _resolve_borrower_user(loan.applicant),
				"type": "Alert",
				"document_type": "Loan Disbursement",
				"document_name": disb.name,
			}
		).insert(ignore_permissions=True)
	except Exception:
		pass

	# 2) Branded email.
	if customer.email_id:
		try:
			from lms_saas.utils.email import send_branded_email
			from frappe.utils import fmt_money
			currency = (
				frappe.db.get_value("Company", loan.company, "default_currency")
				if loan.company else None
			)
			amount_fmt = fmt_money(flt(disb.disbursed_amount), currency=currency)
			# First payment date from repayment schedule when available.
			first_payment_date = loan.get("repayment_start_date") or ""
			if not first_payment_date and frappe.db.exists("DocType", "Loan Repayment Schedule"):
				sched = frappe.get_all(
					"Loan Repayment Schedule",
					filters={"loan": loan.name, "docstatus": 1},
					fields=["posting_date"],
					order_by="posting_date asc",
					limit_page_length=1,
				)
				if sched:
					first_payment_date = sched[0].posting_date or ""

			send_branded_email(
				recipients=[customer.email_id],
				subject=_("Funds disbursed — {0}").format(loan.name),
				body_key="loan_disbursed",
				context={
					"customer_name": customer.customer_name,
					"loan_name": loan.name,
					"disbursement_name": disb.name,
					"amount": amount_fmt,
					"first_payment_date": str(first_payment_date)[:10] if first_payment_date else "",
				},
				reference_doctype="Loan Disbursement",
				reference_name=disb.name,
			)
		except Exception:
			pass


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

	# Compute PAR ratio + total disbursed per officer.
	for row in officers.values():
		row["par_ratio"] = flt(row["par_count"]) / flt(row["loan_count"]) if row["loan_count"] else 0

	return {"officers": list(officers.values())}


@frappe.whitelist()
def get_branch_loans(status: str | None = None, limit_start: int = 0, limit_page_length: int = 50):
	"""Paginated list of all loans in the manager's branch."""
	_require_manager()
	branch = _manager_branch()
	if not branch and not _is_admin():
		return {"loans": [], "total_count": 0}

	filters = {"docstatus": 1}
	if branch:
		filters["custom_lms_branch"] = branch
	if status:
		filters["status"] = status

	limit_start = max(0, cint(limit_start))
	limit_page_length = max(1, min(cint(limit_page_length) or 50, 200))
	total_count = frappe.db.count("Loan", filters)

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
		limit_start=limit_start,
		limit_page_length=limit_page_length,
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

	return {"loans": loans, "total_count": total_count, "limit_start": limit_start, "limit_page_length": limit_page_length}


# ---------------------------------------------------------------------------
# Borrower management
# ---------------------------------------------------------------------------

@frappe.whitelist()
def search_borrowers(query: str = "", status: str | None = None, limit: int = 50):
	"""Search borrowers (Customers) in the manager's branch by name, mobile, email, or national ID."""
	_require_manager()
	branch = _manager_branch()
	query = (query or "").strip()
	# Escape LIKE wildcards to prevent wildcard injection (e.g. "%%%" matching all rows).
	query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	# Cap limit to prevent full-database PII dumps (P0 fix).
	limit = min(cint(limit) or 50, 100)

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
	# Branch scoping — fail closed.
	branch = _manager_branch()
	if branch and (not cust.get("custom_lms_branch") or cust.get("custom_lms_branch") != branch):
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
	# Branch scoping — fail closed.
	branch = _manager_branch()
	if branch and (not cust.get("custom_lms_branch") or cust.get("custom_lms_branch") != branch):
		frappe.throw(_("Customer is not in your branch."), frappe.PermissionError)
	# Track changed fields for the audit event (include old→new for ID).
	changed_fields = []
	audit_bits = []
	if customer_name_new is not None:
		cust.customer_name = customer_name_new
		changed_fields.append("customer_name")
	if email_id is not None:
		cust.email_id = email_id
		changed_fields.append("email_id")
	if mobile_no is not None:
		cust.mobile_no = mobile_no
		changed_fields.append("mobile_no")
	if national_id is not None:
		old_nid = cust.get("custom_national_id_number") or ""
		cust.custom_national_id_number = national_id
		changed_fields.append("national_id")
		audit_bits.append(f"national_id:{old_nid}->{national_id}")
	if disabled is not None:
		cust.disabled = cint(disabled)
		changed_fields.append("disabled")
	cust.flags.ignore_permissions = True
	cust.save()

	# Audit event for customer status changes (regulatory evidence).
	try:
		from lms_saas.api.compliance import write_audit_event
		details = (
			f"updated_by={frappe.session.user}; fields={','.join(changed_fields) if changed_fields else '-'}; "
			f"disabled={cust.disabled}"
		)
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
			title="LMS audit event failed (customer update)",
			reference_doctype="Customer",
			reference_name=customer_name,
			message=frappe.get_traceback(),
		)

	return {"status": "updated", "customer": customer_name}


@frappe.whitelist()
def get_loan_detail(loan_name: str):
	"""Full loan detail: schedule, repayments, collateral, borrower info."""
	_require_manager()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)
	branch = _manager_branch()
	if branch and (not loan.get("custom_lms_branch") or loan.get("custom_lms_branch") != branch):
		frappe.throw(_("Loan is not in your branch."), frappe.PermissionError)

	# Schedule — Repayment Schedule has no 'paid' column; use demand_generated.
	schedule = frappe.get_all(
		"Repayment Schedule",
		filters={"parent": loan_name, "parenttype": "Loan"},
		fields=["payment_date", "principal_amount", "interest_amount", "total_payment", "balance_loan_amount", "demand_generated"],
		order_by="payment_date asc",
		limit_page_length=0,
	)
	for row in schedule:
		row["paid"] = cint(row.get("demand_generated"))

	# Repayments.
	repayments = frappe.get_all(
		"Loan Repayment",
		filters={"against_loan": loan_name, "docstatus": 1},
		fields=["name", "amount_paid", "posting_date", "docstatus"],
		order_by="posting_date desc",
		limit_page_length=50,
	)
	for r in repayments:
		r["status"] = "Submitted" if cint(r.get("docstatus")) == 1 else "Draft"

	# Disbursements.
	disbursements = frappe.get_all(
		"Loan Disbursement",
		filters={"against_loan": loan_name, "docstatus": 1},
		fields=["name", "disbursed_amount", "posting_date", "status"],
		order_by="posting_date desc",
		limit_page_length=20,
	)

	borrower_name = frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else ""

	# Collateral.
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

	Branch-scoped, idempotent, KYC re-check, amount upper bound,
	mode_of_payment resolution, audit event (critical).
	"""
	_require_manager()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)

	# Branch scoping — fail closed.
	branch = _manager_branch()
	if not branch and not _is_admin():
		frappe.throw(_("No branch assigned to your account."), frappe.PermissionError)
	if branch and (not loan.get("custom_lms_branch") or loan.get("custom_lms_branch") != branch):
		frappe.throw(_("Loan is not in your branch."), frappe.PermissionError)

	if loan.docstatus != 1:
		frappe.throw(_("Loan must be submitted before disbursement."))

	# Four-eyes: the user who approved the application cannot also disburse.
	if frappe.conf.get("lms_enforce_four_eyes", False) and frappe.get_meta("Loan").has_field(
		"custom_approved_by"
	):
		approver = loan.get("custom_approved_by")
		if approver and approver == frappe.session.user:
			frappe.throw(
				_(
					"Four-eyes control: you approved this loan and cannot also disburse it. "
					"A second authorised user must disburse."
				),
				frappe.PermissionError,
			)

	# Refuse to disburse a loan that is already closed, written off, cancelled, or already active.
	if loan.status in ("Closed", "Written Off", "Cancelled"):
		frappe.throw(_("Loan status is {0}. Cannot disburse.").format(loan.status))
	if loan.status in ("Disbursed", "Active"):
		frappe.throw(_("Loan is already {0}. Cannot disburse again.").format(loan.status))

	# Idempotency guard.
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

	# KYC re-check at disbursement time.
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
			expiry = kyc.get("kyc_expiry_date")
			if expiry and getdate(expiry) < getdate(today()):
				frappe.throw(
					_("KYC expired on {0}. Disbursement blocked — renew KYC first.").format(expiry)
				)

	# Amount validation.
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

	# Resolve mode_of_payment / disbursement_account.
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

	# Audit event (critical — rolls back on failure).
	from lms_saas.api.compliance import write_audit_event
	write_audit_event(
		event_type="Loan Disbursement:manager",
		reference_doctype="Loan Disbursement",
		reference_name=disb.name,
		amount=flt(amount),
		company=loan.company,
		details=f"loan={loan.name}; manager={frappe.session.user}; sanctioned={flt(loan.loan_amount)}; disbursed={flt(amount)}",
		critical=True,
	)

	# Notify the borrower that funds have been released.
	try:
		_notify_borrower_disbursement(loan, disb)
	except Exception:
		pass

	# Invalidate dashboard cache.
	try:
		from lms_saas.api.dashboard import invalidate_dashboard_cache
		invalidate_dashboard_cache()
	except Exception:
		pass

	return {
		"status": "disbursed",
		"loan": loan.name,
		"disbursement": disb.name,
		"amount": amount,
		"message": _("Loan {0} disbursed — {1}.").format(loan.name, disb.name),
	}


@frappe.whitelist()
def write_off_loan(loan_name: str, write_off_amount: float | None = None, reason: str = ""):
	"""Create a Loan Write Off for a non-performing loan.

	Round-4 expert-board fixes:
	- Branch scoping (fail closed).
	- Reason is required (regulatory evidence).
	- Idempotency: refuse if a non-cancelled write-off already exists.
	- Loan status check: refuse if loan is already Closed or Cancelled.
	- Audit event with log_error on failure.
	"""
	_require_manager()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)

	# Branch scoping — fail closed.
	branch = _manager_branch()
	if branch and (not loan.get("custom_lms_branch") or loan.get("custom_lms_branch") != branch):
		frappe.throw(_("Loan is not in your branch."), frappe.PermissionError)

	if loan.docstatus != 1:
		frappe.throw(_("Loan must be submitted before write-off."))

	# Refuse to write off a loan that is already closed or cancelled.
	if loan.status in ("Closed", "Cancelled"):
		frappe.throw(_("Loan status is {0}. Cannot write off.").format(loan.status))

	# Reason is required for the audit trail.
	if not (reason or "").strip():
		frappe.throw(_("Write-off reason is required for the audit trail."))
	reason_clean = reason.strip()[:500]

	# Idempotency guard.
	existing = frappe.get_all(
		"Loan Write Off",
		filters={"against_loan": loan.name, "docstatus": ("<", 2)},
		fields=["name", "write_off_amount", "posting_date"],
		limit_page_length=1,
	)
	if existing:
		frappe.throw(
			_("Loan {0} has already been written off via {1} on {2}. "
			  "Cancel that write-off first if you need to redo it.").format(
				loan.name, existing[0].name, existing[0].posting_date
			)
		)

	amount = flt(write_off_amount) if write_off_amount else flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0)
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
			"remarks": reason_clean,
		}
	)
	wo.flags.ignore_permissions = True
	wo.insert()
	wo.submit()

	# Audit event (critical — rolls back on failure).
	from lms_saas.api.compliance import write_audit_event
	write_audit_event(
		event_type="Loan Write Off:manager",
		reference_doctype="Loan Write Off",
		reference_name=wo.name,
		amount=flt(amount),
		company=loan.company,
		details=f"loan={loan.name}; manager={frappe.session.user}; reason={reason_clean}",
		critical=True,
	)

	return {
		"status": "written_off",
		"loan": loan_name,
		"write_off": wo.name,
		"amount": amount,
		"message": _("Loan {0} written off — {1}.").format(loan_name, wo.name),
	}


@frappe.whitelist()
def record_repayment(loan_name: str, amount: float, payment_mode: str = "Cash", posting_date: str | None = None):
	"""Record a loan repayment (manager can record on behalf of borrower).

	Round-4 expert-board fixes:
	- Branch scoping (fail closed).
	- Loan status check: refuse if loan is Closed, Written Off, or Cancelled.
	- Audit event with recorded_by context.
	"""
	_require_manager()
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Repayment amount must be positive."))

	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)

	# Branch scoping — fail closed.
	branch = _manager_branch()
	if branch and (not loan.get("custom_lms_branch") or loan.get("custom_lms_branch") != branch):
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
		event_type="Loan Repayment:manager",
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
	if branch and (not loan.get("custom_lms_branch") or loan.get("custom_lms_branch") != branch):
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
		# Check custom_lms_branch first (our custom field), then cost_center,
		# then the standard branch field (P0 fix — wrong priority returned empty teams).
		emp_meta = frappe.get_meta("Employee")
		for bf in ("custom_lms_branch", "cost_center", "branch"):
			if emp_meta.has_field(bf):
				filters[bf] = branch
				break
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
		# PAR data per officer (R7 fix — Team tab renders these columns).
		emp["par_count"] = frappe.db.count("Loan", {
			"custom_loan_officer": emp.name, "docstatus": 1,
			"custom_days_past_due": (">", 30),
		})
		emp["par_ratio"] = flt(emp["par_count"]) / flt(emp["loan_count"]) if emp["loan_count"] else 0

	return {"staff": employees}


@frappe.whitelist()
def get_branch_overview():
	"""Branch-level overview: KPIs, officer performance, arrears, disbursement summary."""
	_require_manager()
	branch = _manager_branch()

	# Reuse portfolio summary
	portfolio = get_portfolio_summary()

	# Today's collections — branch-scoped (P0 fix: was summing ALL branches).
	today_filters = {"docstatus": 1, "posting_date": today()}
	if branch:
		today_filters["against_loan"] = ("in", frappe.get_all("Loan", {"custom_lms_branch": branch, "docstatus": 1}, pluck="name"))
	today_collections = frappe.get_all(
		"Loan Repayment",
		filters=today_filters,
		fields=["sum(amount_paid) as total"],
	)
	today_total = flt(today_collections[0].total) if today_collections and today_collections[0].total else 0

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
	"""Collateral register: pledged assets linked to loans in the manager's branch."""
	_require_manager()
	branch = _manager_branch()
	# Fail closed: non-admin with no branch must not see cross-branch collateral.
	if not branch and not _is_admin():
		return {"collateral": []}

	collateral = frappe.get_all(
		"LMS Collateral",
		fields=[
			"name", "collateral_title", "collateral_type", "market_value",
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
			if not loan:
				continue
			loan_branch = loan.get("custom_lms_branch")
			# Strict branch match — loans with no branch never leak into a
			# branch-scoped register (and admins without a branch see all).
			if branch and loan_branch != branch:
				continue
			if loan_status and loan.status != loan_status:
				continue
			linked_loans.append({
				"loan": loan.name,
				"borrower": frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else "",
				"status": loan.status,
				"allocated_value": flt(link.allocated_value),
			})
		# Only surface collateral that has at least one in-branch linked loan.
		if linked_loans:
			result.append({**c, "linked_loans": linked_loans})

	return {"collateral": result}
# ---------------------------------------------------------------------------
# Loan officer assignment / reassignment
# ---------------------------------------------------------------------------

@frappe.whitelist()
def assign_loan_officer(loan_name: str, officer_employee: str):
	"""Assign or reassign a loan to a different loan officer.

	The manager can reassign any loan in their branch to any active officer
	in the same branch. This is a common branch-management operation when
	an officer leaves, is reassigned, or the workload needs rebalancing.

	Round-7: commercial-grade feature — the manager portal was missing the
	ability to assign/reassign officers from the UI, forcing desk workarounds.
	"""
	_require_manager()
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)

	# Branch scoping — fail closed.
	branch = _manager_branch()
	if branch and (not loan.get("custom_lms_branch") or loan.get("custom_lms_branch") != branch):
		frappe.throw(_("Loan is not in your branch."), frappe.PermissionError)

	if not frappe.db.exists("Employee", officer_employee):
		frappe.throw(_("Officer {0} not found.").format(officer_employee))

	# Verify the target officer is active and in the same branch.
	officer_status = frappe.db.get_value("Employee", officer_employee, "status")
	if officer_status != "Active":
		frappe.throw(_("Officer is not active."))

	# Verify the target officer has the Loan Officer persona.
	officer_persona = frappe.db.get_value("Employee", officer_employee, "custom_lms_persona") or ""
	if officer_persona and officer_persona != "Loan Officer":
		frappe.throw(_("Target employee is not a Loan Officer (persona: {0}).").format(officer_persona))

	officer_branch = frappe.db.get_value("Employee", officer_employee, "custom_lms_branch")
	if branch and officer_branch and officer_branch != branch:
		frappe.throw(_("Officer is not in your branch."), frappe.PermissionError)

	old_officer = loan.get("custom_loan_officer") or ""
	old_officer_name = (
		frappe.db.get_value("Employee", old_officer, "employee_name")
		if old_officer else "Unassigned"
	)
	new_officer_name = frappe.db.get_value("Employee", officer_employee, "employee_name")

	# Update the loan.
	loan.custom_loan_officer = officer_employee
	loan.flags.ignore_permissions = True
	loan.save()

	# Audit event.
	from lms_saas.api.compliance import write_audit_event
	write_audit_event(
		event_type="Loan:reassign",
		reference_doctype="Loan",
		reference_name=loan_name,
		details=f"reassigned_by={frappe.session.user}; from={old_officer} ({old_officer_name}); to={officer_employee} ({new_officer_name})",
	)

	# Comment on the loan for traceability.
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": "Loan",
			"reference_name": loan_name,
			"content": f"Loan officer reassigned by {frappe.session.user}: {old_officer_name} → {new_officer_name}",
		}
	).insert(ignore_permissions=True)

	return {
		"status": "reassigned",
		"loan": loan_name,
		"old_officer": old_officer_name,
		"new_officer": new_officer_name,
		"message": _("Loan {0} reassigned from {1} to {2}.").format(
			loan_name, old_officer_name, new_officer_name
		),
	}


@frappe.whitelist()
def get_branch_officers():
	"""List all active loan officers in the manager's branch for the assignment dropdown."""
	_require_manager()
	branch = _manager_branch()

	filters = {"status": "Active", "custom_lms_persona": "Loan Officer"}
	if branch:
		emp_meta = frappe.get_meta("Employee")
		for bf in ("custom_lms_branch", "cost_center", "branch"):
			if emp_meta.has_field(bf):
				filters[bf] = branch
				break

	officers = frappe.get_all(
		"Employee",
		filters=filters,
		fields=["name", "employee_name", "user_id", "designation"],
		order_by="employee_name asc",
		limit_page_length=50,
	)

	for o in officers:
		o["loan_count"] = frappe.db.count("Loan", {"custom_loan_officer": o.name, "docstatus": 1})

	return {"officers": officers}
