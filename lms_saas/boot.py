import frappe
import frappe.apps
import frappe.auth as _frappe_auth

from lms_saas.utils.brand import enrich_brand, get_brand_favicon_url, get_brand_splash_url, get_lms_theme, resolve_operator_app_name
from lms_saas.install import LOAN_DASHBOARD_NAME, PORTAL_STAFF_ROLE
from lms_saas.utils.desk_nav import get_lms_desk_nav
from lms_saas.utils.frappe_version import LENDING_HOME_SLUG, desk_prefix, get_major_version
from lms_saas.utils.help import get_lms_help_menu


# ---------------------------------------------------------------------------
# Patch Frappe's get_default_path so LMS portal users (Website Users with the
# Customer role) bypass the /desk fallback on login.
#
# Context (R54 / R35-#24 / R35-#26): Frappe's auth.make_session resolves the
# post-login home_page for Website Users as
#
#     get_default_path() or "/" + get_home_page()
#
# For multi-app installs (erpnext + lms_saas + lending + hrms), get_default_path
# returns /desk unconditionally because is_desk_apps(_apps) is True. That
# short-circuits the `or` and our get_website_user_home_page hook — wired
# through get_home_page() — never runs. The borrower (Website User) lands on
# /desk/loan_management, which is the LMS workspace, NOT the borrower
# portal at /lms.
#
# Fix: monkey-patch get_default_path to return None for LMS portal users. The
# `or` then falls through to "/" + get_home_page() which calls our hook and
# returns /lms.
#
# This monkey-patch is guarded: it only fires when the session user has a
# portal role. For System Users (Loan Officers / Managers / Collectors /
# Admins), the original get_default_path is preserved so the desk behavior
# is unchanged.
#
# `frappe.auth` does `from frappe.apps import get_default_path` at module
# load time, so it has its OWN reference to the function. We patch both
# bindings so the patch fires regardless of which module calls it.
# ---------------------------------------------------------------------------
_original_get_default_path = frappe.apps.get_default_path


def _patched_get_default_path():
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		return None
	try:
		roles = set(frappe.get_roles(user))
	except Exception:
		roles = set()
	# LMS portal users: skip the desk fallback so the home_page resolves
	# through get_home_page() → get_website_user_home_page hook → /lms.
	if roles & {"Customer", "LMS Portal Staff"}:
		return None
	return _original_get_default_path()


frappe.apps.get_default_path = _patched_get_default_path
# Also patch the local reference in frappe.auth (captured via `from X import Y`)
_frappe_auth.get_default_path = _patched_get_default_path

# Admin landing workspace (slugified desk route for System Manager / Administrator).
ADMIN_LANDING_ROUTE = "loan-management"
LOAN_DASHBOARD_ROUTE = f"dashboard-view/{LOAN_DASHBOARD_NAME}"


def _is_desk_admin(roles):
    """True if the user has System Manager or Administrator role (desk admin)."""
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _apply_operator_app_name(bootinfo):
    """R32: override the desk navbar / login title to the operator's brand.

    Frappe's desk chrome reads ``bootinfo.app_name`` (mirrored from
    ``frappe.conf["app_name"]`` / ``hooks.app_title``) for the navbar wordmark
    and the login page. ``hooks.app_title`` is a build-time constant and
    can't be runtime-overridden per site, so WITHOUT this hook every install
    of ``lms_saas`` shows the build-time default brand in the desk chrome
    — even if the operator configured ``lms_brand_portal_title`` to a
    different brand.

    We follow the R23 board's recommended pattern (R23 §fix-list Q1-H1 /
    Q2-H1): the operator's brand is resolved per-request from
    ``lms_app_title`` (preferred; explicit override) or
    ``lms_brand_portal_title`` (the unified brand key), then stamped onto
    ``bootinfo.app_name``, ``frappe.conf["app_name"]``, and
    ``frappe.local.app_name``. The fallback chain is:
      1. ``lms_app_title`` site_config — explicit per-site override
      2. ``lms_brand_portal_title`` site_config — the unified brand key
      3. None — leave the build-time value (don't override)
    """
    app_name = resolve_operator_app_name()
    if not app_name:
        return
    bootinfo.app_name = app_name
    # Mirror onto the request-local + conf so any module that reads these
    # BEFORE Frappe serialises the bootinfo (e.g. navbar templates that
    # check site config during the same boot pass) sees the override.
    frappe.conf["app_name"] = app_name
    # frappe.local is a SiteLocal that may or may not carry an app_name
    # attribute depending on the request path. Set it unconditionally so
    # later code (e.g. navbar templates that read frappe.local.app_name
    # during the same boot pass) sees the override.
    if hasattr(frappe, "local"):
        frappe.local.app_name = app_name


def apply_default_route(bootinfo):
    """Route desk admins to the Loan Management workspace; borrowers to the portal."""
    # R32: must run BEFORE any code that reads app_name / bootinfo.app_name
    # so the navbar wordmark is correct on the first render.
    _apply_operator_app_name(bootinfo)

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


def on_login(login_manager=None):
	"""Frappe ``on_login`` hook — defensive belt-and-braces guard.

	The primary fix for the borrower /desk/lending redirect (issues R35-#24
	and R35-#26) is the ``get_default_path`` monkey-patch at module import
	time above. That patch makes ``get_default_path()`` return None for LMS
	portal users, so the ``or`` in Frappe's ``auth.make_session`` falls
	through to ``"/" + get_home_page()`` which calls our
	``get_website_user_home_page`` hook and resolves to ``/lms``.

	This hook provides an additional safety net: it sets
	``frappe.local.response["home_page"]`` to the persona-based landing URL
	in case the response is left at a non-LMS path by some Frappe upgrade.
	"""
	user = getattr(login_manager, "user", None) or getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		return

	# Defensive: never let the response resolve to the broken /desk/lending
	# URL (no Workspace at that slug in v15+). Point at the persona landing.
	current = (frappe.local.response.get("home_page") or "").strip("/")
	if current == "desk/lending":
		frappe.local.response["home_page"] = None

	target = get_lms_home_page(user=user)
	if target:
		frappe.local.response["home_page"] = target
