import frappe

from lms_saas.utils.brand import enrich_brand, get_brand_favicon_url, get_brand_splash_url, get_lms_theme
from lms_saas.install import LOAN_DASHBOARD_NAME, PORTAL_STAFF_ROLE
from lms_saas.utils.desk_nav import get_lms_desk_nav
from lms_saas.utils.frappe_version import LENDING_HOME_SLUG, desk_prefix, get_major_version
from lms_saas.utils.help import get_lms_help_menu

# Admin landing workspace (slugified desk route for System Manager / Administrator).
ADMIN_LANDING_ROUTE = "loan-management"
LOAN_DASHBOARD_ROUTE = f"dashboard-view/{LOAN_DASHBOARD_NAME}"


def _is_desk_admin(roles):
    """True if the user has System Manager or Administrator role (desk admin)."""
    return bool(roles.intersection({"System Manager", "Administrator"}))


def apply_default_route(bootinfo):
    """Route desk admins to the Loan Management workspace; borrowers to the portal."""
    from lms_saas.utils.portal import install_desk_gate
    install_desk_gate()

    brand = enrich_brand()
    bootinfo.lms_portal_title = brand.get("portal_title")
    bootinfo.lms_theme = get_lms_theme()
    bootinfo.lms_desk_prefix = desk_prefix()
    bootinfo.lms_frappe_major = get_major_version()
    favicon = get_brand_favicon_url()
    bootinfo.lms_favicon_url = favicon
    bootinfo.favicon = favicon
    bootinfo.splash_image = get_brand_splash_url()
    user = frappe.session.user
    if not user or user == "Guest":
        return

    bootinfo.lms_desk_nav = get_lms_desk_nav(user)
    bootinfo.lms_help_menu = get_lms_help_menu(user)

    roles = set(frappe.get_roles(user))
    if _is_desk_admin(roles):
        # Admins land on the Loan Management workspace (portfolio overview + KPIs).
        bootinfo.default_route = ADMIN_LANDING_ROUTE
        bootinfo.lms_loan_dashboard_route = LOAN_DASHBOARD_ROUTE
        return

    # Non-desk customer users land on the borrower portal, not the desk.
    if "Customer" in roles and "Desk User" not in roles:
        bootinfo.portal_default_route = "/lms"
        # Also force the default route — Frappe's get_home_page(user) falls
        # through to Portal Settings / Role.home_page, which is the desk.
        # Setting default_route here is what the web_logout redirect and the
        # Frappe desk sidebar actually consult.
        bootinfo.default_route = "lms"

    # Portal staff (Loan Officers, Collectors, Branch Managers) land on persona-based portal page.
    if PORTAL_STAFF_ROLE in roles and not _is_desk_admin(roles):
        bootinfo.portal_default_route = _portal_staff_landing(user)
        # Mirror the persona landing into default_route so post-login redirect
        # hits the right page (Frappe's home_page resolver checks default_route
        # before Portal Settings).
        persona_route = _portal_staff_landing(user).lstrip("/")
        bootinfo.default_route = persona_route

    # ── Addon routes ──
    # Expose enabled addon metadata in the boot payload so the portal JS
    # can dynamically render addon pages without a server round-trip.
    try:
        from lms_saas.utils.addons import get_enabled_addons
        bootinfo.lms_addons = get_enabled_addons()
    except Exception:
        bootinfo.lms_addons = []


def get_lms_home_page(user=None):
    """Hook: get_website_user_home_page — return the correct post-login URL.

    Desk admins → /app/loan-management (the admin landing workspace).
    Borrowers → /lms (the borrower portal).
    Others → None (falls through to Frappe default).
    """
    user = user or frappe.session.user
    if not user or user == "Guest":
        return None

    roles = set(frappe.get_roles(user))

    # Desk admins → Loan Management workspace.
    if _is_desk_admin(roles):
        from frappe.desk.utils import slug

        return f"{desk_prefix()}/{slug('Loan Management')}"

    # Portal staff (Loan Officers, Collectors, Branch Managers) → persona-based portal page.
    # Must be evaluated before the Customer check since many staff users also carry Customer.
    if PORTAL_STAFF_ROLE in roles:
        return _portal_staff_landing(user)

    # Borrowers → portal.
    if "Customer" in roles:
        return "/lms"

    return None


def _portal_staff_landing(user: str) -> str:
    """Route portal staff to the correct page based on their LMS persona.

    The persona is resolved from the Employee record's ``custom_lms_persona``
    custom field (set during LMS User Setup onboarding). Falls back to
    ``/lms/collect`` if the field is not set.
    """
    employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
    persona = None
    if employee:
        # Check if the custom field exists on Employee
        if frappe.get_meta("Employee").has_field("custom_lms_persona"):
            persona = frappe.db.get_value("Employee", employee, "custom_lms_persona")

    routes = {
        "Loan Officer": "/lms/officer",
        "Branch Manager": "/lms/manager",
        "Collector": "/lms/collect",
    }
    return routes.get(persona, "/lms/collect")
