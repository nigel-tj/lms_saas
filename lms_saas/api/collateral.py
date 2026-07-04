"""Collateral management: valuation, loan coverage enforcement, and reporting.

A single ``LMS Collateral`` record is a pledged asset in the security register.
Loans and Loan Applications reference collateral through the ``custom_collateral``
child table (``LMS Loan Collateral``), allowing many-to-many pledging with a
per-loan allocated value.

Coverage enforcement at origination is config-gated via site_config so it can be
switched on per environment without code changes (kept off for seeding/tests):

    lms_require_collateral        (bool)   block submit of an application with no collateral
    lms_min_collateral_coverage   (number) minimum net-realizable / loan-amount ratio (e.g. 1.25)
"""

import frappe
from frappe.utils import flt


def compute_net_realizable_value(market_value, haircut_percent=0, forced_sale_value=0):
    """Realizable security value.

    A forced-sale valuation, when provided, is an independent realizable estimate
    and overrides the haircut model. Otherwise apply the risk haircut to market value.
    """
    if flt(forced_sale_value) > 0:
        return round(flt(forced_sale_value), 2)
    return round(flt(market_value) * (1 - flt(haircut_percent) / 100.0), 2)


def get_collateral_coverage(doc):
    """Return collateral coverage metrics for a Loan / Loan Application doc."""
    rows = doc.get("custom_collateral") or []
    total_realizable = 0.0
    total_allocated = 0.0
    items = []
    for row in rows:
        nrv = (
            flt(frappe.db.get_value("LMS Collateral", row.collateral, "net_realizable_value"))
            if row.collateral
            else 0.0
        )
        allocated = flt(row.allocated_value) or nrv
        total_realizable += nrv
        total_allocated += allocated
        items.append(
            {
                "collateral": row.collateral,
                "collateral_type": row.get("collateral_type"),
                "net_realizable_value": nrv,
                "allocated_value": allocated,
            }
        )

    loan_amount = flt(doc.get("loan_amount"))
    coverage_value = total_allocated or total_realizable
    ratio = round(coverage_value / loan_amount, 4) if loan_amount else 0.0
    return {
        "loan_amount": loan_amount,
        "total_net_realizable_value": round(total_realizable, 2),
        "total_allocated_value": round(total_allocated, 2),
        "coverage_ratio": ratio,
        "items": items,
    }


def enforce_collateral_coverage(doc, method=None):
    """doc_event: validate collateral coverage on a Loan Application before submit."""
    if frappe.flags.in_install or frappe.flags.in_migrate:
        return

    require = frappe.conf.get("lms_require_collateral", False)
    min_cov = frappe.conf.get("lms_min_collateral_coverage")
    rows = doc.get("custom_collateral") or []

    if not rows:
        if require:
            frappe.throw(
                "Collateral is required before this loan application can be submitted. "
                "Add at least one pledged asset in the Collateral table."
            )
        return

    coverage = get_collateral_coverage(doc)

    if min_cov and coverage["coverage_ratio"] < flt(min_cov):
        frappe.throw(
            "Insufficient collateral coverage: net realizable value "
            f"{coverage['total_net_realizable_value']:,.2f} covers only "
            f"{coverage['coverage_ratio']:.2f}x of the loan amount "
            f"{coverage['loan_amount']:,.2f} (minimum required {flt(min_cov):.2f}x)."
        )


def record_collateral_event(doc, method=None):
    """Audit collateral submit/cancel via the compliance audit trail."""
    try:
        from lms_saas.api.compliance import write_audit_event

        write_audit_event(
            event_type=f"{doc.doctype}:{method}",
            reference_doctype=doc.doctype,
            reference_name=doc.name,
            amount=flt(doc.get("net_realizable_value")) or None,
            company=doc.get("company"),
            details=f"type={doc.get('collateral_type')} status={doc.get('status')}",
        )
    except Exception:  # noqa: BLE001 - auditing must not break the business flow
        frappe.log_error(title="LMS collateral audit failed", message=frappe.get_traceback())


@frappe.whitelist()
def get_loan_collateral_summary(doctype, name):
    """Whitelisted: coverage summary for a Loan or Loan Application.

    Permission-scoped: caller must have read access to the referenced document.
    """
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)
    if doctype not in ("Loan", "Loan Application"):
        frappe.throw("Unsupported document type for collateral summary.")

    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    return get_collateral_coverage(doc)
