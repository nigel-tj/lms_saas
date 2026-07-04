"""Idempotent single-company onboarding for live/staging sites.

Run examples:
  bench --site app.kesari.africa execute lms_saas.setup.onboard_company.run --kwargs '{"company":"Kesari","dry_run":1}'
  bench --site app.kesari.africa execute lms_saas.setup.onboard_company.run --kwargs '{"company":"Kesari","apply":1,"run_verify":1}'
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import frappe


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


def _ensure_company(company: str | None) -> str:
    if not company:
        company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        company = frappe.db.get_value("Company", {}, "name")
    if not company:
        frappe.throw("No Company found. Create Company first.")
    if not frappe.db.exists("Company", company):
        frappe.throw(f"Company '{company}' not found")
    return company


def _detect_plan(company: str, email_id: str | None = None) -> dict[str, Any]:
    from lms_saas.install import LMS_NAV_SPEC

    branches = ["Main Branch", "North Branch", "South Branch"]
    missing_branches = [
        b for b in branches if not frappe.db.exists("Cost Center", {"company": company, "cost_center_name": b})
    ]

    lms_product_exists = bool(frappe.db.exists("Loan Product", {"company": company, "product_code": "LMS-STD"}))

    missing_workspaces = [spec["title"] for spec in LMS_NAV_SPEC if not frappe.db.exists("Workspace", spec["title"])]

    email_state = {
        "needs_setup": False,
        "account": None,
    }
    if email_id:
        account = frappe.db.get_value(
            "Email Account",
            {"email_id": email_id},
            "name",
        )
        email_state["account"] = account
        email_state["needs_setup"] = not bool(account)

    return {
        "company": company,
        "branches_missing": missing_branches,
        "loan_product_missing": not lms_product_exists,
        "workspaces_missing": missing_workspaces,
        "email": email_state,
    }


@contextmanager
def _temporary_company_context(company: str):
    """Patch install._default_company so helper functions target the requested company."""
    import lms_saas.install as install_mod

    original = install_mod._default_company
    install_mod._default_company = lambda: company
    try:
        yield
    finally:
        install_mod._default_company = original


@contextmanager
def _temporary_conf(overrides: dict[str, Any]):
    changed = {}
    sentinel = object()
    for key, value in overrides.items():
        changed[key] = frappe.conf.get(key, sentinel)
        frappe.conf[key] = value
    try:
        yield
    finally:
        for key, prev in changed.items():
            if prev is sentinel:
                frappe.conf.pop(key, None)
            else:
                frappe.conf[key] = prev


def _maybe_update_company_identity(company: str, *, company_name: str | None, domain: str | None, dry_run: bool) -> dict[str, Any]:
    current = frappe.get_cached_value("Company", company, ["company_name", "domain"], as_dict=True) or {}
    updates = {}
    if company_name and company_name != current.get("company_name"):
        updates["company_name"] = company_name
    if domain and domain != current.get("domain"):
        updates["domain"] = domain

    if not updates:
        return {"status": "skipped", "reason": "already up-to-date"}
    if dry_run:
        return {"status": "planned", "updates": updates}

    frappe.db.set_value("Company", company, updates)
    return {"status": "updated", "updates": updates}


def _apply_core_setup(company: str) -> None:
    import lms_saas.install as install_mod

    with _temporary_company_context(company):
        install_mod._seed_branches()
        install_mod._seed_loan_product()
        install_mod._sync_loan_product_accounts()

    install_mod._ensure_lending_permissions()
    install_mod._ensure_lms_report_support_permissions()
    install_mod._sync_lms_report_roles()
    install_mod._sync_dashboard_chart_source()
    install_mod._sync_number_cards()
    install_mod._sync_dashboard_charts()
    install_mod._sync_loan_dashboard_extensions()
    install_mod._sync_lms_workspaces()
    install_mod._setup_navbar_branding()
    install_mod._seed_print_formats()
    install_mod._sync_print_formats()
    install_mod._ensure_crm_permissions()
    install_mod._seed_branded_emails()
    install_mod._setup_portal_menu()
    install_mod._ensure_customer_portal_role()
    install_mod._seed_payment_providers()


def _run_verification(full_verify: bool) -> dict[str, Any]:
    from lms_saas.setup.verify_spec import run_all_checks

    report = run_all_checks()
    if not full_verify:
        return {
            "ok": report.get("ok", False),
            "checks": {
                k: report.get("checks", {}).get(k)
                for k in ("roles", "workspace", "loan_product", "branches", "crm", "scheduler")
            },
            "mode": "targeted",
        }
    report["mode"] = "full"
    return report


def run(
    company: str | None = None,
    dry_run: int | bool | None = 1,
    apply: int | bool | None = 0,
    company_name: str | None = None,
    domain: str | None = None,
    run_verify: int | bool | None = 1,
    full_verify: int | bool | None = 0,
    send_test_email: int | bool | None = 0,
    test_email_recipient: str | None = None,
    include_demo: int | bool | None = 0,
    demo_count: int | None = 0,
    smtp_server: str | None = None,
    smtp_port: int | None = None,
    smtp_email_id: str | None = None,
    smtp_password: str | None = None,
    smtp_use_ssl: int | bool | None = None,
) -> dict[str, Any]:
    """Onboard one company safely and return a JSON-friendly summary.

    Defaults to dry-run unless apply=1 is passed.
    """
    company = _ensure_company(company)
    do_apply = _as_bool(apply, False)
    is_dry_run = _as_bool(dry_run, not do_apply)
    if do_apply:
        is_dry_run = False

    config = {
        "lms_live_smtp_server": smtp_server or frappe.conf.get("lms_live_smtp_server"),
        "lms_live_smtp_port": _as_int(smtp_port, _as_int(frappe.conf.get("lms_live_smtp_port"), 465)),
        "lms_live_email_id": smtp_email_id or frappe.conf.get("lms_live_email_id"),
        "lms_live_smtp_password": smtp_password or frappe.conf.get("lms_live_smtp_password"),
        "lms_live_smtp_use_ssl": (
            int(_as_bool(smtp_use_ssl, True))
            if smtp_use_ssl is not None
            else _as_int(frappe.conf.get("lms_live_smtp_use_ssl"), 1)
        ),
    }

    summary: dict[str, Any] = {
        "ok": True,
        "mode": "dry-run" if is_dry_run else "apply",
        "company": company,
        "plan": _detect_plan(company, email_id=(config.get("lms_live_email_id") or "").strip() or None),
        "actions": {},
        "warnings": [],
        "errors": [],
    }

    try:
        summary["actions"]["company_identity"] = _maybe_update_company_identity(
            company,
            company_name=company_name,
            domain=domain,
            dry_run=is_dry_run,
        )

        if is_dry_run:
            summary["actions"]["core_setup"] = {"status": "planned"}
            summary["actions"]["email_setup"] = {
                "status": "planned",
                "smtp_server": config.get("lms_live_smtp_server"),
                "email_id": config.get("lms_live_email_id"),
            }
        else:
            _apply_core_setup(company)
            summary["actions"]["core_setup"] = {"status": "applied"}

            if config.get("lms_live_smtp_server") and config.get("lms_live_email_id") and config.get("lms_live_smtp_password"):
                from lms_saas.setup.configure_live_email import run as configure_email

                with _temporary_conf(config):
                    summary["actions"]["email_setup"] = configure_email()
            else:
                summary["actions"]["email_setup"] = {
                    "ok": False,
                    "status": "skipped",
                    "reason": "SMTP config incomplete (server/email/password required)",
                }
                summary["warnings"].append("SMTP setup skipped due to incomplete configuration")

            if _as_bool(include_demo, False):
                if _as_int(demo_count, 0) > 0:
                    from lms_saas.setup.seed_demo import run_bulk

                    summary["actions"]["demo_seed"] = run_bulk(count=_as_int(demo_count, 12))
                else:
                    from lms_saas.setup.seed_demo import run as run_demo

                    summary["actions"]["demo_seed"] = run_demo()
            else:
                summary["actions"]["demo_seed"] = {"status": "skipped"}

            if _as_bool(send_test_email, False):
                from lms_saas.setup.configure_live_email import send_test_email as send_test

                summary["actions"]["test_email"] = send_test(recipient=test_email_recipient)
            else:
                summary["actions"]["test_email"] = {"status": "skipped"}

            if _as_bool(run_verify, True):
                summary["verification"] = _run_verification(_as_bool(full_verify, False))

            frappe.db.commit()

    except Exception:
        summary["ok"] = False
        summary["errors"].append(frappe.get_traceback())
        frappe.db.rollback()

    if summary.get("verification") and not summary["verification"].get("ok", False):
        summary["ok"] = False

    if summary.get("errors"):
        summary["ok"] = False

    return summary
