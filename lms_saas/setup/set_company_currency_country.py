"""Set the default Company's currency and country.

Idempotent one-call helper used by ``scripts/set-company-currency-country.sh``.
Safe to re-run — every write is a no-op when the target state already exists.

Run examples:

    # Dry-run (prints the plan, writes nothing):
    bench --site lms.localhost execute \
        lms_saas.setup.set_company_currency_country.run \
        --kwargs '{"company":"LMS Demo Co","currency":"USD","country":"Zimbabwe"}'

    # Apply:
    bench --site lms.localhost execute \
        lms_saas.setup.set_company_currency_country.run \
        --kwargs '{"company":"LMS Demo Co","currency":"USD","country":"Zimbabwe","apply":1}'

    # Read back the current state:
    bench --site lms.localhost execute \
        lms_saas.setup.set_company_currency_country.diff
"""

from __future__ import annotations

from typing import Any

import frappe


def run(**kwargs: Any) -> dict:
    """Set ``Company.default_currency`` and ``Company.country``.

    Args:
        company: Company name. Defaults to the Global Defaults default_company.
        currency: ISO 4217 currency code (e.g. ``USD``).
        country: Full country name as listed in Frappe's Country master
            (e.g. ``Zimbabwe``). The Country doctype row is created if missing.
        apply: ``1`` to write, anything else (default) is a dry-run.

    Returns:
        dict with ``applied``, ``skipped``, ``failed`` lists — each containing
        human-readable strings so the operator can audit the change.
    """
    apply = bool(int(kwargs.pop("apply", 0) or 0))
    company = (kwargs.get("company") or "").strip()
    currency = (kwargs.get("currency") or "").strip().upper()
    country = (kwargs.get("country") or "").strip()

    result: dict[str, list[str]] = {"applied": [], "skipped": [], "failed": []}

    # 1. Resolve the company.
    if not company:
        company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
    if not company:
        company = frappe.db.get_value("Company", {}, "name") or ""
    if not company:
        result["failed"].append("No Company found. Create a Company first.")
        return result
    if not frappe.db.exists("Company", company):
        result["failed"].append(f"Company '{company}' not found.")
        return result

    # 2. Validate the currency code against Frappe's Currency master.
    if currency and not frappe.db.exists("Currency", currency):
        # Auto-create the Currency row so the operator doesn't have to.
        if apply:
            try:
                cur_doc = frappe.get_doc(
                    {"doctype": "Currency", "currency_name": currency, "enabled": 1}
                )
                cur_doc.flags.ignore_permissions = True
                cur_doc.insert()
                result["applied"].append(f"currency: created Currency '{currency}'")
            except Exception as exc:  # noqa: BLE001
                result["failed"].append(f"currency: could not create '{currency}': {exc}")
                return result
        else:
            result["skipped"].append(
                f"currency: '{currency}' does not exist in Currency master "
                f"(would be auto-created on apply)"
            )

    # 3. Validate / create the Country.
    if country and not frappe.db.exists("Country", country):
        if apply:
            try:
                frappe.get_doc(
                    {"doctype": "Country", "country_name": country}
                ).insert(ignore_permissions=True)
                result["applied"].append(f"country: created Country '{country}'")
            except Exception as exc:  # noqa: BLE001
                result["failed"].append(f"country: could not create '{country}': {exc}")
                return result
        else:
            result["skipped"].append(
                f"country: '{country}' does not exist in Country master "
                f"(would be auto-created on apply)"
            )

    # 4. Read the current Company values.
    current = frappe.db.get_value(
        "Company", company, ["default_currency", "country"], as_dict=True
    ) or {}
    updates: dict[str, str] = {}
    if currency and (current.get("default_currency") or "") != currency:
        updates["default_currency"] = currency
    if country and (current.get("country") or "") != country:
        updates["country"] = country

    if not updates:
        result["skipped"].append(
            f"company '{company}' already has "
            f"currency={current.get('default_currency')!r} "
            f"country={current.get('country')!r} — no changes needed"
        )
        return result

    plan_lines = [
        f"Company '{company}' updates:",
        f"  default_currency: {current.get('default_currency')!r} -> {currency!r}",
        f"  country:          {current.get('country')!r} -> {country!r}",
    ]
    if not apply:
        result["plan"] = ["DRY RUN — nothing will be written. Re-run with apply=1."] + plan_lines
        return result

    # 5. Write the Company record.
    try:
        frappe.db.set_value("Company", company, updates)
        frappe.db.commit()
        result["applied"].append(
            f"company '{company}': set default_currency={currency!r}, country={country!r}"
        )
    except Exception as exc:  # noqa: BLE001
        result["failed"].append(f"company write failed: {exc}")
        return result

    # 6. Clear the cache so the portal JS picks up the new boot currency
    #    on the next request (frappe.boot.sysdefaults.currency).
    try:
        frappe.clear_cache()
        result["applied"].append("frappe cache cleared")
    except Exception as exc:  # noqa: BLE001
        result["skipped"].append(f"cache clear skipped: {exc}")

    return result


def diff() -> dict:
    """Return the current Company currency/country snapshot for verification."""
    company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
    if not company:
        company = frappe.db.get_value("Company", {}, "name") or ""
    if not company:
        return {"error": "no Company found"}
    row = frappe.db.get_value("Company", company, ["name", "default_currency", "country"], as_dict=True)
    return {
        "company": row.get("name"),
        "default_currency": row.get("default_currency"),
        "country": row.get("country"),
    }


def _write_site_config_currency(currency: str = "USD") -> dict:
    """Write ``lms_currency`` to ``site_config.json`` so the portal shell
    picks it up via ``frappe.conf.get("lms_currency")``.

    This is the second half of the currency reset — ``run()`` sets the
    Company + Global Defaults, this writes the site_config key that
    ``brand.py`` reads as a fallback when the context builder hasn't
    run yet (e.g. on the login page before the user has a session).
    """
    import json
    from pathlib import Path

    currency = (currency or "USD").strip().upper()
    site_config_path = Path(frappe.utils.get_site_path("site_config.json"))
    raw = json.loads(site_config_path.read_text() or "{}")
    raw["lms_currency"] = currency
    site_config_path.write_text(json.dumps(raw, indent=2, sort_keys=True))
    # Also set in the in-memory conf so the current process picks it up.
    frappe.conf["lms_currency"] = currency
    frappe.clear_cache()
    return {"applied": f"site_config.json: lms_currency={currency}"}