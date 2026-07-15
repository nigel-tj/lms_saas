"""LMS Addon Settings — single doctype for toggling portal addons."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class LMSAddonSettings(Document):
	pass


def on_update(doc, method=None):
    """Sync addon toggles to site_config.lms_addons on save."""
    addons = {}
    for row in (doc.addons or []):
        if row.addon_key:
            addons[row.addon_key] = bool(row.enabled)

    # Write to site_config so is_addon_enabled() can read it without DB queries.
    import json, os
    site_config_path = os.path.join(frappe.get_site_path(), "site_config.json")
    try:
        with open(site_config_path) as f:
            conf = json.load(f)
        conf["lms_addons"] = addons
        with open(site_config_path, "w") as f:
            json.dump(conf, f, indent=2)
    except Exception:
        pass
    frappe.local.conf["lms_addons"] = addons


def populate_addon_rows(doc, method=None):
    """Ensure all registered addons have a row in the settings table.

    Called on load / after_insert so new addons added to the registry
    appear automatically.
    """
    from lms_saas.utils.addons import ADDON_REGISTRY

    existing_keys = {row.addon_key for row in (doc.addons or [])}
    conf = frappe.conf.get("lms_addons") or {}

    for key, spec in ADDON_REGISTRY.items():
        if key in existing_keys:
            continue
        doc.append(
            "addons",
            {
                "addon_key": key,
                "addon_label": str(spec.get("label", key)),
                "description": str(spec.get("description", "")),
                "enabled": bool(conf.get(key, False)),
            },
        )


@frappe.whitelist()
def sync_addon_rows():
    """Re-populate addon rows from the registry (call after app upgrade)."""
    doc = frappe.get_single("LMS Addon Settings")
    populate_addon_rows(doc)
    doc.flags.ignore_permissions = True
    doc.save()
    return {"ok": True, "count": len(doc.addons or [])}