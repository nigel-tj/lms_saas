"""Addon registry — admin-toggleable portal extensions.

All addons follow the existing ``site_config`` feature-flag pattern.
Admins enable addons via the **LMS Addon Settings** desk doctype (which
reads/writes the ``lms_addons`` config key) or by editing site_config.json
directly.

Each addon entry in ``ADDON_REGISTRY`` declares:
    key        — the config key under ``lms_addons``
    label      — display name for nav + settings
    icon       — sidebar icon key (matched in base.html SVG set)
    route      — portal URL (``/lms/<key>``)
    nav_group  — optional sidebar group label (``Field`` / ``Ops`` / ``Admin``)
    personas   — list of personas allowed to see/use the addon
    description — short text for the settings page

Usage in portal pages::

    from lms_saas.utils.addons import is_addon_enabled, require_addon

    def get_context(context):
        require_addon("hr_management")
        ...

Usage in API guards::

    from lms_saas.utils.addons import require_addon_api
    @frappe.whitelist()
    def my_endpoint():
        require_addon_api("hr_management")
        ...
"""

from __future__ import annotations

import frappe
from frappe import _


# ---------------------------------------------------------------------------
# Registry — single source of truth for all addon metadata.
# Order = display order in the LMS Addon Settings desk page.
# ---------------------------------------------------------------------------

ADDON_REGISTRY: dict[str, dict] = {
    # ── P0 — Quick wins ──
    "announcements": {
        "label": _("Announcements"),
        "icon": "megaphone",
        "route": "/lms/announcements",
        "nav_group": "Ops",
        "personas": ["Admin", "Branch Manager", "Loan Officer", "Collector"],
        "description": _("Internal announcement board with acknowledgement tracking."),
        "new_doctypes": ["LMS Announcement"],
    },
    "task_management": {
        "label": _("Task Management"),
        "icon": "check-square",
        "route": "/lms/tasks",
        "nav_group": "Ops",
        "personas": ["Admin", "Branch Manager", "Loan Officer", "Collector"],
        "description": _("Kanban task board linked to loans, borrowers, and projects."),
        "new_doctypes": [],
    },
    "document_center": {
        "label": _("Document Center"),
        "icon": "folder",
        "route": "/lms/documents",
        "nav_group": "Ops",
        "personas": ["Admin", "Branch Manager", "Loan Officer", "Collector", "Borrower"],
        "description": _("Centralised document repository with categories and expiry tracking."),
        "new_doctypes": ["LMS Document Category"],
    },
    "helpdesk": {
        "label": _("Support / Helpdesk"),
        "icon": "life-buoy",
        "route": "/lms/support",
        "nav_group": "Ops",
        "personas": ["Admin", "Branch Manager", "Loan Officer", "Collector", "Borrower"],
        "description": _("Borrower ticket system with SLA tracking and complaint escalation."),
        "new_doctypes": [],
    },
    "hr_management": {
        "label": _("HR Management"),
        "icon": "users",
        "route": "/lms/hr",
        "nav_group": "Admin",
        "personas": ["Admin", "Branch Manager"],
        "description": _("Leave approvals, attendance, expense claims, shifts, team directory."),
        "new_doctypes": [],
    },
    # ── P1 — Manager empowerment ──
    "branch_analytics": {
        "label": _("Branch Analytics"),
        "icon": "bar-chart",
        "route": "/lms/analytics",
        "nav_group": "Admin",
        "personas": ["Admin", "Branch Manager"],
        "description": _("Cross-branch KPI comparison, officer leaderboard, trend analysis."),
        "new_doctypes": [],
    },
    "regulatory_hub": {
        "label": _("Regulatory Hub"),
        "icon": "shield",
        "route": "/lms/regulatory",
        "nav_group": "Admin",
        # Branch Managers get a read-only branch summary; generate/save stay admin-only in API.
        "personas": ["Admin", "Branch Manager"],
        "description": _("Centralised regulatory reporting with deadline calendar and archive."),
        "new_doctypes": ["LMS Regulatory Submission"],
    },
    "payroll": {
        "label": _("Payroll"),
        "icon": "wallet",
        "route": "/lms/payroll",
        "nav_group": "Admin",
        "personas": ["Admin", "Branch Manager"],
        "description": _("Payroll runs, payslip distribution, loan deduction tracking."),
        "new_doctypes": [],
    },
    "appraisals": {
        "label": _("Appraisals"),
        "icon": "star",
        "route": "/lms/appraisals",
        "nav_group": "Ops",
        "personas": ["Admin", "Branch Manager", "Loan Officer", "Collector"],
        "description": _("Appraisal cycles, goal setting, KRA scoring, performance feedback."),
        "new_doctypes": [],
    },
    "training": {
        "label": _("Training & Development"),
        "icon": "book-open",
        "route": "/lms/training",
        "nav_group": "Ops",
        "personas": ["Admin", "Branch Manager", "Loan Officer", "Collector"],
        "description": _("Training programs, event registration, feedback, compliance tracking."),
        "new_doctypes": [],
    },
    "recruitment": {
        "label": _("Recruitment"),
        "icon": "user-plus",
        "route": "/lms/recruitment",
        "nav_group": "Admin",
        "personas": ["Admin", "Branch Manager"],
        "description": _("Job openings, applicant tracking, interview scheduling, onboarding."),
        "new_doctypes": [],
    },
    "procurement": {
        "label": _("Procurement"),
        "icon": "shopping-cart",
        "route": "/lms/procurement",
        "nav_group": "Admin",
        "personas": ["Admin", "Branch Manager"],
        "description": _("Purchase requests, PO tracking, supplier directory, spend dashboard."),
        "new_doctypes": [],
    },
    "savings_club": {
        "label": _("Savings Club"),
        "icon": "piggy-bank",
        "route": "/lms/savings",
        "nav_group": "Ops",
        "personas": ["Admin", "Branch Manager", "Loan Officer", "Borrower"],
        "description": _("Group savings goals, voluntary deposits, savings statements, withdrawals."),
        "new_doctypes": ["LMS Savings Goal"],
    },
    "customer_feedback": {
        "label": _("Customer Feedback"),
        "icon": "message-circle",
        "route": "/lms/feedback",
        "nav_group": "Ops",
        "personas": ["Admin", "Branch Manager", "Borrower"],
        "description": _("NPS surveys, post-disbursement feedback, complaint auto-routing."),
        "new_doctypes": ["LMS Survey", "LMS Survey Response"],
    },
    "field_visits": {
        "label": _("Field Visits"),
        "icon": "map-pin",
        "route": "/lms/visits",
        "nav_group": "Field",
        "personas": ["Admin", "Branch Manager", "Loan Officer", "Collector"],
        "description": _("Visit scheduling, geo-tagged check-in, checklists, visit reports."),
        "new_doctypes": ["LMS Field Visit"],
    },
    # ── P2 — Advanced ──
    "inventory": {
        "label": _("Inventory & Assets"),
        "icon": "package",
        "route": "/lms/inventory",
        "nav_group": "Admin",
        "personas": ["Admin", "Branch Manager"],
        "description": _("Asset register, stock items, field equipment checkout, depreciation."),
        "new_doctypes": [],
    },
    "budgeting": {
        "label": _("Budgeting"),
        "icon": "trending-up",
        "route": "/lms/budgeting",
        "nav_group": "Admin",
        "personas": ["Admin", "Branch Manager"],
        "description": _("Branch budgets, budget vs. actual, forecasting, variance analysis."),
        "new_doctypes": [],
    },
    "insurance": {
        "label": _("Insurance"),
        "icon": "umbrella",
        "route": "/lms/insurance",
        "nav_group": "Ops",
        "personas": ["Admin", "Branch Manager", "Loan Officer", "Borrower"],
        "description": _("Loan insurance policies, premium tracking, claims management."),
        "new_doctypes": ["LMS Insurance Policy", "LMS Insurance Claim"],
    },
    "whatsapp": {
        "label": _("WhatsApp Business"),
        "icon": "message-square",
        "route": "/lms/whatsapp",
        "nav_group": "Ops",
        "personas": ["Admin", "Branch Manager", "Loan Officer"],
        "description": _("WhatsApp notifications, two-way messaging, broadcast campaigns."),
        "new_doctypes": ["LMS WhatsApp Template"],
    },
    "wallet_recon": {
        "label": _("Wallet Reconciliation"),
        "icon": "refresh-cw",
        "route": "/lms/reconciliation",
        "nav_group": "Admin",
        "personas": ["Admin", "Branch Manager"],
        "description": _("Mobile money statement import, auto-matching, reconciliation dashboard."),
        "new_doctypes": ["LMS Wallet Statement"],
    },
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _get_addons_config() -> dict:
    """Read the ``lms_addons`` block from site_config (or the LMS Addon Settings singleton)."""
    conf = frappe.conf.get("lms_addons")
    if conf and isinstance(conf, dict):
        return conf
    # Fall back to the desk doctype singleton if site_config is not set.
    try:
        if frappe.db.table_exists("LMS Addon Settings"):
            doc = frappe.get_single("LMS Addon Settings")
            return {row.addon_key: row.enabled for row in (doc.addons or []) if row.addon_key}
    except Exception:
        pass
    return {}


def is_addon_enabled(key: str) -> bool:
    """Return True if the named addon is enabled in site_config."""
    if key not in ADDON_REGISTRY:
        return False
    return bool(_get_addons_config().get(key, False))


def get_enabled_addons() -> list[dict]:
    """Return metadata for all enabled addons (used by nav builder)."""
    conf = _get_addons_config()
    out = []
    for key, spec in ADDON_REGISTRY.items():
        if not conf.get(key, False):
            continue
        out.append({**spec, "key": key})
    return out


def get_all_addon_specs() -> list[dict]:
    """Return metadata for ALL registered addons (used by settings page)."""
    return [{**spec, "key": key} for key, spec in ADDON_REGISTRY.items()]


def get_addons_for_persona(persona: str | None) -> list[dict]:
    """Return enabled addons visible to the given persona."""
    if not persona:
        # Borrowers see borrower-tagged addons even without a staff persona.
        persona = "Borrower"
    enabled = get_enabled_addons()
    return [a for a in enabled if persona in a.get("personas", [])]


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def require_addon(key: str) -> None:
    """Page-level guard: redirect to /lms if the addon is disabled.

    Use in ``www/lms/<addon>.py`` after the Guest check.
    """
    if not is_addon_enabled(key):
        frappe.local.flags.redirect_location = "/lms"
        raise frappe.Redirect


def require_addon_api(key: str) -> None:
    """API-level guard: throw PermissionError if the addon is disabled.

    Use at the top of whitelisted API methods.
    """
    if not is_addon_enabled(key):
        frappe.throw(
            _("{} addon is not enabled on this site.").format(
                ADDON_REGISTRY.get(key, {}).get("label", key)
            ),
            frappe.PermissionError,
        )


def require_addon_persona(key: str) -> None:
    """Combined guard: addon enabled + current persona is allowed.

    Admins (System Manager / Administrator) always pass.
    """
    require_addon_api(key)

    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)

    roles = set(frappe.get_roles())
    if roles.intersection({"System Manager", "Administrator"}):
        return

    spec = ADDON_REGISTRY.get(key, {})
    allowed_personas = spec.get("personas", [])

    # Borrower addons: check via is_portal_borrower
    if "Borrower" in allowed_personas:
        from lms_saas.utils.portal import is_portal_borrower
        if is_portal_borrower():
            return

    # Staff addons: check via persona resolver
    from lms_saas.utils.portal import resolve_portal_persona
    persona = resolve_portal_persona()
    if persona and persona in allowed_personas:
        return

    frappe.throw("Not permitted", frappe.PermissionError)


_NAV_GROUP_ORDER = {"Field": 0, "Ops": 1, "Admin": 2}


def addon_nav_items(persona: str | None = None) -> list[dict]:
    """Build nav items for enabled addons matching the persona.

    Returns a list of ``{key, label, route, icon, group?}`` dicts suitable for
    ``_build_lms_nav`` in ``utils/brand.py``. Items are ordered by ``nav_group``
    (Field → Ops → Admin) then registry order within each group.
    """
    addons = get_addons_for_persona(persona)
    addons = sorted(
        addons,
        key=lambda a: (_NAV_GROUP_ORDER.get(a.get("nav_group") or "", 99),),
    )
    items = []
    for a in addons:
        item = {
            "key": a["key"],
            "label": a["label"],
            "route": a["route"],
            "icon": a["icon"],
        }
        if a.get("nav_group"):
            item["group"] = a["nav_group"]
        items.append(item)
    return items