"""Fresh-install orchestrator for lms_saas — ONE call, 100% seeded.

Consolidates every post-install step we learned is required this session
(R42): ERPNext fixtures, Company creation, Loan Product with collection
offset orders, sandbox config, demo users, borrower Customer link, and
the after_install / onboard_company / live_repair self-heal hooks.

Run on a freshly-created site (after `bench new-site` + `bench install-app`):

    bench --site <site> execute lms_saas.setup.fresh_install.run \\
        --kwargs '{"company":"LMS Demo Co","currency":"USD","country":"Zimbabwe","apply":1}'

Idempotent: safe to re-run. Every step is a no-op when its target state
already exists.
"""

from __future__ import annotations

from typing import Any

import frappe


# The standard demo company + currency / country defaults.
DEFAULTS = {
    "company": "LMS Demo Co",
    "abbr": "LD",
    "currency": "USD",
    "country": "Zimbabwe",
    "domain": "Manufacturing",
}

# Sandbox / relaxed compliance config written to site_config so demo
# seeding (which disburses loans) doesn't trip the production-mode gate.
SANDBOX_CONFIG = {
    "lms_sandbox_end_date": "2027-12-31",
    "lms_compliance_relaxed": True,
    "lms_relax_origination": True,
    "lms_aml_enabled": False,
    "lms_aml_require_clear": False,
    "lms_payments_enabled": False,
    "lms_enforce_four_eyes": True,
    "lms_require_consent": True,
    "lms_max_loan_amount": 50000,
    "lms_max_active_customers": 500,
    "lms_risk_disclosure": "Loans involve credit risk. Terms and fees apply.",
    "lms_brand_portal_title": "Kesari",
    "lms_brand_footer_text": "Powered by Kesari",
    "lms_brand_tagline": "Stewardship in every repayment",
    "lms_theme": "default",
    "lms_operator_regulator": "Reserve Bank of Zimbabwe",
    "lms_operator_legal_name": "Kesari Microfinance Ltd",
    "lms_operator_licence_number": "MFI-RBZ-2024-001",
    "lms_operator_licence_validated": True,
}


def run(**kwargs: Any) -> dict:
    """Run the full fresh-install sequence. Idempotent.

    Args:
        company: Company name (default ``LMS Demo Co``).
        abbr: Company abbreviation (default ``LD``).
        currency: ISO 4217 code (default ``USD``).
        country: Full country name (default ``Zimbabwe``).
        domain: ERPNext domain (default ``Manufacturing``).
        apply: ``1`` to write, anything else is a dry-run.
        seed_loans: ``1`` (default) to seed demo + bulk loans.
        seed_users: ``1`` (default) to provision the 8 demo users.

    Returns:
        dict with ``applied``, ``skipped``, ``failed`` lists.
    """
    import json
    from pathlib import Path

    apply = bool(int(kwargs.pop("apply", 0) or 0))
    seed_loans = bool(int(kwargs.pop("seed_loans", 1) or 0))
    seed_users = bool(int(kwargs.pop("seed_users", 1) or 0))

    company = (kwargs.get("company") or DEFAULTS["company"]).strip()
    abbr = (kwargs.get("abbr") or DEFAULTS["abbr"]).strip()
    currency = (kwargs.get("currency") or DEFAULTS["currency"]).strip().upper()
    country = (kwargs.get("country") or DEFAULTS["country"]).strip()
    domain = (kwargs.get("domain") or DEFAULTS["domain"]).strip()

    result: dict[str, list[str]] = {"applied": [], "skipped": [], "failed": []}

    if not apply:
        result["plan"] = [
            "DRY RUN — nothing will be written. Re-run with apply=1.",
            f"Company: {company} ({abbr}) currency={currency} country={country} domain={domain}",
            "Steps: site_config → erpnext_fixtures → company → after_install →",
            "  onboard_company → loan_product → sandbox_config → seed_users →",
            "  seed_loans → link_borrower → live_repair → clear_cache",
        ]
        return result

    # ── 1. Write sandbox + brand config to site_config.json ──────────
    try:
        site_path = Path(frappe.utils.get_site_path("site_config.json"))
        raw = json.loads(site_path.read_text() or "{}")
        for k, v in SANDBOX_CONFIG.items():
            raw[k] = v
        site_path.write_text(json.dumps(raw, indent=2, sort_keys=True))
        for k, v in SANDBOX_CONFIG.items():
            frappe.conf[k] = v
        result["applied"].append("site_config: sandbox + brand keys written")
    except Exception as exc:  # noqa: BLE001
        result["failed"].append(f"site_config write failed: {exc}")

    # ── 2. Install ERPNext fixtures (Warehouse Type, Gender, etc.) ───
    try:
        from erpnext.setup.setup_wizard.operations.install_fixtures import install
        install(country=country)
        frappe.db.commit()
        result["applied"].append("erpnext fixtures: Warehouse Type, Gender, etc.")
    except Exception as exc:  # noqa: BLE001
        result["skipped"].append(f"erpnext fixtures skipped: {exc}")

    # ── 3. Ensure Gender master (ERPNext sometimes doesn't create all) ─
    try:
        for g in ("Male", "Female", "Prefer not to say", "Other"):
            if not frappe.db.exists("Gender", g):
                frappe.get_doc({"doctype": "Gender", "gender": g}).insert(ignore_permissions=True)
        frappe.db.commit()
        result["applied"].append("gender: 4 standard records ensured")
    except Exception as exc:  # noqa: BLE001
        result["skipped"].append(f"gender ensure skipped: {exc}")

    # ── 4. Create or update the Company with the requested currency/country ─
    try:
        if not frappe.db.exists("Country", country):
            frappe.get_doc({"doctype": "Country", "country_name": country}).insert(ignore_permissions=True)
        if not frappe.db.exists("Currency", currency):
            frappe.get_doc({"doctype": "Currency", "currency_name": currency, "enabled": 1}).insert(ignore_permissions=True)
        # R45: if a Company exists but with a different name/abbr/currency
        # (e.g. live was bootstrapped as "Kesari" before R44), use
        # reconcile_company_name to surgically rename + retag it so the
        # downstream Cost Center / Account / Loan names still resolve.
        # reconcile_company_name is a no-op if there's nothing to change.
        if frappe.db.exists("Company"):
            try:
                from lms_saas.setup.live_repair import reconcile_company_name
                reco = reconcile_company_name(
                    company=company,
                    abbr=abbr,
                    currency=currency,
                    country=country,
                    apply=1,
                )
                for line in reco.get("applied", []):
                    result["applied"].append(f"company_reconcile: {line}")
                for line in reco.get("skipped", []):
                    if line and line != "no changes requested":
                        result["skipped"].append(f"company_reconcile: {line}")
            except Exception as exc:  # noqa: BLE001
                result["skipped"].append(f"company_reconcile failed: {exc}")
        if not frappe.db.exists("Company", company):
            co = frappe.get_doc({
                "doctype": "Company",
                "company_name": company,
                "abbr": abbr,
                "default_currency": currency,
                "country": country,
                "domain": domain,
            })
            co.flags.ignore_permissions = True
            co.insert()
            result["applied"].append(f"company: created {company} ({currency}/{country})")
        else:
            # Company exists — update its currency/country to match the
            # operator's requested values so a re-run with different
            # currency/country params actually changes the company.
            frappe.db.set_value("Company", company, {
                "default_currency": currency,
                "country": country,
            })
            result["applied"].append(f"company: {company} updated to {currency}/{country}")
        frappe.db.set_single_value("Global Defaults", "default_company", company)
        # Also set Global Defaults currency so frappe.boot.sysdefaults.currency
        # resolves correctly on the portal.
        frappe.db.set_single_value("Global Defaults", "default_currency", currency)
        frappe.db.commit()
    except Exception as exc:  # noqa: BLE001
        result["failed"].append(f"company creation failed: {exc}")

    # ── 4b. Write lms_currency to site_config.json ────────────────────
    # The portal shell reads window.__lms_currency from context.lms_currency
    # (set by brand.py from the company's default_currency). But on the login
    # page — before the user has a session — brand.py hasn't run yet, so the
    # shell falls back to frappe.conf.get("lms_currency"). Writing it here at
    # install time means the login page shows the right currency symbol from
    # the very first request.
    try:
        raw["lms_currency"] = currency
        site_path.write_text(json.dumps(raw, indent=2, sort_keys=True))
        frappe.conf["lms_currency"] = currency
        result["applied"].append(f"site_config: lms_currency={currency}")
    except Exception as exc:  # noqa: BLE001
        result["skipped"].append(f"site_config lms_currency skipped: {exc}")

    # ── 5. Run lms_saas after_install (creates roles, workspaces, etc.) ─
    try:
        from lms_saas.install import after_install
        after_install()
        frappe.db.commit()
        result["applied"].append("after_install: roles, workspaces, loan product")
    except Exception as exc:  # noqa: BLE001
        result["failed"].append(f"after_install failed: {exc}")

    # ── 5b. Retire legacy LMS roles from any existing user assignments ─
    # after_install creates the new role set, but users from a previous
    # install may still have the retired LMS Admin / LMS Branch Manager /
    # LMS Loan Officer / LMS Collector roles. Clean them up here so the
    # live_repair step doesn't have to.
    try:
        from lms_saas.setup.live_repair import _repair_legacy_user_roles
        out = _repair_legacy_user_roles()
        if out.get("removed_rows"):
            result["applied"].append(f"legacy_roles: removed {out['removed_rows']} stale assignments")
    except Exception as exc:  # noqa: BLE001
        result["skipped"].append(f"legacy role cleanup skipped: {exc}")

    # ── 6. Run onboard_company (cost centers, branches) ───────────────
    try:
        from lms_saas.setup.onboard_company import run as onboard_run
        onboard_run(company=company, apply=1, run_verify=0)
        frappe.db.commit()
        result["applied"].append("onboard_company: cost centers + branches")
    except Exception as exc:  # noqa: BLE001
        result["skipped"].append(f"onboard_company skipped: {exc}")

    # ── 7. Ensure Loan Product (with collection offset orders) ───────
    try:
        from lms_saas.install import _seed_loan_product
        _seed_loan_product()
        frappe.db.commit()
        result["applied"].append("loan_product: LMS-STD ensured")
    except Exception as exc:  # noqa: BLE001
        result["failed"].append(f"loan_product failed: {exc}")

    # ── 8. Provision the 8 demo users ─────────────────────────────────
    if seed_users:
        try:
            from lms_saas.setup.live_repair import provision_test_users
            out = provision_test_users()
            n = len(out.get("created", [])) + len(out.get("updated", []))
            result["applied"].append(f"demo_users: {n} users provisioned")
            if out.get("skipped"):
                result["skipped"].append(f"demo_users skipped: {out['skipped']}")
        except Exception as exc:  # noqa: BLE001
            result["failed"].append(f"demo_users failed: {exc}")

    # ── 9. Seed demo + bulk loans ─────────────────────────────────────
    if seed_loans:
        try:
            from lms_saas.setup.seed_demo import run as seed_demo, run_bulk
            seed_demo()
            frappe.db.commit()
            bulk = run_bulk(count=12, with_repayments=True)
            frappe.db.commit()
            result["applied"].append(
                f"seed_loans: demo + {bulk.get('created_loans', 0)} bulk "
                f"({bulk.get('repayments', 0)} repayments)"
            )
        except Exception as exc:  # noqa: BLE001
            result["skipped"].append(f"seed_loans skipped: {exc}")

    # ── 10. Link borrower to a loan-bearing Customer ──────────────────
    try:
        from lms_saas.setup.live_repair import link_borrower_to_demo_customer
        link_borrower_to_demo_customer("borrower@example.com")
        frappe.db.commit()
        result["applied"].append("borrower_link: re-linked to loan-bearing Customer")
    except Exception as exc:  # noqa: BLE001
        result["skipped"].append(f"borrower_link skipped: {exc}")

    # ── 11. Run live_repair self-heal (user setup, roles, branches) ──
    # R54: previously this called repair_live_site_state() which calls
    # after_install() again — but after_install already ran in step 5.
    # Now we call only the live-repair-specific steps (user setup,
    # legacy roles, branch reconciliation) that after_install does NOT
    # cover. The dashboard / home-page / branding steps are already
    # done by after_install in step 5.
    try:
        from lms_saas.setup.live_repair import (
            _diagnose_user_setup,
            _repair_user_setup,
            _repair_legacy_user_roles,
            reconcile_staff_branches,
        )
        diagnostic = _diagnose_user_setup()
        _repair_user_setup(diagnostic)
        _repair_legacy_user_roles()
        reconcile_staff_branches()
        frappe.db.commit()
        result["applied"].append("live_repair: user setup + roles + branches")
    except Exception as exc:  # noqa: BLE001
        result["skipped"].append(f"live_repair skipped: {exc}")

    # ── 11b. Sync lms_currency in site_config to match company currency ─
    # Ensures the portal shell shows the correct currency symbol on every
    # page (including the login page before the user has a session).
    try:
        from lms_saas.setup.set_company_currency_country import _sync_site_config_currency
        out = _sync_site_config_currency()
        if out.get("applied"):
            result["applied"].append(f"currency_sync: {out['applied']}")
        else:
            result["skipped"].append(f"currency_sync: {out.get('skipped', 'no-op')}")
    except Exception as exc:  # noqa: BLE001
        result["skipped"].append(f"currency_sync skipped: {exc}")

    # ── 12. Clear cache + enable scheduler ───────────────────────────
    try:
        frappe.clear_cache()
        frappe.db.set_single_value("System Settings", "enable_scheduler", 1)
        frappe.db.commit()
        result["applied"].append("cache cleared + scheduler enabled")
    except Exception as exc:  # noqa: BLE001
        result["skipped"].append(f"cache/scheduler skipped: {exc}")

    return result


def diff() -> dict:
    """Return a snapshot of the fresh-install state for verification."""
    company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
    out: dict[str, Any] = {
        "company": company,
        "company_currency": frappe.db.get_value("Company", company, "default_currency") if company else None,
        "company_country": frappe.db.get_value("Company", company, "country") if company else None,
        "loan_product": frappe.db.exists("Loan Product", {"product_code": "LMS-STD"}),
        "users": frappe.db.count("User", filters={"enabled": 1}),
        "customers": frappe.db.count("Customer"),
        "loans": frappe.db.count("Loan", filters={"docstatus": 1}) if frappe.db.exists("DocType", "Loan") else 0,
        "sandbox_mode": frappe.conf.get("lms_sandbox_end_date") is not None,
        "warehouse_types": frappe.db.count("Warehouse Type") if frappe.db.exists("DocType", "Warehouse Type") else 0,
        "genders": frappe.db.count("Gender") if frappe.db.exists("DocType", "Gender") else 0,
    }
    return out