import frappe

from lms_saas.utils.brand import get_brand_favicon_url, get_brand_splash_url, get_lms_theme
from lms_saas.install import LOAN_DASHBOARD_NAME
from lms_saas.utils.desk_nav import get_lms_desk_nav
from lms_saas.utils.help import get_lms_help_menu

LMS_DESK_ROLES = {"LMS Admin", "LMS Branch Manager", "LMS Loan Officer", "LMS Collector"}
LOAN_DASHBOARD_ROUTE = f"dashboard-view/{LOAN_DASHBOARD_NAME}"


def apply_default_route(bootinfo):
    """Route LMS staff to Lending home (sidebar); Loan Dashboard is linked from the workspace."""
    bootinfo.lms_theme = get_lms_theme()
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
        # Lending home keeps the native workspace sidebar; Loan Dashboard stays one click away.
        bootinfo.default_route = "loans"
        bootinfo.lms_loan_dashboard_route = LOAN_DASHBOARD_ROUTE
        return

    # Non-desk customer users can still use the portal entrypoint.
    if "Customer" in roles and "Desk User" not in roles:
        bootinfo.portal_default_route = "/lms"
