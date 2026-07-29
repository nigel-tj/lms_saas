"""Whitelisted API endpoints for LMS staff portal actions.

Officer: submit loan applications, search customers.
Manager: approve / reject loan applications.

Phase 4.4: all role checks delegate to the persona-aware guard in
``lms_saas.utils.portal._user_can`` (or the brand-level helpers). The legacy
role names ``LMS Loan Officer`` / ``LMS Branch Manager`` / ``LMS Collector``
are no longer accepted — they were retired in install.py:_retire_legacy_roles.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt


# ── Persona-aware guards ──
# Map a legacy role name (or call-site semantic) to the permission bit the
# nav exposes. We keep the ``_require_role(legacy_name)`` call signature so
# we don't have to rewrite every call site, but the actual check is
# persona-based — the legacy role is just a tag for readability.

_LEGACY_TO_PERM = {
	"LMS Loan Officer": "can_officer",
	"LMS Branch Manager": "can_manager",
	"LMS Collector": "can_collect",
	"LMS Admin": "can_admin",
}


def _require_role(role: str) -> None:
	"""Persona-aware guard used by every whitelisted endpoint in this module.

	``role`` is one of the legacy role names (kept for call-site readability);
	the actual decision is made via ``_user_can(perm)``. Admins always pass.
	"""
	if frappe.session.user == "Guest":
		frappe.throw("Please log in", frappe.PermissionError)
	roles = set(frappe.get_roles())
	if roles.intersection({"System Manager", "Administrator"}):
		return
	# Late import — the helper avoids a circular dep at module load.
	from lms_saas.utils.portal import _user_can

	perm = _LEGACY_TO_PERM.get(role, "can_admin")
	if not _user_can(perm):
		frappe.throw("You do not have permission to perform this action.", frappe.PermissionError)


# ── Officer endpoints ──

@frappe.whitelist()
def submit_loan_application_officer(
	applicant: str,
	loan_amount: float,
	loan_product: str | None = None,
	repayment_periods: int = 6,
):
	"""Loan Officer creates a draft Loan Application on behalf of a client.

	R22-C2: writes LMS Audit Event for the officer-initiated submission.
	Also fixes the branch-scoping bug: prior versions did not set
	custom_lms_branch on the application, so manager approval queues
	filtered by branch missed officer-submitted applications.
	"""
	_require_role("LMS Loan Officer")

	loan_amount = flt(loan_amount)
	repayment_periods = int(repayment_periods)
	if loan_amount <= 0:
		frappe.throw("Loan amount must be positive.")
	if repayment_periods <= 0:
		frappe.throw("Repayment periods must be positive.")

	# Validate applicant exists
	if not frappe.db.exists("Customer", applicant):
		frappe.throw(f"Customer '{applicant}' not found.")

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not loan_product:
		loan_product = frappe.db.get_value(
			"Loan Product", {"company": company, "product_code": "LMS-STD"}, "name"
		)
	if not loan_product:
		frappe.throw("No loan product specified and default product not found.")

	rate = flt(frappe.db.get_value("Loan Product", loan_product, "rate_of_interest") or 0)

	# R22-C2 fix: branch scoping. Resolve the branch from the Customer
	# record (the source of truth used by all other flows). Without
	# this, the manager's approval queue — which filters by
	# custom_lms_branch — would not return officer-submitted apps
	# belonging to a customer in a different branch from the manager.
	cust_branch = frappe.db.get_value("Customer", applicant, "custom_lms_branch")
	cust_officer = frappe.db.get_value("Customer", applicant, "custom_loan_officer")
	# Officer's own branch wins when the customer has no branch (a
	# brand-new borrower who hasn't been assigned yet). This matches
	# the policy used elsewhere — the queue falls back to "all
	# branches" if the manager has no branch set.
	if not cust_branch:
		import lms_saas.api.staff as _staff
		cust_branch = _staff.get_current_user_branch()
	# Officer fallback for traceability (the regulator's
	# "who originated this?" walk).
	if not cust_officer:
		from lms_saas.api.officer import _officer_employee
		cust_officer = _officer_employee()

	app = frappe.get_doc(
		{
			"doctype": "Loan Application",
			"applicant_type": "Customer",
			"applicant": applicant,
			"company": company,
			"loan_product": loan_product,
			"loan_amount": loan_amount,
			"repayment_periods": repayment_periods,
			"rate_of_interest": rate,
			"custom_lms_branch": cust_branch,
			"custom_loan_officer": cust_officer,
		}
	)
	app.insert(ignore_permissions=True)

	# R22-C2: audit the officer submission. critical=True so a write
	# failure surfaces in the operator's error log.
	from lms_saas.api.compliance import write_audit_event

	try:
		write_audit_event(
			event_type="LoanApplication:Submitted:Officer",
			reference_doctype="Loan Application",
			reference_name=app.name,
			amount=loan_amount,
			details=(
				f"applicant={applicant} loan_product={loan_product} "
				f"branch={cust_branch or 'unassigned'} officer={cust_officer or 'unassigned'}"
			),
			critical=True,
		)
	except Exception:
		frappe.log_error(
			title="LMS audit event failed (officer submit)",
			message=frappe.get_traceback(),
		)

	return {"application": app.name, "status": app.status or "Draft"}


@frappe.whitelist()
def search_customers(query: str):
	"""Quick customer search for the officer portal."""
	_require_role("LMS Loan Officer")

	if not query or len(query) < 2:
		return {"results": []}

	results = frappe.get_all(
		"Customer",
		or_filters={
			"name": ("like", f"%{query}%"),
			"customer_name": ("like", f"%{query}%"),
		},
		fields=["name", "customer_name", "mobile_no", "email_id"],
		limit_page_length=15,
		order_by="customer_name asc",
	)
	return {"results": results}


@frappe.whitelist()
def get_loan_products():
	"""Return available loan products for the officer form."""
	_require_role("LMS Loan Officer")

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	products = frappe.get_all(
		"Loan Product",
		filters={"company": company, "disabled": 0},
		fields=["name", "product_name", "rate_of_interest", "maximum_loan_amount"],
	)
	return {"products": products}


# ── Manager endpoints ──

@frappe.whitelist()
def approve_loan_application(application_name: str):
	"""Branch Manager approves a loan application (submit workflow)."""
	_require_role("LMS Branch Manager")

	if not frappe.db.exists("Loan Application", application_name):
		frappe.throw(f"Application '{application_name}' not found.")

	app = frappe.get_doc("Loan Application", application_name)
	if app.docstatus == 1:
		frappe.throw("Application is already submitted.")

	app.status = "Approved"
	app.flags.ignore_permissions = True
	app.submit()

	return {"application": app.name, "status": "Approved"}


@frappe.whitelist()
def reject_loan_application(application_name: str, reason: str = ""):
	"""Branch Manager rejects a loan application."""
	_require_role("LMS Branch Manager")

	if not frappe.db.exists("Loan Application", application_name):
		frappe.throw(f"Application '{application_name}' not found.")

	app = frappe.get_doc("Loan Application", application_name)
	if app.docstatus == 2:
		frappe.throw("Application is already cancelled.")

	app.status = "Rejected"
	if reason:
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": "Loan Application",
				"reference_name": application_name,
				"content": f"Rejection reason: {reason}",
			}
		).insert(ignore_permissions=True)

	app.flags.ignore_permissions = True
	app.save()

	return {"application": app.name, "status": "Rejected"}
