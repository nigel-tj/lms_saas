import frappe

from lms_saas.utils.brand import enrich_brand, get_brand_favicon_url, get_brand_splash_url, get_lms_theme
from lms_saas.install import LOAN_DASHBOARD_NAME, ROLE_LANDING_ROUTES
from lms_saas.utils.desk_nav import get_lms_desk_nav
from lms_saas.utils.frappe_version import LENDING_HOME_SLUG, desk_prefix, get_major_version
from lms_saas.utils.help import get_lms_help_menu

LMS_DESK_ROLES = {"LMS Admin", "LMS Branch Manager", "LMS Loan Officer", "LMS Collector"}
LOAN_DASHBOARD_ROUTE = f"dashboard-view/{LOAN_DASHBOARD_NAME}"

# Role → workspace title (used by get_lms_home_page to build the slugified URL).
# Kept in sync with ROLE_LANDING_ROUTES in install.py (single source of truth).
ROLE_WORKSPACE_TITLES = {
    "LMS Admin": "Loan Management",
    "LMS Branch Manager": "Loans & Disbursements",
    "LMS Loan Officer": "Applications",
    "LMS Collector": "Collections",
}


def _resolve_desk_landing(roles):
    """Pick the most relevant landing workspace for the signed-in user's role.

    Priority: a specific LMS role landing > Lending home > desk root. This means
    a Collector lands on Collections, a Loan Officer on Applications, etc. — each
    persona sees their primary workspace immediately instead of hunting for it.
    """
    # Admin gets the portfolio overview (Loan Management workspace).
    if "LMS Admin" in roles or "System Manager" in roles or "Administrator" in roles:
        return ROLE_LANDING_ROUTES.get("LMS Admin", LENDING_HOME_SLUG)
    if "LMS Branch Manager" in roles:
        return ROLE_LANDING_ROUTES.get("LMS Branch Manager", LENDING_HOME_SLUG)
    if "LMS Loan Officer" in roles:
        return ROLE_LANDING_ROUTES.get("LMS Loan Officer", LENDING_HOME_SLUG)
    if "LMS Collector" in roles:
        return ROLE_LANDING_ROUTES.get("LMS Collector", LENDING_HOME_SLUG)
    return LENDING_HOME_SLUG


def apply_default_route(bootinfo):
    """Route LMS staff to their role-specific workspace; Loan Dashboard is one click away."""
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
    desk_staff = roles.intersection(LMS_DESK_ROLES) or roles.intersection({"System Manager", "Administrator"})
    if desk_staff:
        # Each persona lands on the workspace that matters most to their job.
        bootinfo.default_route = _resolve_desk_landing(roles)
        bootinfo.lms_loan_dashboard_route = LOAN_DASHBOARD_ROUTE
        return

    # Non-desk customer users land on the borrower portal, not the desk.
    if "Customer" in roles and "Desk User" not in roles:
        bootinfo.portal_default_route = "/lms"


def get_lms_home_page(user=None):
    """Hook: get_website_user_home_page — return the correct post-login URL.

    Frappe's get_home_page() checks Portal Settings.default_portal_home (/lms) for
    ALL users, which sends desk staff to the borrower portal. This hook wins over
    that default and returns the slugified desk workspace URL for desk staff, and
    /lms for borrowers. Called by get_home_page_via_hooks() before the portal
    default is consulted.
    """
    user = user or frappe.session.user
    if not user or user == "Guest":
        return None

    roles = set(frappe.get_roles(user))

    # Desk staff → their role-specific workspace (slugified, /desk/ prefixed).
    if roles.intersection(LMS_DESK_ROLES) or roles.intersection({"System Manager", "Administrator"}):
        from frappe.desk.utils import slug

        for role, title in ROLE_WORKSPACE_TITLES.items():
            if role in roles:
                return f"{desk_prefix()}/{slug(title)}"
        # System Manager / Administrator with no LMS role → Lending home.
        return f"{desk_prefix()}/{LENDING_HOME_SLUG}"

    # Borrowers → portal.
    if "Customer" in roles:
        return "/lms"

    return None
