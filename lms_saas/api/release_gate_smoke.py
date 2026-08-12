"""Release-gate smoke (R06) — GL / audit dump for human auditor review.

A non-destructive ``bench execute`` entry point that prints a JSON report
of the last N disbursements, repayments, and write-offs with their GL
entries. The agent does NOT assert correctness on money — that is the
human accountant's job (gate row 8.2).
"""

from __future__ import annotations

import json

import frappe


def run_all(limit: int = 5) -> dict:
    """Print a JSON report of the last N money movements + their GL entries.

    Usage::

        bench --site <site> execute lms_saas.api.release_gate_smoke.run_all
    """
    report = {
        "generated_at": frappe.utils.now(),
        "site": frappe.local.site,
        "disbursements": _last_disbursements(limit),
        "repayments": _last_repayments(limit),
        "write_offs": _last_write_offs(limit),
        "audit_events": _last_audit_events(limit * 2),
    }
    print(json.dumps(report, indent=2, default=str))
    return report


def _last_disbursements(limit: int) -> list:
    rows = frappe.get_all(
        "Loan Disbursement",
        fields=["name", "against_loan", "disbursed_amount", "posting_date", "docstatus"],
        order_by="creation desc",
        limit=limit,
    )
    for r in rows:
        r["gl_entries"] = frappe.get_all(
            "GL Entry",
            filters={"voucher_type": "Loan Disbursement", "voucher_no": r["name"]},
            fields=["account", "debit", "credit"],
        )
    return rows


def _last_repayments(limit: int) -> list:
    rows = frappe.get_all(
        "Loan Repayment",
        fields=["name", "against_loan", "amount_paid", "posting_date", "docstatus"],
        order_by="creation desc",
        limit=limit,
    )
    for r in rows:
        r["gl_entries"] = frappe.get_all(
            "GL Entry",
            filters={"voucher_type": "Loan Repayment", "voucher_no": r["name"]},
            fields=["account", "debit", "credit"],
        )
    return rows


def _last_write_offs(limit: int) -> list:
    if not frappe.db.exists("DocType", "Loan Write Off"):
        return []
    try:
        rows = frappe.get_all(
            "Loan Write Off",
            fields=["name", "against_loan", "write_off_amount", "posting_date", "docstatus"],
            order_by="creation desc",
            limit=limit,
        )
    except Exception:
        return []
    for r in rows:
        r["gl_entries"] = frappe.get_all(
            "GL Entry",
            filters={"voucher_type": "Loan Write Off", "voucher_no": r["name"]},
            fields=["account", "debit", "credit"],
        )
    return rows


def _last_audit_events(limit: int) -> list:
    if not frappe.db.exists("DocType", "LMS Audit Event"):
        return []
    return frappe.get_all(
        "LMS Audit Event",
        fields=["name", "event_type", "reference_doctype", "reference_name", "amount", "creation"],
        order_by="creation desc",
        limit=limit,
    )
