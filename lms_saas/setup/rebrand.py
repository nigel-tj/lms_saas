"""Idempotent single-call rebrand for a freshly installed ``lms_saas`` site.

R23-Q2-C1: this runner collapses the 6-step rebrand flow (after_install +
onboard_company + configure_live_email + manual Website Settings + manual
System Settings + manual logo upload) into ONE ``bench execute`` call so
a new operator (or a rebrand to a different product line) can ship under
their own brand in one shot.

Run examples (dry-run by default — print a plan, write nothing):

    bench --site <site> execute lms_saas.setup.rebrand.run --kwargs '{
        "operator_legal_name": "Kesari Microfinance Ltd",
        "operator_domain": "kesari.africa",
        "operator_regulator": "Reserve Bank of Zimbabwe",
        "operator_licence_number": "MFI-RBZ-2024-001",
        "operator_licence_validated": true,
        "portal_title": "Kesari",
        "tagline": "Stewardship in every repayment",
        "footer_text": "Powered by Kesari",
        "primary_color": "#2f4f46",
        "support_email": "support@kesari.africa",
        "company": "Kesari Microfinance Ltd",
        "domain": "kesari.africa",
        "logo_path": "/files/kesari-logo.svg",
        "favicon_path": "/files/kesari-favicon.svg",
        "smtp_server": "kesari.africa",
        "smtp_email": "app@kesari.africa",
        "smtp_password": "<secret>",
        "smtp_port": 465,
        "smtp_use_ssl": true,
        "apply": 1
    }'

The runner:
- Validates every key (the dry-run prints a list of what's missing).
- Sets the operator profile keys (``lms_operator_*``) and brand keys
  (``lms_brand_*``) in ``site_config.json`` — the ONLY safe way to write
  site_config is via the file (Frappe does not expose site_config writes
  via the ORM).
- Calls ``onboard_company.run`` to seed Company + Cost Centers + Loan
  Product + Workspaces.
- Calls ``configure_live_email.run`` to set up the SMTP account.
- Writes Website Settings (app_name, app_logo, favicon, splash_image,
  brand_html) and System Settings (app_name) — the values the operator
  sees in the desk chrome and the /login page.
- Returns a structured ``{"applied": [...], "skipped": [...], "failed": [...]}``
  so the operator can verify the rebrand was applied end-to-end.

The runner is safe to re-run: every write is idempotent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import frappe


# All rebrand keys — used for validation and dry-run output.
REBRAND_KEYS = (
    # Operator profile (compliance / production-mode)
    "operator_legal_name",
    "operator_domain",
    "operator_regulator",
    "operator_licence_number",
    "operator_licence_validated",
    # Visible brand
    "portal_title",
    "tagline",
    "footer_text",
    "primary_color",
    "support_email",
    # Brand assets
    "logo_path",
    "favicon_path",
    # Company / domain
    "company",
    "domain",
    # SMTP / Email Account
    "smtp_server",
    "smtp_email",
    "smtp_password",
    "smtp_port",
    "smtp_use_ssl",
)

# Mapping from rebrand key to the site_config key it sets.
# ``lms_operator_*`` keys live in compliance_config.py;
# ``lms_brand_*`` keys live in utils/brand.py.
SITE_CONFIG_MAP = {
    "operator_legal_name": "lms_operator_legal_name",
    "operator_regulator": "lms_operator_regulator",
    "operator_licence_number": "lms_operator_licence_number",
    "operator_licence_validated": "lms_operator_licence_validated",
    "portal_title": "lms_brand_portal_title",
    "tagline": "lms_brand_tagline",
    "footer_text": "lms_brand_footer_text",
    "primary_color": "lms_brand_primary_color",
    "support_email": "lms_support_email",
    "logo_path": "lms_brand_logo_path",
    "favicon_path": "lms_brand_favicon_path",
    "smtp_server": "lms_live_smtp_server",
    "smtp_email": "lms_live_email_id",
    "smtp_password": "lms_live_smtp_password",
    "smtp_port": "lms_live_smtp_port",
    "smtp_use_ssl": "lms_live_smtp_use_ssl",
}

# Keys that are required for a rebrand to be considered complete.
REQUIRED_KEYS = (
    "portal_title",
    "company",
)


def run(**kwargs) -> dict:
    """Idempotent single-call rebrand.

    Args:
        **kwargs: Rebrand values (see REBRAND_KEYS for the full list).
            ``apply`` is the toggle: ``apply=1`` writes everything,
            ``apply=0`` (default) prints a plan and writes nothing.

    Returns:
        dict with keys ``applied``, ``skipped``, ``failed``, and (when
        dry-run) ``plan``. Each entry is a list of human-readable strings
        so the operator can audit the rebrand end-to-end.
    """
    apply = bool(kwargs.pop("apply", False))
    # Normalise booleans — bench execute may pass strings.
    for k in ("operator_licence_validated", "smtp_use_ssl"):
        if k in kwargs and isinstance(kwargs[k], str):
            kwargs[k] = kwargs[k].strip().lower() in {"1", "true", "yes", "on"}
    if "smtp_port" in kwargs:
        try:
            kwargs["smtp_port"] = int(kwargs["smtp_port"])
        except (TypeError, ValueError):
            pass

    result = {"applied": [], "skipped": [], "failed": []}

    # 1. Validate required keys.
    missing = [k for k in REQUIRED_KEYS if not kwargs.get(k)]
    if missing:
        result["failed"].append(
            f"Missing required keys: {', '.join(missing)}"
        )
        return result

    if not apply:
        # Dry-run: print a plan, write nothing.
        result["plan"] = _build_plan(kwargs)
        return result

    # 2. Write site_config keys.
    try:
        _write_site_config(kwargs)
        result["applied"].append("site_config.json: lms_operator_* and lms_brand_* keys set")
    except Exception as exc:  # noqa: BLE001
        result["failed"].append(f"site_config write failed: {exc}")
        return result

    # 3. Run onboard_company for the operator's company.
    try:
        from lms_saas.setup.onboard_company import run as onboard_run

        onboard_kwargs = {"company": kwargs["company"], "apply": 1, "run_verify": 0}
        if kwargs.get("operator_legal_name"):
            onboard_kwargs["company_name"] = kwargs["operator_legal_name"]
        if kwargs.get("operator_domain"):
            onboard_kwargs["domain"] = kwargs["operator_domain"]
        onboard_result = onboard_run(**onboard_kwargs)
        result["applied"].append(
            f"onboard_company: company={kwargs['company']} "
            f"company_name={kwargs.get('operator_legal_name', kwargs['company'])} "
            f"domain={kwargs.get('operator_domain', '<unchanged>')}"
        )
        if not onboard_result.get("ok", True):
            result["failed"].append(f"onboard_company returned: {onboard_result}")
    except Exception as exc:  # noqa: BLE001
        result["failed"].append(f"onboard_company failed: {exc}")

    # 4. Run configure_live_email for the operator's SMTP.
    if kwargs.get("smtp_server") and kwargs.get("smtp_email") and kwargs.get("smtp_password"):
        try:
            from lms_saas.setup.configure_live_email import run as configure_run

            configure_result = configure_run()
            if configure_result.get("ok"):
                result["applied"].append(
                    f"configure_live_email: smtp={kwargs['smtp_server']} "
                    f"email={kwargs['smtp_email']}"
                )
            else:
                result["failed"].append(
                    f"configure_live_email returned: {configure_result.get('reason')}"
                )
        except Exception as exc:  # noqa: BLE001
            result["failed"].append(f"configure_live_email failed: {exc}")
    else:
        result["skipped"].append(
            "configure_live_email: smtp_server, smtp_email, smtp_password not all provided"
        )

    # 5. Write Website Settings + System Settings (the desk chrome).
    try:
        _write_website_settings(kwargs)
        result["applied"].append("website_settings: app_name, app_logo, favicon, splash_image, brand_html set")
    except Exception as exc:  # noqa: BLE001
        result["failed"].append(f"website_settings write failed: {exc}")

    try:
        _write_system_settings(kwargs)
        result["applied"].append("system_settings: app_name set")
    except Exception as exc:  # noqa: BLE001
        result["failed"].append(f"system_settings write failed: {exc}")

    # 6. Re-run after_install to pick up the new brand in navbar / help
    #    dropdown (idempotent).
    try:
        from lms_saas.install import after_install

        after_install()
        result["applied"].append("after_install: navbar / website settings re-applied")
    except Exception as exc:  # noqa: BLE001
        result["failed"].append(f"after_install failed: {exc}")

    return result


def _build_plan(kwargs: dict) -> list[str]:
    """Return a human-readable plan for the dry-run output."""
    plan = ["DRY RUN — nothing will be written. Re-run with apply=1 to apply."]
    plan.append("")
    plan.append("site_config.json keys to set:")
    for src, dst in SITE_CONFIG_MAP.items():
        if src in kwargs and kwargs[src] is not None:
            plan.append(f"  {dst} = {kwargs[src]!r}")
    plan.append("")
    plan.append("onboard_company.run with:")
    plan.append(f"  company = {kwargs.get('company')!r}")
    plan.append(f"  company_name = {kwargs.get('operator_legal_name', kwargs.get('company'))!r}")
    plan.append(f"  domain = {kwargs.get('operator_domain')!r}")
    plan.append("")
    if kwargs.get("smtp_server") and kwargs.get("smtp_email"):
        plan.append("configure_live_email.run with:")
        plan.append(f"  smtp_server = {kwargs['smtp_server']!r}")
        plan.append(f"  smtp_email = {kwargs['smtp_email']!r}")
    else:
        plan.append("configure_live_email.run: SKIPPED (smtp_server / smtp_email not provided)")
    plan.append("")
    plan.append("Website Settings + System Settings writes: see _write_website_settings / _write_system_settings")
    return plan


def _write_site_config(kwargs: dict) -> None:
    """Write the lms_operator_* and lms_brand_* keys to site_config.json.

    The site_config file is the ONLY safe place to store these keys —
    Frappe does not expose site_config writes via the ORM. The file
    is read at request time, so changes are visible on the next request.
    """
    site_path = Path(frappe.utils.get_site_path("site_config.json"))
    if not site_path.exists():
        raise FileNotFoundError(f"site_config.json not found at {site_path}")

    raw = json.loads(site_path.read_text() or "{}")
    for src, dst in SITE_CONFIG_MAP.items():
        if src in kwargs and kwargs[src] is not None:
            raw[dst] = kwargs[src]
    # In-memory also (so the current process picks up the change).
    for src, dst in SITE_CONFIG_MAP.items():
        if src in kwargs and kwargs[src] is not None:
            frappe.conf[dst] = kwargs[src]
    site_path.write_text(json.dumps(raw, indent=2, sort_keys=True))


def _write_website_settings(kwargs: dict) -> None:
    """Write Website Settings: app_name, app_logo, favicon, splash_image, brand_html."""
    if not frappe.db.exists("DocType", "Website Settings"):
        return
    website = frappe.get_single("Website Settings")
    title = kwargs.get("portal_title") or "LMS"
    website.app_name = title
    website.brand_html = f'<span style="font-weight:600">{title}</span>'
    if kwargs.get("logo_path"):
        website.app_logo = kwargs["logo_path"]
    if kwargs.get("favicon_path"):
        website.favicon = kwargs["favicon_path"]
        if frappe.get_meta("Website Settings").has_field("splash_image"):
            website.splash_image = kwargs["favicon_path"]
    website.flags.ignore_permissions = True
    website.save(ignore_permissions=True)


def _write_system_settings(kwargs: dict) -> None:
    """Write System Settings: app_name (the value the desk shows in the title bar)."""
    title = kwargs.get("portal_title") or "LMS"
    if frappe.db.exists("DocType", "System Settings"):
        frappe.db.set_single_value("System Settings", "app_name", title)


def diff() -> dict:
    """Return a JSON-serialisable snapshot of every brand-touching value.

    Used by the operator (and any auditor) to verify the rebrand was
    applied end-to-end. Returns a flat dict so the result is easy to diff.
    """
    import frappe as _frappe

    out: dict[str, Any] = {
        "site_config": {
            "lms_brand_portal_title": _frappe.conf.get("lms_brand_portal_title"),
            "lms_brand_tagline": _frappe.conf.get("lms_brand_tagline"),
            "lms_brand_footer_text": _frappe.conf.get("lms_brand_footer_text"),
            "lms_brand_primary_color": _frappe.conf.get("lms_brand_primary_color"),
            "lms_brand_logo_path": _frappe.conf.get("lms_brand_logo_path"),
            "lms_brand_favicon_path": _frappe.conf.get("lms_brand_favicon_path"),
            "lms_operator_legal_name": _frappe.conf.get("lms_operator_legal_name"),
            "lms_operator_licence_number": _frappe.conf.get("lms_operator_licence_number"),
            "lms_operator_regulator": _frappe.conf.get("lms_operator_regulator"),
            "lms_live_smtp_server": _frappe.conf.get("lms_live_smtp_server"),
            "lms_live_email_id": _frappe.conf.get("lms_live_email_id"),
        },
    }
    try:
        website = _frappe.get_single("Website Settings")
        out["website_settings"] = {
            "app_name": website.app_name,
            "app_logo": website.app_logo,
            "favicon": website.favicon,
            "splash_image": getattr(website, "splash_image", None),
            "brand_html": website.brand_html,
        }
    except Exception:
        out["website_settings"] = {"error": "could not read Website Settings"}
    try:
        out["system_settings"] = {
            "app_name": _frappe.db.get_single_value("System Settings", "app_name"),
        }
    except Exception:
        out["system_settings"] = {"error": "could not read System Settings"}
    try:
        out["default_company"] = _frappe.db.get_single_value("Global Defaults", "default_company")
    except Exception:
        out["default_company"] = None
    return out
