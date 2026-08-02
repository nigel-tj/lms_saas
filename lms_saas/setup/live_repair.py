"""Idempotent live-site repair for LMS parity and role/home-page drift.

Use this when a site was created or upgraded before the parity fixes were in place.
It self-heals the common production issues without assuming the site was created
fresh.

Run:
  bench --site <site> execute lms_saas.setup.live_repair.repair_live_site_state
"""

from __future__ import annotations

import frappe

LEGACY_LMS_ROLES = (
    "LMS Admin",
    "LMS Branch Manager",
    "LMS Loan Officer",
    "LMS Collector",
)


def _repair_legacy_user_roles() -> dict[str, int | list[str]]:
    """Remove stale legacy LMS roles from user assignments.

    These roles were retired in favor of the admin-only desk model and the
    portal-only LMS Portal Staff role. This step is safe to re-run and only
    touches user-role rows that still reference the retired names.
    """
    removed = 0
    touched_users: list[str] = []

    for role in LEGACY_LMS_ROLES:
        if not frappe.db.exists("Role", role):
            continue
        rows = frappe.get_all(
            "Has Role",
            filters={"role": role, "parenttype": "User"},
            fields=["name", "parent"],
        )
        for row in rows:
            frappe.db.delete("Has Role", {"name": row["name"]})
            removed += 1
            if row.get("parent") and row["parent"] not in touched_users:
                touched_users.append(row["parent"])

    frappe.db.commit()
    return {"removed_rows": removed, "touched_users": touched_users}


def _diagnose_user_setup() -> dict:
    """Capture a diagnostic trail for users that should be wired for desk/portal access."""
    from lms_saas.install import ADMIN_ROLES, SYS_ROLE, PORTAL_STAFF_ROLE

    issues: list[dict] = []
    for role_name in (SYS_ROLE, PORTAL_STAFF_ROLE, *ADMIN_ROLES):
        if not frappe.db.exists("Role", role_name):
            issues.append({"type": "missing_role", "role": role_name})

    users = frappe.get_all("User", filters={"enabled": 1}, fields=["name", "email", "user_type"])
    for user in users:
        if user.get("name") in {"Administrator", "Guest"}:
            continue
        roles = set(frappe.get_roles(user["name"]))
        if not roles:
            issues.append({"type": "no_roles", "user": user["name"]})
            continue
        if PORTAL_STAFF_ROLE in roles and any(role in roles for role in ADMIN_ROLES):
            issues.append({"type": "mixed_roles", "user": user["name"], "roles": sorted(roles)})

    return {"ok": not issues, "issues": issues, "user_count": len(users)}


def _repair_user_setup(diagnostic: dict) -> dict:
    """Repair the most common user-setup drift without changing business semantics."""
    from lms_saas.install import ADMIN_ROLES, PORTAL_STAFF_ROLE

    repairs: list[dict] = []
    for issue in diagnostic.get("issues", []):
        if issue.get("type") == "missing_role":
            role_name = issue["role"]
            if not frappe.db.exists("Role", role_name):
                frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)
                repairs.append({"type": "created_role", "role": role_name})
        elif issue.get("type") == "mixed_roles":
            user_name = issue["user"]
            user_roles = set(frappe.get_roles(user_name))
            if PORTAL_STAFF_ROLE in user_roles:
                user_roles.discard(PORTAL_STAFF_ROLE)
            if any(role in user_roles for role in ADMIN_ROLES):
                repairs.append({"type": "normalized_roles", "user": user_name, "roles": sorted(user_roles)})
                for role in sorted(user_roles):
                    frappe.get_doc("User", user_name).add_roles(role)

    frappe.db.commit()
    return {"repairs": repairs}


def repair_live_site_state() -> dict:
    """Run the live-site self-heal sequence in a safe, idempotent order."""
    from lms_saas.install import (
        after_install as run_install_bootstrap,
        _reconcile_loan_dashboard,
        _set_admin_home_page,
        _set_portal_role_home_pages,
        _setup_navbar_branding,
    )

    diagnostic = _diagnose_user_setup()
    repairs = _repair_user_setup(diagnostic)
    run_install_bootstrap()
    role_repair = _repair_legacy_user_roles()
    _reconcile_loan_dashboard()
    _set_admin_home_page()
    _set_portal_role_home_pages()
    _setup_navbar_branding()

    frappe.db.commit()
    return {
        "ok": True,
        "diagnostic": diagnostic,
        "user_repairs": repairs,
        "role_repair": role_repair,
        "notes": [
            "Ran after_install bootstrap and self-heal hooks",
            "Removed retired legacy roles from user assignments",
            "Re-applied admin and portal home-page routing",
            "Re-applied navbar and branding settings",
            "Captured and repaired user-setup diagnostics",
        ],
    }


def run_live_repair() -> dict:
    """Compatibility entry-point used by bench execute."""
    return repair_live_site_state()
