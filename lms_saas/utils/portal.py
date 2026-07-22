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
	landing = PERSONA_LANDING.get(persona)
	if not landing:
		from lms_saas.install import PORTAL_STAFF_ROLE

		roles = set(frappe.get_roles())
		landing = "/lms/manager" if PORTAL_STAFF_ROLE in roles else "/lms"
	frappe.local.flags.redirect_location = landing
	raise frappe.Redirect


def require_persona(persona: str):
	"""Strict persona guard for a single persona's page.

	Unlike ``require_persona_for_page`` (which accepts any user with the
	``can_<persona>`` permission, including Desk Users and admins), this
	helper requires the user's actual persona to be ``persona`` exactly.
	Use for sensitive workflows — Books & Import, PII, financial data —
	where the persona's branch scope, not the role, gates access.

	Guests and the Administrator are passed through; everyone else is sent
	to their persona landing if it does not match.
	"""
	if frappe.session.user == "Guest" or frappe.session.user == "Administrator":
		return
	from lms_saas.utils.brand import _get_user_persona

	current = _get_user_persona() or ""
	if current == persona:
		return
	# Send to the user's own persona landing, or the borrower portal.
	landing = PERSONA_LANDING.get(current) or "/lms"
	frappe.local.flags.redirect_location = landing
	raise frappe.Redirect


def _persona_permissions(persona: str | None, roles: set) -> dict:
	"""Alias for mixins/tests — same bitmask as brand._get_user_permissions."""
	from lms_saas.utils.brand import _get_user_permissions

	return _get_user_permissions(persona, roles)


# ---------------------------------------------------------------------------
# Desk-route guard
# ---------------------------------------------------------------------------
# Portal staff and borrowers must never see the Frappe desk. If they hit any
# /desk/* or /app/* URL directly (typed URL, old bookmark, deep link from a
# report), bounce them to their persona landing. This is the single point of
# truth for that redirect so docs and code stay aligned.
_DESK_PATH_PREFIXES = ("/desk", "/app")


def _portal_staff_landing_for_request(user: str) -> str:
	"""Same routing as boot._portal_staff_landing, but tolerant of older helpers."""
	from lms_saas.install import PORTAL_STAFF_ROLE
	from lms_saas.utils.brand import _get_user_persona

	persona = _get_user_persona(user)
	routes = {
		"Loan Officer": "/lms/officer",
		"Branch Manager": "/lms/manager",
		"Collector": "/lms/collect",
	}
	landing = routes.get(persona or "")
	if landing:
		return landing
	# Portal staff with no persona → /lms/manager is the safe default.
	if PORTAL_STAFF_ROLE in set(frappe.get_roles(user)):
		return "/lms/manager"
	return "/lms"


def guard_desk_route():
	"""Request hook: bounce non-admin users off /desk and /app to the portal.

	Returns nothing; sets ``frappe.local.response`` to a 302 redirect when the
	current request is a desk URL. Hooked in hooks.py as ``on_request`` so
	every web request runs through it. Uses the response dict (not a raised
	exception) so Frappe writes a clean 302 instead of treating the redirect
	as an unhandled error.
	"""
	user = frappe.session.user
	if not user or user == "Guest" or user == "Administrator":
		return

	# Admins may go anywhere.
	roles = set(frappe.get_roles(user))
	if roles.intersection({"System Manager", "Administrator"}):
		return

	path = (getattr(frappe.local, "path", None) or "").strip().lower()
	if not path:
		return
	if not any(path == prefix or path.startswith(prefix + "/") for prefix in _DESK_PATH_PREFIXES):
		return

	# Allow Frappe's own /api/* endpoints — they don't render desk chrome.
	if path.startswith("/api/"):
		return

	# Borrowers and portal staff get sent to their landing page.
	target = _portal_staff_landing_for_request(user)
	frappe.local.response = frappe._dict()
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = target
	frappe.flags.redirect_location = target


def gate_desk_path(path: str):
	"""website_path_resolver hook: redirect non-admin users away from /desk.

	Returns ``None`` for everyone else so the normal resolver continues.
	For non-admin users, raises ``frappe.Redirect`` with the persona landing;
	Frappe's path_resolver catches it and returns a 301 ``RedirectPage``.

	Registered via ``website_path_resolver`` in hooks.py.
	"""
	user = frappe.session.user
	if not user or user == "Guest" or user == "Administrator":
		return None

	roles = set(frappe.get_roles(user))
	if roles.intersection({"System Manager", "Administrator"}):
		return None

	clean = (path or "").strip("/").lower()
	if not clean:
		return None
	if clean == "desk" or clean.startswith("desk/") or clean == "app" or clean.startswith("app/"):
		target = _portal_staff_landing_for_request(user)
		frappe.flags.redirect_location = target
		raise frappe.Redirect
	return None


def install_desk_gate():
	"""Override Frappe's path resolver to gate /desk and /app for non-admins.

	Frappe's ``PathResolver.resolve`` has a hardcoded fast path for the
	``desk`` endpoint that runs before ``website_path_resolver`` hooks, so
	those hooks never get a chance to redirect non-admin users. We subclass
	``PathResolver`` and inject the persona redirect into the resolve method
	so it fires before the desk fast path returns.

	Patched at import time. Idempotent — safe to call from multiple places.
	"""
	import frappe.website.path_resolver as pr

	if getattr(pr.PathResolver, "_lms_desk_gate_installed", False):
		return

	_BaseResolver = pr.PathResolver
	_Gate = _portal_staff_landing_for_request

	class _GatedResolver(_BaseResolver):
		_resolve_original = _BaseResolver.resolve

		def resolve(self):  # type: ignore[override]
			user = frappe.session.user
			if user and user != "Guest" and user != "Administrator":
				roles = set(frappe.get_roles(user))
				if not roles.intersection({"System Manager", "Administrator"}):
					clean = (self.path or "").strip("/").lower()
					if clean == "desk" or clean.startswith("desk/"):
						frappe.flags.redirect_location = _Gate(user)
						raise frappe.Redirect
					# /app is the legacy alias Frappe redirects to /desk with
					# 301; we just rewrite it to the persona landing instead.
					if clean == "app" or clean.startswith("app/"):
						frappe.flags.redirect_location = _Gate(user)
						raise frappe.Redirect
			return self._resolve_original()

	_GatedResolver._lms_desk_gate_installed = True
	pr.PathResolver = _GatedResolver

	# Also patch the local alias used inside path_resolver.py itself.
	if hasattr(pr, "PathResolver"):
		pr.PathResolver = _GatedResolver

	# And the `serve.py` import.
	try:
		import frappe.website.serve as srv
		srv.PathResolver = _GatedResolver
	except Exception:
		pass

	# And the website_settings / portal_settings imports.
	for modname in (
		"frappe.website.doctype.website_settings.website_settings",
		"frappe.website.doctype.portal_settings.portal_settings",
		"frappe.website.doctype.web_page.web_page",
	):
		try:
			mod = __import__(modname, fromlist=["PathResolver"])
			if hasattr(mod, "PathResolver"):
				mod.PathResolver = _GatedResolver
		except Exception:
			pass


# Default page_js for each addon key (SSoT for get_lms_page_context).
ADDON_PAGE_JS: dict[str, str] = {
	"announcements": "js/lms_announcements_portal.js",
	"task_management": "js/lms_tasks_portal.js",
	"document_center": "js/lms_documents_portal.js",
	"helpdesk": "js/lms_helpdesk_portal.js",
	"hr_management": "js/lms_hr_portal.js",
	"branch_analytics": "js/lms_analytics_portal.js",
	"regulatory_hub": "js/lms_regulatory_portal.js",
	"payroll": "js/lms_payroll_portal.js",
	"appraisals": "js/lms_appraisals_portal.js",
	"training": "js/lms_training_portal.js",
	"recruitment": "js/lms_recruitment_portal.js",
	"procurement": "js/lms_procurement_portal.js",
	"savings_club": "js/lms_savings_portal.js",
	"customer_feedback": "js/lms_feedback_portal.js",
	"field_visits": "js/lms_visits_portal.js",
	"inventory": "js/lms_inventory_portal.js",
	"budgeting": "js/lms_budgeting_portal.js",
	"insurance": "js/lms_insurance_portal.js",
	"whatsapp": "js/lms_whatsapp_portal.js",
	"wallet_recon": "js/lms_recon_portal.js",
}


def get_lms_page_context(
	context,
	*,
	nav_key: str | None = None,
	page_js: str | None = None,
	addon: str | None = None,
	perm: str | None = None,
	login_path: str | None = None,
):
	"""Guest login → optional addon gate → optional persona gate → portal shell.

	If ``addon`` is set, ``nav_key`` defaults to the registry key and
	``page_js`` defaults to ``ADDON_PAGE_JS[addon]``.
	``nav_key`` must match ADDON_REGISTRY / sidebar ``item.key`` so the
	active nav highlight and page title stay in sync.
	"""
	from lms_saas.utils.brand import apply_portal_context

	path = login_path or ("/" + (getattr(frappe.local, "path", None) or "lms").lstrip("/"))

	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to={path}"
		raise frappe.Redirect

	if addon:
		from lms_saas.utils.addons import ADDON_REGISTRY, require_addon

		require_addon(addon)
		nav_key = nav_key or addon
		page_js = page_js or ADDON_PAGE_JS.get(addon)
		# Page-level persona gate for addons (nav already filters; this
		# blocks deep links by wrong persona). Admins always pass.
		_require_addon_persona_page(addon, ADDON_REGISTRY.get(addon) or {})

	if perm:
		require_persona_for_page(perm)

	return apply_portal_context(
		context,
		nav_active=nav_key or "loans",
		page_js=page_js,
	)


def _require_addon_persona_page(addon_key: str, spec: dict) -> None:
	"""Redirect wrong personas away from addon pages (Admins exempt)."""
	if frappe.session.user in (None, "Guest", "Administrator"):
		return
	roles = set(frappe.get_roles())
	if roles.intersection({"System Manager", "Administrator"}):
		return

	allowed = spec.get("personas") or []
	persona = resolve_portal_persona()
	if persona and persona in allowed:
		return
	if "Borrower" in allowed and is_portal_borrower():
		return

	# Never dump staff onto the borrower dashboard (/lms). Prefer their
	# persona landing; fall back to manager for unknown portal staff.
	landing = PERSONA_LANDING.get(persona or "")
	if not landing:
		from lms_saas.install import PORTAL_STAFF_ROLE

		if PORTAL_STAFF_ROLE in roles:
			landing = "/lms/manager"
		else:
			landing = "/lms"
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
