"""Borrower portal helpers — menu lockdown, website context, persona guard."""

from __future__ import annotations

import importlib.util
import os

import frappe

# ERPNext seeds these for Customer; LMS borrowers only need loan self-service.
ERPNext_CUSTOMER_PORTAL_ROUTES = (
	"/project",
	"/quotations",
	"/orders",
	"/invoices",
	"/shipments",
	"/issues",
	"/addresses",
	"/timesheets",
	"/material-requests",
	"/newsletters",
)

LMS_BORROWER_PORTAL_ROUTES = (
	"/lms",
	"/lms/account",
)

LEGACY_ACCOUNT_PATHS = (
	"me",
	"update-profile",
	"update-password",
	"third_party_apps",
)


DESK_ADMIN_ROLES = frozenset({"System Manager", "Administrator"})


def resolve_portal_persona(user: str | None = None) -> str | None:
	"""Resolve the LMS persona for the current (or given) portal staff user.

	Reads ``Employee.custom_lms_persona`` (set during LMS User Setup onboarding).
	Returns one of: ``"Loan Officer"``, ``"Branch Manager"``, ``"Collector"``,
	or ``None`` if the user is not portal staff or has no persona set.
	"""
	import frappe

	from lms_saas.install import PORTAL_STAFF_ROLE

	user = user or frappe.session.user
	if not user or user == "Guest":
		return None

	roles = set(frappe.get_roles(user))
	if PORTAL_STAFF_ROLE not in roles:
		return None

	employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	if not employee:
		return None

	if frappe.get_meta("Employee").has_field("custom_lms_persona"):
		return frappe.db.get_value("Employee", employee, "custom_lms_persona") or None
	return None


def is_portal_borrower(user: str | None = None) -> bool:
	"""Website-only Customer (no desk admin roles)."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False

	roles = set(frappe.get_roles(user))
	if "Customer" not in roles:
		return False
	if roles & DESK_ADMIN_ROLES:
		return False
	if "Desk User" in roles:
		return False
	return True


def show_staff_desk_link(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	roles = set(frappe.get_roles(user))
	return bool(roles & DESK_ADMIN_ROLES)


def prune_customer_portal_menu() -> dict:
	"""Disable ERPNext portal clutter; keep LMS borrower routes only.

	Also seeds a portal menu item for the collector PWA, visible to the
	portal-only LMS Portal Staff role (Loan Officers / Collectors).
	"""
	from lms_saas.install import PORTAL_STAFF_ROLE

	disabled = 0
	settings = frappe.get_doc("Portal Settings", "Portal Settings")

	for row in settings.menu:
		if row.role != "Customer":
			continue
		if row.route in ERPNext_CUSTOMER_PORTAL_ROUTES:
			row.enabled = 0
			disabled += 1
		elif row.route in LMS_BORROWER_PORTAL_ROUTES:
			row.enabled = 1

	_ensure_portal_item(settings, "My Loans", "/lms", "Loan")
	_ensure_portal_item(settings, "My Account", "/lms/account", "User")
	_ensure_staff_portal_item(settings, "Collection Run", "/lms/collect", PORTAL_STAFF_ROLE)
	_ensure_staff_portal_item(settings, "Officer", "/lms/officer", PORTAL_STAFF_ROLE)
	_ensure_staff_portal_item(settings, "Manager", "/lms/manager", PORTAL_STAFF_ROLE)

	settings.default_portal_home = "/lms"
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)

	frappe.clear_cache()
	return {"disabled": disabled}


def _ensure_portal_item(settings, title: str, route: str, reference_doctype: str | None) -> None:
	for row in settings.menu:
		if row.route == route and row.role == "Customer":
			row.enabled = 1
			row.title = title
			if reference_doctype:
				row.reference_doctype = reference_doctype
			return

	row = {
		"title": title,
		"enabled": 1,
		"route": route,
		"role": "Customer",
	}
	if reference_doctype:
		row["reference_doctype"] = reference_doctype
	settings.append("menu", row)


def _ensure_staff_portal_item(settings, title: str, route: str, role: str) -> None:
	"""Seed a portal menu item for a staff role (e.g. LMS Portal Staff)."""
	for row in settings.menu:
		if row.route == route and row.role == role:
			row.enabled = 1
			row.title = title
			return

	settings.append(
		"menu",
		{
			"title": title,
			"enabled": 1,
			"route": route,
			"role": role,
		},
	)


def apply_borrower_web_context(context) -> None:
	"""Strip ERPNext portal chrome for website-only borrowers on legacy account pages."""
	if not is_portal_borrower():
		return

	path = (getattr(frappe.local, "path", None) or "").strip("/")
	if not path:
		path = (getattr(context, "pathname", None) or context.get("pathname") or context.get("path") or "").strip("/")

	is_legacy = any(path == legacy or path.startswith(f"{legacy}/") for legacy in LEGACY_ACCOUNT_PATHS)
	if not is_legacy and not path.startswith("lms"):
		return

	context.show_sidebar = False
	context.no_header = True
	body = (context.get("body_class") if isinstance(context, dict) else getattr(context, "body_class", None)) or ""
	merged = f"{body} lms-portal lms-portal-borrower lms-themed lms-portal-legacy".strip()
	if isinstance(context, dict):
		context["body_class"] = merged
		context["lms_portal_legacy"] = True
	else:
		context.body_class = merged
		context.lms_portal_legacy = True


# ---------------------------------------------------------------------------
# Phase 4.4 — Persona-aware permission helpers
#
# The portal nav (templates/lms_portal/base.html) and the page-level guards
# (www/lms/{manager,officer,collect}.py) share one bitmask per user. Persona
# is derived from Employee.custom_lms_persona + the user's Frappe roles.
# ---------------------------------------------------------------------------

PERSONA_LANDING = {
	"Admin": "/desk",
	"Borrower": "/lms",
	"Loan Officer": "/lms/officer",
	"Branch Manager": "/lms/manager",
	"Collector": "/lms/collect",
}


def _user_can(perm: str) -> bool:
	"""Return True if the current user has the named permission.

	Mirrors utils/brand.py:_get_user_permissions. Used by page-level guards
	and API guards that need a one-shot predicate (no context object).
	"""
	if frappe.session.user == "Guest":
		return False
	from lms_saas.utils.brand import _get_user_persona, _get_user_permissions

	persona = _get_user_persona()
	roles = set(frappe.get_roles())
	perms = _get_user_permissions(persona, roles)
	return bool(perms.get(perm))


def require_persona_for_page(perm: str):
	"""Raise frappe.Redirect to the user's persona-appropriate landing.

	Use after the Guest check in www/lms/*.py. If the user does not have
	``perm`` (e.g. can_manager), send them to their persona's home page
	instead of letting them see a 403 / blank dashboard.
	"""
	if frappe.session.user == "Guest" or frappe.session.user == "Administrator":
		return
	if _user_can(perm):
		return
	from lms_saas.utils.brand import _get_user_persona

	persona = _get_user_persona() or ""
	landing = PERSONA_LANDING.get(persona, "/lms")
	frappe.local.flags.redirect_location = landing
	raise frappe.Redirect


# ---------------------------------------------------------------------------
# Loader for the hyphen-named www/lms-portal/mixins.py (Python can't import
# modules whose path contains a dash). The file is loaded by file path and
# the resulting module is cached on the function. Pre-existing pages at
# www/lms-portal/{officer,collector}.py call this loader instead of
# ``from lms_saas.www.lms_portal.mixins import ...`` (which is broken).
# ---------------------------------------------------------------------------

_LMS_PORTAL_MIXINS = None


def _load_lms_portal_mixins():
	"""Load www/lms-portal/mixins.py (hyphen path) via importlib."""
	global _LMS_PORTAL_MIXINS
	if _LMS_PORTAL_MIXINS is not None:
		return _LMS_PORTAL_MIXINS
	mixins_path = os.path.join(
		frappe.get_app_path("lms_saas", "www", "lms-portal", "mixins.py")
	)
	if not os.path.exists(mixins_path):
		_lms_portal_mixins = None
		return None
	spec = importlib.util.spec_from_file_location(
		"lms_saas_www_lms_portal_mixins", mixins_path
	)
	if not spec or not spec.loader:
		_lms_portal_mixins = None
		return None
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	_lms_portal_mixins = module
	return module
