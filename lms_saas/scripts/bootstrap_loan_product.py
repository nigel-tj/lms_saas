#!/usr/bin/env python3
"""Bootstrap the LMS Standard Loan Product on a fresh Frappe Cloud site.

On a brand-new Frappe Cloud bench the `lms_saas` app is installed but
`after_install()` may not have run (or ran before the Chart of Accounts
was set up). The result is the manager / officer portals show "No loan
products available" and no loan application can be submitted.

This script is a **targeted, idempotent** fix: it ensures the Chart of
Accounts has the GL accounts the Loan Product needs, then creates the
`LMS-STD` Loan Product if it doesn't already exist. It does NOT seed
demo borrowers, loan applications, or any other demo data — safe to run
on a production site.

USAGE:
  bench --site <site> execute lms_saas.scripts.bootstrap_loan_product.run
  # or with a bench console:
  bench --site <site> console
  >>> from lms_saas.scripts.bootstrap_loan_product import run
  >>> run()

FLAGS:
  --dry-run   Preview what would be created without writing anything.
"""
from __future__ import annotations

import frappe

# The lending app (v15+) requires a Loan Demand Offset Order linked to
# both the Company and the Loan Product. Without it, the lending
# controller's validate_demand_offset_sequences() throws on insert.
# This is the standard offset order: Penalty → Interest → Principal.
OFFSET_ORDER_TITLE = "Standard Loan Demand Offset Order"
OFFSET_COMPONENTS = [
    {"demand_type": "Penalty"},
    {"demand_type": "Interest"},
    {"demand_type": "Principal"},
]

DEFAULT_LOAN_PURPOSES = (
    "Business Expansion",
    "Working Capital",
    "Inventory Purchase",
    "Equipment Purchase",
    "Education",
    "Home Improvement",
    "Emergency / Medical",
    "Debt Consolidation",
    "Agriculture / Farming",
    "Transport / Vehicle",
)


def _ensure_offset_order() -> str:
    """Create the Loan Demand Offset Order if it doesn't exist. Returns name."""
    existing = frappe.db.exists("Loan Demand Offset Order", {"title": OFFSET_ORDER_TITLE})
    if existing:
        return existing
    doc = frappe.get_doc({
        "doctype": "Loan Demand Offset Order",
        "title": OFFSET_ORDER_TITLE,
        "components": OFFSET_COMPONENTS,
    })
    doc.insert(ignore_permissions=True)
    return doc.name


def _ensure_loan_purposes() -> int:
    """Seed default Loan Purpose records. Returns count created."""
    count = 0
    for name in DEFAULT_LOAN_PURPOSES:
        if not frappe.db.exists("Loan Purpose", name):
            frappe.get_doc({
                "doctype": "Loan Purpose",
                "loan_purpose": name,
            }).insert(ignore_permissions=True)
            count += 1
    return count


def _ensure_company_offset_sequences(company: str, order_name: str) -> None:
    """Set the offset sequence fields on the Company via direct DB write.

    Uses frappe.db.set_value to bypass the Company controller's link
    validation (which would re-validate the entire Company doc and may
    fail on unrelated missing fields).
    """
    fields = [
        "collection_offset_sequence_for_standard_asset",
        "collection_offset_sequence_for_sub_standard_asset",
        "collection_offset_sequence_for_written_off_asset",
        "collection_offset_sequence_for_settlement_collection",
    ]
    for field in fields:
        current = frappe.db.get_value("Company", company, field)
        if not current:
            frappe.db.set_value("Company", company, field, order_name)


def _ensure_product_offset_sequences(product_name: str, order_name: str) -> None:
    """Set the offset sequence fields on the Loan Product via direct DB write."""
    fields = [
        "collection_offset_sequence_for_standard_asset",
        "collection_offset_sequence_for_sub_standard_asset",
        "collection_offset_sequence_for_written_off_asset",
        "collection_offset_sequence_for_settlement_collection",
    ]
    for field in fields:
        current = frappe.db.get_value("Loan Product", product_name, field)
        if not current:
            frappe.db.set_value("Loan Product", product_name, field, order_name)


def run(*, dry_run: bool = False) -> dict:
    """Ensure the LMS-STD Loan Product exists for the default company.

    Returns a summary dict describing what was done.
    """
    summary: dict = {
        "company": None,
        "product_exists": False,
        "product_created": False,
        "accounts_resolved": {},
        "accounts_missing": [],
        "after_install_ran": False,
        "offset_order_created": False,
        "offset_order_name": None,
        "company_offset_set": False,
        "product_offset_set": False,
        "dry_run": dry_run,
    }

    company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
        "Company", {}, "name"
    )
    if not company:
        summary["error"] = "No Company found. Create a Company in ERPNext first."
        frappe.throw(summary["error"])
    summary["company"] = company

    # 1. Ensure the Loan Demand Offset Order exists (lending v15+ requirement).
    if not dry_run:
        order_name = _ensure_offset_order()
        summary["offset_order_name"] = order_name
        summary["offset_order_created"] = True
        _ensure_company_offset_sequences(company, order_name)
        summary["company_offset_set"] = True
        purposes_created = _ensure_loan_purposes()
        summary["loan_purposes_created"] = purposes_created
        frappe.db.commit()

    # 2. Check if the product already exists — idempotent.
    existing = frappe.db.exists("Loan Product", {"company": company, "product_code": "LMS-STD"})
    if existing:
        summary["product_exists"] = True
        summary["product_name"] = existing
        # Even if the product exists, ensure offset sequences are set
        # (the product may have been created before the offset fix).
        if not dry_run:
            _ensure_product_offset_sequences(existing, order_name)
            summary["product_offset_set"] = True
            frappe.db.commit()
        frappe.msgprint(f"LMS-STD already exists for {company}: {existing}. Offset sequences ensured.")
        return summary

    # 3. Resolve the GL accounts the Loan Product needs.
    from lms_saas.install import _loan_product_accounts, _seed_loan_product, _sync_loan_product_accounts

    accounts = _loan_product_accounts(company)
    if not accounts:
        summary["accounts_missing"] = [
            "disbursement_account",
            "loan_account",
            "interest_income_account",
        ]
        if dry_run:
            summary["error"] = (
                "GL accounts not found. Run without --dry-run to bootstrap "
                "via after_install()."
            )
            return summary

        try:
            from lms_saas.install import after_install
            after_install()
            summary["after_install_ran"] = True
            accounts = _loan_product_accounts(company)
        except Exception as exc:
            summary["error"] = f"after_install() failed: {exc}"
            frappe.log_error(message=str(exc), title="LMS bootstrap_loan_product")
            frappe.throw(f"Failed to bootstrap GL accounts: {exc}")

    if not accounts:
        summary["error"] = (
            "GL accounts could not be resolved even after after_install(). "
            "Manually set lms_loan_account, lms_interest_income_account, "
            "lms_disbursement_account in site_config."
        )
        frappe.throw(summary["error"])

    summary["accounts_resolved"] = accounts

    if dry_run:
        summary["product_created"] = False
        frappe.msgprint(
            f"DRY RUN: would create LMS-STD Loan Product for {company} "
            f"with accounts: {list(accounts.keys())}"
        )
        return summary

    # 4. Create the product.
    _seed_loan_product()
    _sync_loan_product_accounts()
    frappe.db.commit()

    created = frappe.db.get_value(
        "Loan Product", {"company": company, "product_code": "LMS-STD"}, "name"
    )
    summary["product_created"] = bool(created)
    summary["product_name"] = created

    if not created:
        summary["error"] = "Product creation did not throw but the product was not found after commit."
        frappe.throw(summary["error"])

    # 5. Set the offset sequences on the Loan Product (bypasses link validation).
    _ensure_product_offset_sequences(created, order_name)
    summary["product_offset_set"] = True
    frappe.db.commit()

    frappe.msgprint(
        f"✓ Created LMS-STD Loan Product for {company}: {created}. "
        f"Offset order: {order_name}. "
        "The manager and officer portals can now submit loan applications."
    )

    return summary


if __name__ == "__main__":
    import sys
    site = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--site" else "lms.localhost"
    frappe.init(site=site, sites_path="sites")
    frappe.connect()
    frappe.set_user("Administrator")
    print(run(dry_run="--dry-run" in sys.argv))
    frappe.destroy()