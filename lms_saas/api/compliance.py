"""RBZ Fintech Sandbox compliance controls.

Implements audit logging, maker-checker (four-eyes), origination limits /
consent / sandbox-window enforcement, and the weekly sandbox KPI report.

Enforcement controls are config-gated via site_config so they can be switched
on per environment without code changes (and kept off for automated seeding):
    lms_enforce_four_eyes      (bool)  maker != checker on disbursement/write-off
    lms_require_consent        (bool)  borrower consent required before origination
    lms_max_loan_amount        (number) per-loan transaction cap
    lms_max_active_customers   (number) volunteer customer cap
    lms_sandbox_end_date       (date)  testing window end (<=24 months, RBZ 3.32)
"""

import frappe
from frappe.utils import add_days, cint, flt, getdate, now_datetime, today

MONEY_DOCTYPES = ("Loan", "Loan Disbursement", "Loan Repayment", "Loan Write Off", "LMS Investor Transaction")


# ---------------------------------------------------------------------------
# Audit trail (Annex 5.1)
# ---------------------------------------------------------------------------

def write_audit_event(event_type, reference_doctype, reference_name, amount=None, company=None, details=None, critical=False):
	"""Append an immutable audit event.

	If ``critical=True`` (used for money-movement events: disbursement,
	write-off, repayment, approval), a failure to write the audit row
	**raises** — rolling back the business transaction. For a regulated
	microfinance system, a disbursement with no audit evidence is a
	reportable incident; we refuse to commit the business op if the
	audit trail cannot be written.

	If ``critical=False`` (default — used for non-money events like
	customer updates), the failure is logged but does not break the
	business flow.
	"""
	try:
		frappe.get_doc(
			{
				"doctype": "LMS Audit Event",
				"event_time": now_datetime(),
				"event_type": event_type,
				"event_user": frappe.session.user,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"amount": amount,
				"company": company,
				"details": details,
			}
		).insert(ignore_permissions=True)
	except Exception:  # noqa: BLE001
		try:
			frappe.log_error(title="LMS audit event failed", message=frappe.get_traceback())
		except Exception:
			pass  # log_error itself failed — can't do much
		if critical:
			raise  # roll back the business transaction — no audit = no commit


def record_money_event(doc, method):
    """doc_event hook: record submit/cancel of money-movement documents."""
    amount = (
        getattr(doc, "disbursed_amount", None)
        or getattr(doc, "amount_paid", None)
        or getattr(doc, "amount", None)
        or getattr(doc, "loan_amount", None)
    )
    write_audit_event(
        event_type=f"{doc.doctype}:{method}",
        reference_doctype=doc.doctype,
        reference_name=doc.name,
        amount=flt(amount) if amount else None,
        company=getattr(doc, "company", None),
        details=f"status={getattr(doc, 'status', None)}",
        critical=True,  # P0 fix: money-movement events must roll back on audit failure
    )


# ---------------------------------------------------------------------------
# Four-eyes / maker-checker (Annex 5.1)
# ---------------------------------------------------------------------------

def enforce_four_eyes(doc, method):
	"""High-impact actions require a different approver than the maker."""
	if not frappe.conf.get("lms_enforce_four_eyes", False):
		# Warn loudly when four-eyes is off in a production-like deployment.
		# Use logger, not log_error, to avoid flooding the Error Log with config warnings.
		if not frappe.conf.get("lms_sandbox_end_date"):
			frappe.logger("lms_compliance").warning(
				f"User {frappe.session.user} submitted {doc.doctype} {doc.name} with no maker-checker."
			)
		return
	if frappe.flags.in_install or frappe.flags.in_migrate:
		return
	if doc.owner and frappe.session.user == doc.owner:
		frappe.throw(
			f"Four-eyes control: the maker ({doc.owner}) cannot approve their own "
			f"{doc.doctype}. A second authorised user must submit it."
		)


# ---------------------------------------------------------------------------
# Origination controls: limits, consent, sandbox window (Annex 4.5, 3.19, 3.32)
# ---------------------------------------------------------------------------

def enforce_origination_controls(doc, method):
    """Validate a Loan Application against configured sandbox boundaries."""
    end_date = frappe.conf.get("lms_sandbox_end_date")
    if end_date and getdate(today()) > getdate(end_date):
        frappe.throw("Sandbox testing window has ended. New originations are not permitted.")

    max_amount = frappe.conf.get("lms_max_loan_amount")
    if max_amount and flt(doc.loan_amount) > flt(max_amount):
        frappe.throw(
            f"Loan amount {flt(doc.loan_amount)} exceeds the sandbox transaction limit ({flt(max_amount)})."
        )

    if frappe.conf.get("lms_require_consent", False):
        consent = frappe.db.get_value(
            "LMS Borrower Compliance", {"customer": doc.applicant}, "consent_given"
        )
        if not consent:
            frappe.throw(
                "Customer consent is required before origination (RBZ Sandbox 3.19). "
                "Record consent on the borrower's LMS Borrower Compliance profile."
            )

    max_customers = frappe.conf.get("lms_max_active_customers")
    if max_customers:
        active = frappe.get_all(
            "Loan",
            filters={"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
            distinct=True,
            pluck="applicant",
        )
        existing = set(active)
        if doc.applicant not in existing and len(existing) >= int(max_customers):
            frappe.throw(
                f"Volunteer customer cap ({int(max_customers)}) reached for the sandbox test."
            )


# ---------------------------------------------------------------------------
# Weekly sandbox KPI report (Annex 5.1)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_sandbox_report(days=7):
	"""Return the metrics required for the RBZ weekly sandbox progress report."""
	# Role check — restrict to admin only (P1 fix: sandbox report is system-wide regulatory data).
	roles = set(frappe.get_roles())
	if not roles.intersection({"System Manager", "Administrator"}):
		frappe.throw("Not permitted", frappe.PermissionError)

	# Sanitize days parameter (P1 fix).
	days = max(1, min(cint(days), 365))
	since = add_days(today(), -int(days))

	active_customers = frappe.get_all(
		"Loan",
		filters={"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
		distinct=True,
		pluck="applicant",
	)

	disbursements = frappe.get_all(
		"Loan Disbursement",
		filters={"docstatus": 1, "posting_date": (">=", since)},
		fields=["count(name) as count", "sum(disbursed_amount) as value"],
	)[0]
	repayments = frappe.get_all(
		"Loan Repayment",
		filters={"docstatus": 1, "posting_date": (">=", since)},
		fields=["count(name) as count", "sum(amount_paid) as value"],
	)[0]

	incidents = frappe.get_all(
		"LMS Incident Log",
		filters={"reported_on": (">=", since)},
		fields=["name", "incident_type", "severity", "status", "title"],
		order_by="reported_on desc",
	)
	complaints = [i for i in incidents if i.incident_type == "Customer Complaint"]
	open_incidents = [i for i in incidents if i.status in ("Open", "Investigating")]

	audit_events = frappe.db.count("LMS Audit Event", {"event_time": (">=", since)})

	return {
		"period_days": int(days),
		"since": str(since),
		"volunteer_customers": len(active_customers),
		"transactions": {
			"disbursements_count": disbursements.count or 0,
			"disbursements_value": flt(disbursements.value),
			"repayments_count": repayments.count or 0,
			"repayments_value": flt(repayments.value),
		},
		"incidents_open": len(open_incidents),
		"complaints": len(complaints),
		"incident_log": incidents,
		"audit_events": audit_events,
	}
