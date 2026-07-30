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
        "dry_run": dry_run,
    }

    company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
        "Company", {}, "name"
    )
    if not company:
        summary["error"] = "No Company found. Create a Company in ERPNext first."
        frappe.throw(summary["error"])
    summary["company"] = company

    # 1. Check if the product already exists — idempotent.
    existing = frappe.db.exists("Loan Product", {"company": company, "product_code": "LMS-STD"})
    if existing:
        summary["product_exists"] = True
        summary["product_name"] = existing
        frappe.msgprint(f"LMS-STD already exists for {company}: {existing}. Nothing to do.")
        return summary

    # 2. Resolve the GL accounts the Loan Product needs.
    from lms_saas.install import _loan_product_accounts, _seed_loan_product, _sync_loan_product_accounts

    accounts = _loan_product_accounts(company)
    if not accounts:
        # Accounts are missing. Run after_install() which will create the
        # Chart of Accounts structure and then seed the product.
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

    # 3. Create the product.
    _seed_loan_product()
    _sync_loan_product_accounts()
    frappe.db.commit()

    created = frappe.db.get_value(
        "Loan Product", {"company": company, "product_code": "LMS-STD"}, "name"
    )
    summary["product_created"] = bool(created)
    summary["product_name"] = created

    if created:
        frappe.msgprint(
            f"✓ Created LMS-STD Loan Product for {company}: {created}. "
            "The manager and officer portals can now submit loan applications."
        )
    else:
        summary["error"] = "Product creation did not throw but the product was not found after commit."
        frappe.throw(summary["error"])

    return summary


if __name__ == "__main__":
    import sys
    site = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--site" else "lms.localhost"
    frappe.init(site=site, sites_path="sites")
    frappe.connect()
    frappe.set_user("Administrator")
    print(run(dry_run="--dry-run" in sys.argv))
    frappe.destroy()