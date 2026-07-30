#!/usr/bin/env python3
"""Mark all LMS Borrower Compliance records as AML-Clear.

Sandbox/demo-only helper. Useful when running the system without a real
AML provider and you want the KYC modal to show "Clear" instead of
"Pending" so demos are not visually misleading.

SAFETY:
  - Refuses to run if `lms_aml_enabled` is True (i.e. you have a real
    provider configured). This script bypasses the provider and is
    meant for sandbox / demo data only.
  - Writes a critical LMS Audit Event for every change so the
    override is traceable.
  - Idempotent: re-running is a no-op for already-cleared records.

USAGE:
  bench --site <site> execute lms_saas.scripts.mark_demo_borrowers_aml_clear.run
  # or
  bench --site <site> console
  >>> from lms_saas.scripts.mark_demo_borrowers_aml_clear import run
  >>> run()
"""
from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from lms_saas.api.compliance import write_audit_event

# Per-record status we're stamping onto the compliance record.
TARGET_STATUS = "Clear"

# Reason that goes into the audit log. Tells the regulator this is a
# sandbox/demo action, not a real screening.
SANDBOX_REASON = (
    "Sandbox/demo override: AML provider is disabled for this site. "
    "Stamped Clear for demo purposes only. NOT a real screening result."
)


def run(*, dry_run: bool = False, batch_size: int = 200) -> dict:
    """Mark every compliance record as Clear (sandbox override).

    Returns a summary dict.
    """
    if frappe.conf.get("lms_aml_enabled", False):
        frappe.throw(
            "Refusing to run: lms_aml_enabled is True. This script is for "
            "sandbox / demo sites only. Disable the provider first or pass "
            "dry_run=True for a preview."
        )

    summary = {
        "considered": 0,
        "already_clear": 0,
        "updated": 0,
        "skipped_no_compliance_record": 0,
    }

    # Walk every Customer. Compliance Record is one-per-borrower; if the
    # row exists, update it; if not, skip.
    customers = frappe.get_all(
        "Customer",
        fields=["name", "customer_name"],
        limit_page_length=0,
    )
    now = now_datetime()

    for cust in customers:
        summary["considered"] += 1
        comp_name = frappe.db.get_value(
            "LMS Borrower Compliance", {"customer": cust.name}, "name"
        )
        if not comp_name:
            summary["skipped_no_compliance_record"] += 1
            continue

        current_status, current_screened_at = frappe.db.get_value(
            "LMS Borrower Compliance",
            comp_name,
            ["aml_status", "aml_screened_at"],
        )

        if current_status == TARGET_STATUS and current_screened_at:
            summary["already_clear"] += 1
            continue

        if dry_run:
            summary["updated"] += 1
            continue

        frappe.db.set_value(
            "LMS Borrower Compliance",
            comp_name,
            {
                "aml_status": TARGET_STATUS,
                "aml_screened_at": now,
                # Leave aml_provider_ref / aml_risk_level as-is so we
                # don't fabricate provider output.
            },
            update_modified=False,
        )

        write_audit_event(
            event_type="AML:SandboxOverride",
            reference_doctype="LMS Borrower Compliance",
            reference_name=comp_name,
            details=(
                f"customer={cust.name} ({cust.customer_name}); "
                f"aml_status: {current_status} -> {TARGET_STATUS}; "
                f"reason={SANDBOX_REASON}"
            ),
        )
        summary["updated"] += 1

    frappe.db.commit()

    if dry_run:
        frappe.msgprint(
            f"DRY RUN: would update {summary['updated']} record(s); "
            f"{summary['already_clear']} already clear; "
            f"{summary['skipped_no_compliance_record']} skipped (no record)."
        )
    else:
        frappe.msgprint(
            f"Updated {summary['updated']} compliance record(s) to Clear. "
            f"{summary['already_clear']} were already clear. "
            f"Audit log written for each change."
        )

    return summary


if __name__ == "__main__":
    # Allow `python3 mark_demo_borrowers_aml_clear.py` from a bench
    # console for ad-hoc use.
    import sys
    site = sys.argv[1] if len(sys.argv) > 1 else "lms.localhost"
    frappe.init(site=site, sites_path="sites")
    frappe.connect()
    frappe.set_user("Administrator")
    print(run(dry_run="--dry-run" in sys.argv))
    frappe.destroy()
