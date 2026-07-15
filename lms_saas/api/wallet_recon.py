"""Wallet Reconciliation addon API — statement import, auto-match, dashboard.

Uses new LMS Wallet Statement doctype + existing LMS Payment Intent and
LMS Payment Reconciliation.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import today, flt, now_datetime

from lms_saas.utils.addons import require_addon_persona


def _require_recon():
    require_addon_persona("wallet_recon")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@frappe.whitelist()
def import_wallet_statement(lines, company=None):
    """Import statement lines (CSV/JSON) into LMS Wallet Statement records.

    :param lines: JSON string or list of dicts with keys:
        provider_code, statement_date, external_ref, amount, raw_line
    :param company: optional company override
    """
    _require_recon()

    if isinstance(lines, str):
        lines = json.loads(lines)

    if not isinstance(lines, list):
        frappe.throw(_("lines must be a list of statement line dicts."))

    created = []
    for line in lines:
        doc = frappe.new_doc("LMS Wallet Statement")
        doc.provider_code = line.get("provider_code")
        doc.statement_date = line.get("statement_date") or today()
        doc.external_ref = line.get("external_ref")
        doc.amount = flt(line.get("amount") or 0)
        doc.status = "Unmatched"
        doc.raw_line = json.dumps(line) if line.get("raw_line") is None else (
            line["raw_line"] if isinstance(line["raw_line"], str) else json.dumps(line["raw_line"])
        )
        if company:
            doc.company = company
        doc.flags.ignore_permissions = True
        doc.insert()
        created.append(doc.name)

    # Auto-match after import
    matched = auto_match()

    return {
        "imported": len(created),
        "statement_names": created,
        "auto_matched": matched.get("matched", 0),
    }


# ---------------------------------------------------------------------------
# Auto-Match
# ---------------------------------------------------------------------------

@frappe.whitelist()
def auto_match():
    """Match unmatched statement lines to LMS Payment Intent records.

    Matching logic:
      1. Exact match on external_ref (if both have one)
      2. Amount + provider_code match (within tolerance)
    """
    _require_recon()

    unmatched = frappe.get_all(
        "LMS Wallet Statement",
        filters={"status": "Unmatched"},
        fields=["name", "provider_code", "external_ref", "amount"],
    )

    matched_count = 0
    for stmt in unmatched:
        intent = None

        # 1. Match by external_ref
        if stmt.get("external_ref"):
            intent = frappe.db.get_value(
                "LMS Payment Intent",
                {"external_ref": stmt["external_ref"], "status": "Confirmed"},
                "name",
            )

        # 2. Match by amount + provider_code
        if not intent and stmt.get("amount"):
            intent = frappe.db.get_value(
                "LMS Payment Intent",
                {
                    "amount": stmt["amount"],
                    "provider_code": stmt.get("provider_code"),
                    "status": "Confirmed",
                },
                "name",
            )

        if intent:
            frappe.db.set_value("LMS Wallet Statement", stmt["name"], {
                "payment_intent": intent,
                "status": "Matched",
            })
            matched_count += 1

    return {"matched": matched_count, "remaining": len(unmatched) - matched_count}


# ---------------------------------------------------------------------------
# Unmatched
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_unmatched(limit=100):
    """Return unmatched transactions for manual review."""
    _require_recon()

    statements = frappe.get_all(
        "LMS Wallet Statement",
        filters={"status": "Unmatched"},
        fields=["name", "provider_code", "statement_date", "external_ref",
                "amount", "raw_line", "company"],
        order_by="statement_date desc",
        limit_page_length=int(limit),
    )

    # Suggest potential matches (same amount, any provider)
    for stmt in statements:
        suggestions = frappe.get_all(
            "LMS Payment Intent",
            filters={"amount": stmt["amount"], "status": "Confirmed"},
            fields=["name", "loan", "customer", "provider_code", "external_ref"],
            limit=5,
        )
        stmt["suggestions"] = suggestions

    return {"statements": statements}


# ---------------------------------------------------------------------------
# Manual Match
# ---------------------------------------------------------------------------

@frappe.whitelist()
def match_transaction(statement_name, payment_intent):
    """Manually link a statement line to a payment intent."""
    _require_recon()

    # Verify the payment intent exists
    if not frappe.db.exists("LMS Payment Intent", payment_intent):
        frappe.throw(_("Payment Intent not found."))

    frappe.db.set_value("LMS Wallet Statement", statement_name, {
        "payment_intent": payment_intent,
        "status": "Matched",
    })

    return {"ok": True, "statement": statement_name, "payment_intent": payment_intent}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_recon_dashboard():
    """Return matched/unmatched counts and values."""
    _require_recon()

    total = frappe.db.count("LMS Wallet Statement")
    matched = frappe.db.count("LMS Wallet Statement", {"status": "Matched"})
    unmatched = frappe.db.count("LMS Wallet Statement", {"status": "Unmatched"})
    ignored = frappe.db.count("LMS Wallet Statement", {"status": "Ignored"})

    matched_value = flt(frappe.db.sql(
        "SELECT SUM(amount) FROM `tabLMS Wallet Statement` WHERE status='Matched'"
    )[0][0] or 0)

    unmatched_value = flt(frappe.db.sql(
        "SELECT SUM(amount) FROM `tabLMS Wallet Statement` WHERE status='Unmatched'"
    )[0][0] or 0)

    return {
        "total": total,
        "matched": matched,
        "unmatched": unmatched,
        "ignored": ignored,
        "matched_value": matched_value,
        "unmatched_value": unmatched_value,
    }


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_recon_stats():
    """Overview stats for the reconciliation dashboard."""
    _require_recon()

    total_statements = frappe.db.count("LMS Wallet Statement")
    matched = frappe.db.count("LMS Wallet Statement", {"status": "Matched"})
    unmatched = frappe.db.count("LMS Wallet Statement", {"status": "Unmatched"})
    ignored = frappe.db.count("LMS Wallet Statement", {"status": "Ignored"})

    match_rate = round((matched / total_statements * 100), 1) if total_statements else 0

    total_value = flt(frappe.db.sql(
        "SELECT SUM(amount) FROM `tabLMS Wallet Statement`"
    )[0][0] or 0)

    return {
        "total_statements": total_statements,
        "matched": matched,
        "unmatched": unmatched,
        "ignored": ignored,
        "match_rate": match_rate,
        "total_value": total_value,
    }