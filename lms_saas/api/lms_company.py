"""Company resolution helper — explicit per-site override, vendor-neutral.

R23-Q5-M1: ``frappe.db.get_single_value("Global Defaults", "default_company")``
was used in 19+ files to find the operator's Company. The helper hid the
assumption that there is ONE Company per site (the operator's stated
"one site, one client" model). A future maintainer adding multi-company
to a single site would silently get the wrong Company.

This module exposes a single ``get_lms_company()`` helper that:

1. Reads ``lms_company`` from site_config (operator override) if set.
2. Falls back to ``Global Defaults.default_company`` (the existing behaviour).
3. Falls back to the first Company record (the existing fallback).

The helper is used in every API that needs a Company record. Refactor
all ``frappe.db.get_single_value("Global Defaults", "default_company")``
call sites to use this helper — see R23-Q5-M1 in the board review.
"""

from __future__ import annotations

import frappe


def get_lms_company() -> str | None:
    """Return the Company for the current site.

    Resolution order (first hit wins):
      1. ``lms_company`` site_config (operator override)
      2. ``Global Defaults.default_company`` (the existing behaviour)
      3. The first Company record on the site
    """
    override = (frappe.conf.get("lms_company") or "").strip()
    if override:
        if frappe.db.exists("Company", override):
            return override
        # Override is set but invalid — log and fall through.
        frappe.log_error(
            title="LMS lms_company override points at non-existent Company",
            message=f"lms_company={override!r} not found in Company",
        )
    try:
        default = frappe.db.get_single_value("Global Defaults", "default_company")
        if default:
            return default
    except Exception:
        pass
    try:
        return frappe.db.get_value("Company", {}, "name")
    except Exception:
        return None
