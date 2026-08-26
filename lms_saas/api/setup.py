"""R52: Operations Manager Setup Portal — API module.

Single server-side entry point for the Operations Manager persona.
Tickets:

- T1 (#46): guard + persona routing. Shipped.
- T2 (#47): Tier A Loan Product draft→approve flow + GL auto-wire.
- T3 (#49): Tier A LMS Credit Policy draft→approve flow.
- T4 (#48): Tier B direct-write endpoints (Loan Purpose, Center, etc.).
- T6 (#51): admin approval surface + verify_spec + perm-sync.

All write endpoints use ``frappe.flags.ignore_permissions = True``
internally — the guard passes first, then the endpoint mutates. The
portal user never needs direct DocPerm on the lending-app doctypes
(Loan Product, etc.) because the lending-app controllers run after the
guard has already verified the persona.

Guard delegation: this module does NOT roll its own persona guard.
It delegates to ``lms_saas.utils.access_control.require_persona`` —
the canonical pattern that replaces the divergent ``_require_manager``
/ ``_require_officer`` copies elsewhere in the codebase. Adding a
fourth copy here would defeat that consolidation.
"""

from __future__ import annotations

import json
from typing import Optional

import frappe
from frappe import _

from lms_saas.lms_saas.doctype.lms_setup_change_request.lms_setup_change_request import (
	STATUS_APPROVED,
	STATUS_APPLIED,
	STATUS_CANCELLED,
	STATUS_PENDING,
	STATUS_PENDING_GL_MISSING,
	STATUS_REJECTED,
)
from lms_saas.utils.access_control import is_admin, require_persona
from lms_saas.utils.loan_product import (
	apply_offset_order_to_product,
	ensure_offset_order,
	missing_gl_accounts,
	resolve_gl_accounts,
)


# The persona string we gate on. Mirrors Employee.custom_lms_persona
# fixture option list + PERSONA_CONFIG.
OPS_PERSONA = "Operations Manager"

# Allowed target_doctype values on a setup change request. Constrained
# here (not on the doctype Select options) so the apply dispatch table
# stays a single dict and the controller has a closed set.
ALLOWED_TARGET_DOCTYPES = ("Loan Product", "LMS Credit Policy")

# The set of business (non-GL) fields an ops manager can edit on a
# Loan Product. GL accounts + offset sequences are admin-owned.
LOAN_PRODUCT_BUSINESS_FIELDS = (
	"product_code",
	"product_name",
	"rate_of_interest",
	"maximum_loan_amount",
	"penalty_interest_rate",
	"grace_period_in_days",
	"is_term_loan",
	"repayment_schedule_type",
	"days_past_due_threshold_for_npa",
	"disabled",
	"loan_category",
	"cyclic_day_of_the_month",
	"repayment_date_on",
)


# ===========================================================================
# Guards
# ===========================================================================


def _require_ops_manager() -> None:
	"""Refuse any user who is not an Operations Manager.

	Admins (System Manager / Administrator) always pass. Loan Officers,
	Branch Managers, Collectors, borrowers, and guests are refused with
	PermissionError. Thin wrapper around ``access_control.require_persona``.
	"""
	require_persona(OPS_PERSONA)


def _require_admin() -> None:
	"""Refuse any user who is not a desk admin.

	Used by ``approve_change_request`` / ``reject_change_request`` /
	``apply_change_request``. Thin wrapper around ``access_control.is_admin``.
	"""
	if not is_admin():
		frappe.throw(
			_("Only System Manager / Administrator can approve setup changes."),
			frappe.PermissionError,
		)


# ===========================================================================
# Audit-event wrappers (Tier A + Tier B)
# ===========================================================================


def _audit_setup_change_proposed(cr_name: str, target: str, change_type: str) -> None:
	"""Informational audit row on draft creation. Best-effort."""
	try:
		from lms_saas.api.compliance import write_audit_event

		write_audit_event(
			event_type="SETUP_CHANGE_PROPOSED",
			reference_doctype="LMS Setup Change Request",
			reference_name=cr_name,
			amount=0,
			company=frappe.db.get_single_value("Global Defaults", "default_company"),
			details={"target_doctype": target, "change_type": change_type},
			critical=False,
		)
	except Exception:
		frappe.log_error(
			title="R52 audit SETUP_CHANGE_PROPOSED failed",
			message=frappe.get_traceback(),
		)


def _audit_setup_change_applied(cr_name: str, target: str, target_name: str,
                                 old: dict, new: dict) -> str:
	"""Critical audit row on apply. Raises on failure so the apply rolls back.

	Returns the audit event name (stored on the change request as
	``audit_event_ref`` for the regulator's evidence trail).
	"""
	from lms_saas.api.compliance import write_audit_event

	# Run as Administrator so the lending-app controllers see a
	# privileged actor on the apply — mirrors the disbursement pattern.
	original_user = frappe.session.user
	frappe.session.user = "Administrator"
	try:
		event_name = write_audit_event(
			event_type="SETUP_CHANGE_APPLIED",
			reference_doctype="LMS Setup Change Request",
			reference_name=cr_name,
			amount=0,
			company=frappe.db.get_single_value("Global Defaults", "default_company"),
			details={
				"target_doctype": target,
				"target_name": target_name,
				"old_values": old,
				"new_values": new,
			},
			critical=True,
		)
	finally:
		frappe.session.user = original_user
	return event_name


def _audit_setup_direct_change(doctype: str, name: str, field: str,
                                old, new) -> None:
	"""Informational audit row for Tier B direct-writes. Best-effort."""
	try:
		from lms_saas.api.compliance import write_audit_event

		write_audit_event(
			event_type="SETUP_DIRECT_CHANGE",
			reference_doctype=doctype,
			reference_name=name,
			amount=0,
			company=frappe.db.get_single_value("Global Defaults", "default_company"),
			details={
				"field": field,
				"old_value": old,
				"new_value": new,
			},
			critical=False,
		)
	except Exception:
		frappe.log_error(
			title="R52 audit SETUP_DIRECT_CHANGE failed",
			message=frappe.get_traceback(),
		)


# ===========================================================================
# Tier A — Loan Product list / get / draft / approve / reject
# (Ticket #47)
# ===========================================================================


@frappe.whitelist()
def list_loan_products() -> dict:
	"""Return all Loan Products with business fields + GL accounts."""
	_require_ops_manager()
	fields = (
		"name", "product_code", "product_name", "company", "disabled",
		"rate_of_interest", "maximum_loan_amount", "penalty_interest_rate",
		"grace_period_in_days", "is_term_loan", "repayment_schedule_type",
		"days_past_due_threshold_for_npa", "loan_category",
		"disbursement_account", "payment_account", "loan_account",
		"interest_income_account", "interest_receivable_account",
		"penalty_income_account", "penalty_receivable_account",
		"interest_accrued_account", "penalty_accrued_account",
	)
	rows = frappe.get_all(
		"Loan Product",
		fields=list(fields),
		order_by="modified desc",
		limit_page_length=200,
	)
	return {"products": rows}


@frappe.whitelist()
def get_loan_product(name: str) -> dict:
	"""Return full detail for a Loan Product (business + GL read-only)."""
	_require_ops_manager()
	if not name or not frappe.db.exists("Loan Product", name):
		frappe.throw(_("Loan Product {0} not found.").format(name))
	doc = frappe.get_doc("Loan Product", name)
	return doc.as_dict()


def _build_loan_product_draft(
	change_type: str,
	fields: dict,
	target_name: Optional[str] = None,
) -> "frappe.model.document.Document":
	"""Common helper for Create / Edit / Disable change requests."""
	# Filter to the allowed business field set so the proposer can't
	# sneak GL account changes through the portal API.
	business_fields = {k: v for k, v in (fields or {}).items() if k in LOAN_PRODUCT_BUSINESS_FIELDS}
	disallowed = set((fields or {}).keys()) - set(LOAN_PRODUCT_BUSINESS_FIELDS)
	if disallowed:
		frappe.throw(
			_(
				"Loan Product draft cannot carry these fields "
				"(admin-only): {0}"
			).format(", ".join(sorted(disallowed))),
			frappe.PermissionError,
		)

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		frappe.throw(_("No default company configured."))

	# Edit / Disable: snapshot the existing Loan Product's state.
	old_values: dict = {}
	status = STATUS_PENDING
	gl_notes: Optional[str] = None

	if change_type in ("Edit", "Disable"):
		if not target_name or not frappe.db.exists("Loan Product", target_name):
			frappe.throw(
				_("target_name is required for {0} and must exist.").format(change_type)
			)
		existing = frappe.get_doc("Loan Product", target_name)
		for f in LOAN_PRODUCT_BUSINESS_FIELDS:
			old_values[f] = existing.get(f)
		if change_type == "Disable":
			business_fields = {"disabled": 1}

	# Create: auto-wire GL accounts + offset sequences.
	proposed_fields = dict(business_fields)
	if change_type == "Create":
		accounts = resolve_gl_accounts(company)
		order_name = ensure_offset_order(company)
		if accounts:
			for k, v in accounts.items():
				proposed_fields.setdefault(k, v)
		else:
			missing = missing_gl_accounts(None)
			gl_notes = (
				"Required GL accounts are missing on the Chart of Accounts: "
				+ ", ".join(missing)
				+ ". An administrator must complete the wiring on the desk "
				"before this change request can be applied."
			)
			status = STATUS_PENDING_GL_MISSING

	cr = frappe.get_doc(
		{
			"doctype": "LMS Setup Change Request",
			"target_doctype": "Loan Product",
			"target_name": target_name or "",
			"change_type": change_type,
			"status": status,
			"proposed_fields": frappe.as_json(proposed_fields) if proposed_fields else "",
			"old_values": frappe.as_json(old_values) if old_values else "",
			"gl_wiring_notes": gl_notes or "",
		}
	)
	cr.flags.ignore_permissions = True
	cr.insert()
	_audit_setup_change_proposed(cr.name, "Loan Product", change_type)
	return cr


@frappe.whitelist()
def create_loan_product_draft(
	product_code: str,
	product_name: str,
	rate_of_interest: float,
	maximum_loan_amount: float,
	**kwargs,
) -> dict:
	"""Create a draft change request to add a new Loan Product."""
	_require_ops_manager()
	fields = {
		"product_code": product_code,
		"product_name": product_name,
		"rate_of_interest": rate_of_interest,
		"maximum_loan_amount": maximum_loan_amount,
	}
	# Pass-through optional fields. Whitelist in LOAN_PRODUCT_BUSINESS_FIELDS.
	for k in (
		"penalty_interest_rate",
		"grace_period_in_days",
		"is_term_loan",
		"repayment_schedule_type",
		"days_past_due_threshold_for_npa",
		"loan_category",
		"cyclic_day_of_the_month",
		"repayment_date_on",
	):
		if k in kwargs and kwargs[k] not in (None, ""):
			fields[k] = kwargs[k]

	cr = _build_loan_product_draft(change_type="Create", fields=fields)
	return {"change_request": cr.name, "status": cr.status}


@frappe.whitelist()
def edit_loan_product_draft(name: str, fields: dict | str) -> dict:
	"""Create a draft change request to edit an existing Loan Product."""
	_require_ops_manager()
	if isinstance(fields, str):
		fields = json.loads(fields)
	cr = _build_loan_product_draft(
		change_type="Edit", fields=fields or {}, target_name=name
	)
	return {"change_request": cr.name, "status": cr.status}


@frappe.whitelist()
def disable_loan_product_draft(name: str) -> dict:
	"""Create a draft change request to disable a Loan Product."""
	_require_ops_manager()
	cr = _build_loan_product_draft(change_type="Disable", fields={}, target_name=name)
	return {"change_request": cr.name, "status": cr.status}


@frappe.whitelist()
def list_change_requests(status: str | None = None) -> dict:
	"""List change requests, optionally filtered by status."""
	_require_ops_manager()
	filters = {}
	if status:
		filters["status"] = status
	rows = frappe.get_all(
		"LMS Setup Change Request",
		filters=filters,
		fields=[
			"name", "target_doctype", "target_name", "change_type",
			"status", "requested_by", "requested_at", "approved_by",
			"approved_at", "applied_at", "rejection_reason",
			"audit_event_ref", "gl_wiring_notes",
		],
		order_by="creation desc",
		limit_page_length=200,
	)
	return {"change_requests": rows}


@frappe.whitelist()
def cancel_change_request(name: str) -> dict:
	"""The ops manager cancels their own pending change request."""
	_require_ops_manager()
	if not name or not frappe.db.exists("LMS Setup Change Request", name):
		frappe.throw(_("Change request {0} not found.").format(name))
	cr = frappe.get_doc("LMS Setup Change Request", name)
	if cr.requested_by != frappe.session.user:
		frappe.throw(
			_("Only the requester can cancel this change request."),
			frappe.PermissionError,
		)
	if cr.status not in (STATUS_PENDING, STATUS_PENDING_GL_MISSING):
		frappe.throw(
			_("Change request is already {0}; cannot cancel.").format(cr.status)
		)
	cr.status = STATUS_CANCELLED
	cr.flags.ignore_permissions = True
	cr.save()
	return {"change_request": cr.name, "status": cr.status}


def _apply_loan_product(cr) -> str:
	"""Apply an Edit / Disable / Create change request onto the live
	Loan Product. Returns the target_name of the new or updated product.

	Runs the lending-app controllers as Administrator so the loan
	product can be saved without the ops manager having direct DocPerm
	on the lending doctype. The GL auto-wire is already embedded in the
	proposed_fields (see _build_loan_product_draft).
	"""
	proposed = cr.get_proposed_fields()
	original_user = frappe.session.user
	frappe.session.user = "Administrator"
	try:
		if cr.change_type == "Create":
			if not proposed.get("product_code"):
				frappe.throw("Create change request missing product_code")
			existing = frappe.db.exists(
				"Loan Product",
				{"product_code": proposed["product_code"]},
			)
			if existing:
				frappe.throw(
					f"Loan Product {proposed['product_code']!r} already exists"
				)
			doc = frappe.get_doc({"doctype": "Loan Product", **proposed})
			doc.flags.ignore_permissions = True
			doc.insert()
			target_name = doc.name
		elif cr.change_type in ("Edit", "Disable"):
			doc = frappe.get_doc("Loan Product", cr.target_name)
			for k, v in proposed.items():
				if k == "disabled" and cr.change_type == "Disable":
					doc.set(k, 1)
				else:
					doc.set(k, v)
			doc.flags.ignore_permissions = True
			doc.save()
			target_name = doc.name
		else:
			frappe.throw(f"Unknown change_type: {cr.change_type!r}")
	finally:
		frappe.session.user = original_user
	return target_name


def _apply_change_request(cr_name: str) -> dict:
	"""Apply a change request by dispatching on target_doctype.

	Shared by ``approve_change_request`` and (T6) the desk apply path.
	Returns the apply summary; raises on failure (the caller is
	responsible for catching + rolling back if needed).
	"""
	cr = frappe.get_doc("LMS Setup Change Request", cr_name)
	old = cr.get_old_values()
	if cr.target_doctype == "Loan Product":
		target_name = _apply_loan_product(cr)
	else:
		frappe.throw(
			f"Apply not implemented for target_doctype={cr.target_doctype!r}"
		)
	# Critical audit row (raises on failure).
	event_name = _audit_setup_change_applied(
		cr_name=cr.name,
		target=cr.target_doctype,
		target_name=target_name,
		old=old,
		new=cr.get_proposed_fields(),
	)
	return {
		"change_request": cr.name,
		"target_name": target_name,
		"audit_event": event_name,
	}


@frappe.whitelist()
def approve_change_request(name: str) -> dict:
	"""Admin approves + applies a Tier A change request."""
	_require_admin()
	if not name or not frappe.db.exists("LMS Setup Change Request", name):
		frappe.throw(_("Change request {0} not found.").format(name))
	cr = frappe.get_doc("LMS Setup Change Request", name)
	if cr.status not in (STATUS_PENDING, STATUS_PENDING_GL_MISSING):
		frappe.throw(
			_("Cannot approve a change request in status {0}.").format(cr.status)
		)
	if cr.status == STATUS_PENDING_GL_MISSING and not (cr.gl_wiring_notes or "").strip():
		frappe.throw(
			_(
				"Cannot approve: change request is flagged Pending — Missing "
				"GL Accounts but no wiring notes. An admin must complete the "
				"GL wiring on the desk first."
			)
		)

	# Stamp approved_by / approved_at before apply.
	cr.approved_by = frappe.session.user
	cr.approved_at = frappe.utils.now_datetime()
	cr.status = STATUS_APPROVED
	cr.flags.ignore_permissions = True
	cr.save()

	# Apply + audit. If the apply fails, the savepoint rolls back so
	# the change request is left in Approved (not Applied) — admin can
	# investigate.
	try:
		summary = _apply_change_request(name)
	except Exception:
		frappe.db.rollback()
		raise

	# Re-fetch + stamp Applied.
	cr = frappe.get_doc("LMS Setup Change Request", name)
	cr.status = STATUS_APPLIED
	cr.applied_at = frappe.utils.now_datetime()
	cr.audit_event_ref = summary["audit_event"]
	cr.flags.ignore_permissions = True
	cr.save()
	return summary


@frappe.whitelist()
def reject_change_request(name: str, reason: str = "") -> dict:
	"""Admin rejects a Tier A change request with a reason."""
	_require_admin()
	if not reason or not reason.strip():
		frappe.throw(_("Rejection reason is required."))
	if not name or not frappe.db.exists("LMS Setup Change Request", name):
		frappe.throw(_("Change request {0} not found.").format(name))
	cr = frappe.get_doc("LMS Setup Change Request", name)
	if cr.status not in (STATUS_PENDING, STATUS_PENDING_GL_MISSING):
		frappe.throw(
			_("Cannot reject a change request in status {0}.").format(cr.status)
		)
	cr.status = STATUS_REJECTED
	cr.approved_by = frappe.session.user
	cr.approved_at = frappe.utils.now_datetime()
	cr.rejection_reason = reason
	cr.flags.ignore_permissions = True
	cr.save()
	return {"change_request": cr.name, "status": cr.status}


# ===========================================================================
# Tier B — direct-write endpoints (Ticket #48)
# ===========================================================================
#
# Each write writes a SETUP_DIRECT_CHANGE audit event with the
# before/after diff. The ops manager is the only persona allowed (the
# ``_require_ops_manager`` guard refuses Loan Officers, Branch
# Managers, Collectors, borrowers, and guests).


def _direct_write(
	doctype: str,
	doc_name: str,
	operation: str,
	field: str,
	old,
	new,
) -> None:
	"""Run the doc save + write the SETUP_DIRECT_CHANGE audit row."""
	_audit_setup_direct_change(
		doctype=doctype, name=doc_name, field=field, old=old, new=new
	)


@frappe.whitelist()
def list_loan_purposes() -> dict:
	_require_ops_manager()
	rows = frappe.get_all(
		"Loan Purpose",
		fields=["name", "loan_purpose"],
		order_by="loan_purpose asc",
		limit_page_length=200,
	)
	return {"purposes": rows}


@frappe.whitelist()
def create_loan_purpose(name: str) -> dict:
	_require_ops_manager()
	if not name or not name.strip():
		frappe.throw(_("Loan Purpose name is required."))
	if frappe.db.exists("Loan Purpose", name.strip()):
		frappe.throw(_("Loan Purpose {0} already exists.").format(name))
	doc = frappe.get_doc({"doctype": "Loan Purpose", "loan_purpose": name.strip()})
	doc.flags.ignore_permissions = True
	doc.insert()
	_direct_write(
		doctype="Loan Purpose", doc_name=name.strip(),
		operation="create", field="loan_purpose", old=None, new=name.strip(),
	)
	return {"purpose": name.strip()}


@frappe.whitelist()
def edit_loan_purpose(name: str, new_name: str) -> dict:
	_require_ops_manager()
	if not new_name or not new_name.strip():
		frappe.throw(_("New name is required."))
	if not frappe.db.exists("Loan Purpose", name):
		frappe.throw(_("Loan Purpose {0} not found.").format(name))
	if frappe.db.exists("Loan Purpose", new_name.strip()) and name != new_name.strip():
		frappe.throw(_("Loan Purpose {0} already exists.").format(new_name))
	# Loan Purpose's autoname is `field:loan_purpose` — the doc's name
	# IS the loan_purpose value, so we use frappe.rename_doc.
	from frappe.model.rename_doc import rename_doc as _rename_doc
	_rename_doc(
		doctype="Loan Purpose",
		old=name,
		new=new_name.strip(),
		ignore_permissions=True,
		show_alert=False,
	)
	_direct_write(
		doctype="Loan Purpose", doc_name=new_name.strip(),
		operation="rename", field="loan_purpose", old=name, new=new_name.strip(),
	)
	return {"purpose": new_name.strip()}


@frappe.whitelist()
def disable_loan_purpose(name: str) -> dict:
	"""No-op for the standard Loan Purpose doctype (which has no enabled
	flag). Kept as an API shape so the Tier B tabs have a uniform
	interface; the change request model is the disable mechanism."""
	_require_ops_manager()
	if not frappe.db.exists("Loan Purpose", name):
		frappe.throw(_("Loan Purpose {0} not found.").format(name))
	return {"purpose": name, "status": "ok"}


@frappe.whitelist()
def list_centers() -> dict:
	_require_ops_manager()
	rows = frappe.get_all(
		"LMS Center",
		fields=["name", "center_name", "branch", "company", "field_officer"],
		order_by="center_name asc",
		limit_page_length=200,
	)
	return {"centers": rows}


@frappe.whitelist()
def create_center(center_name: str, branch: str | None = None) -> dict:
	_require_ops_manager()
	if not center_name or not center_name.strip():
		frappe.throw(_("Center name is required."))
	if frappe.db.exists("LMS Center", {"center_name": center_name.strip()}):
		frappe.throw(_("LMS Center {0} already exists.").format(center_name))
	company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
	doc = frappe.get_doc({
		"doctype": "LMS Center",
		"center_name": center_name.strip(),
		"branch": branch or "",
		"company": company,
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	_direct_write(
		doctype="LMS Center", doc_name=center_name.strip(),
		operation="create", field="center_name", old=None, new=center_name.strip(),
	)
	return {"center": center_name.strip()}


@frappe.whitelist()
def edit_center(name: str, center_name: str | None = None, branch: str | None = None) -> dict:
	_require_ops_manager()
	if not frappe.db.exists("LMS Center", name):
		frappe.throw(_("LMS Center {0} not found.").format(name))
	doc = frappe.get_doc("LMS Center", name)
	before = {"center_name": doc.center_name, "branch": doc.branch or ""}
	if center_name is not None:
		doc.center_name = center_name.strip()
	if branch is not None:
		doc.branch = branch
	doc.flags.ignore_permissions = True
	doc.save()
	_direct_write(
		doctype="LMS Center", doc_name=name,
		operation="edit", field="center_name,branch",
		old=before,
		new={"center_name": doc.center_name, "branch": doc.branch or ""},
	)
	return {"center": name}


@frappe.whitelist()
def list_lending_groups() -> dict:
	_require_ops_manager()
	rows = frappe.get_all(
		"LMS Lending Group",
		fields=["name", "group_name", "center", "branch", "company", "status"],
		order_by="group_name asc",
		limit_page_length=200,
	)
	return {"groups": rows}


@frappe.whitelist()
def create_lending_group(
	group_name: str,
	center: str | None = None,
	branch: str | None = None,
) -> dict:
	_require_ops_manager()
	if not group_name or not group_name.strip():
		frappe.throw(_("Lending group name is required."))
	if frappe.db.exists("LMS Lending Group", {"group_name": group_name.strip()}):
		frappe.throw(_("LMS Lending Group {0} already exists.").format(group_name))
	company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
	doc = frappe.get_doc({
		"doctype": "LMS Lending Group",
		"group_name": group_name.strip(),
		"center": center or "",
		"branch": branch or "",
		"company": company,
		"status": "Active",
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	_direct_write(
		doctype="LMS Lending Group", doc_name=group_name.strip(),
		operation="create", field="group_name", old=None, new=group_name.strip(),
	)
	return {"group": group_name.strip()}


@frappe.whitelist()
def edit_lending_group(
	name: str,
	group_name: str | None = None,
	center: str | None = None,
	branch: str | None = None,
	status: str | None = None,
) -> dict:
	_require_ops_manager()
	if not frappe.db.exists("LMS Lending Group", name):
		frappe.throw(_("LMS Lending Group {0} not found.").format(name))
	doc = frappe.get_doc("LMS Lending Group", name)
	before = {
		"group_name": doc.group_name, "center": doc.center or "",
		"branch": doc.branch or "", "status": doc.status,
	}
	if group_name is not None:
		doc.group_name = group_name.strip()
	if center is not None:
		doc.center = center
	if branch is not None:
		doc.branch = branch
	if status is not None:
		doc.status = status
	doc.flags.ignore_permissions = True
	doc.save()
	_direct_write(
		doctype="LMS Lending Group", doc_name=name,
		operation="edit", field="lending_group_fields",
		old=before,
		new={
			"group_name": doc.group_name, "center": doc.center or "",
			"branch": doc.branch or "", "status": doc.status,
		},
	)
	return {"group": name}


@frappe.whitelist()
def list_announcements() -> dict:
	_require_ops_manager()
	rows = frappe.get_all(
		"LMS Announcement",
		fields=[
			"name", "title", "target_section", "target_persona",
			"publish_date", "expiry_date", "status",
		],
		order_by="publish_date desc, modified desc",
		limit_page_length=200,
	)
	return {"announcements": rows}


@frappe.whitelist()
def create_announcement(
	title: str,
	body: str = "",
	target_section: str | None = None,
	target_persona: str | None = None,
	target_branch: str | None = None,
) -> dict:
	_require_ops_manager()
	if not title or not title.strip():
		frappe.throw(_("Announcement title is required."))
	doc = frappe.get_doc({
		"doctype": "LMS Announcement",
		"title": title.strip(),
		"body": body or "",
		"target_section": target_section or "",
		"target_persona": target_persona or "",
		"target_branch": target_branch or "",
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	_direct_write(
		doctype="LMS Announcement", doc_name=title.strip(),
		operation="create", field="title", old=None, new=title.strip(),
	)
	return {"announcement": title.strip()}


@frappe.whitelist()
def edit_announcement(
	name: str,
	title: str | None = None,
	body: str | None = None,
	status: str | None = None,
) -> dict:
	_require_ops_manager()
	if not frappe.db.exists("LMS Announcement", name):
		frappe.throw(_("LMS Announcement {0} not found.").format(name))
	doc = frappe.get_doc("LMS Announcement", name)
	before = {"title": doc.title, "body": doc.body or "", "status": doc.status}
	if title is not None:
		doc.title = title.strip()
	if body is not None:
		doc.body = body
	if status is not None:
		doc.status = status
	doc.flags.ignore_permissions = True
	doc.save()
	_direct_write(
		doctype="LMS Announcement", doc_name=name,
		operation="edit", field="announcement_fields",
		old=before,
		new={"title": doc.title, "body": doc.body or "", "status": doc.status},
	)
	return {"announcement": name}


@frappe.whitelist()
def list_document_categories() -> dict:
	_require_ops_manager()
	rows = frappe.get_all(
		"LMS Document Category",
		fields=["name", "category_name", "description"],
		order_by="category_name asc",
		limit_page_length=200,
	)
	return {"categories": rows}


@frappe.whitelist()
def create_document_category(
	category_name: str,
	description: str = "",
) -> dict:
	_require_ops_manager()
	if not category_name or not category_name.strip():
		frappe.throw(_("Document category name is required."))
	if frappe.db.exists("LMS Document Category", {"category_name": category_name.strip()}):
		frappe.throw(
			_("LMS Document Category {0} already exists.").format(category_name)
		)
	doc = frappe.get_doc({
		"doctype": "LMS Document Category",
		"category_name": category_name.strip(),
		"description": description or "",
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	_direct_write(
		doctype="LMS Document Category", doc_name=category_name.strip(),
		operation="create", field="category_name", old=None, new=category_name.strip(),
	)
	return {"category": category_name.strip()}


@frappe.whitelist()
def edit_document_category(
	name: str,
	category_name: str | None = None,
	description: str | None = None,
) -> dict:
	_require_ops_manager()
	if not frappe.db.exists("LMS Document Category", name):
		frappe.throw(_("LMS Document Category {0} not found.").format(name))
	doc = frappe.get_doc("LMS Document Category", name)
	before = {"category_name": doc.category_name, "description": doc.description or ""}
	if category_name is not None:
		doc.category_name = category_name.strip()
	if description is not None:
		doc.description = description
	doc.flags.ignore_permissions = True
	doc.save()
	_direct_write(
		doctype="LMS Document Category", doc_name=name,
		operation="edit", field="category_fields",
		old=before,
		new={"category_name": doc.category_name, "description": doc.description or ""},
	)
	return {"category": name}


@frappe.whitelist()
def list_payment_providers() -> dict:
	_require_ops_manager()
	rows = frappe.get_all(
		"LMS Payment Provider",
		fields=["name", "provider_code", "provider_name", "enabled", "api_url", "merchant_id"],
		order_by="provider_name asc",
		limit_page_length=200,
	)
	return {"providers": rows}


@frappe.whitelist()
def toggle_payment_provider(name: str, enabled: bool | int = 1) -> dict:
	_require_ops_manager()
	if not frappe.db.exists("LMS Payment Provider", name):
		frappe.throw(_("LMS Payment Provider {0} not found.").format(name))
	before = int(frappe.db.get_value("LMS Payment Provider", name, "enabled") or 0)
	after = 1 if int(enabled) else 0
	frappe.db.set_value("LMS Payment Provider", name, "enabled", after)
	_direct_write(
		doctype="LMS Payment Provider", doc_name=name,
		operation="toggle", field="enabled", old=before, new=after,
	)
	return {"provider": name, "enabled": after}
