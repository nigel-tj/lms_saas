import frappe
from frappe import _

# ---------------------------------------------------------------------------
# Phase 4.4 — this file is the SHARED helper module for the hyphen-named
# www/lms-portal/{officer,collector}.py pages. It is loaded by file path
# (Python can't import hyphen paths) via
# lms_saas.utils.portal._load_lms_portal_mixins.
#
# v3 design: persona (not legacy role name) drives the nav. Use
# ``resolve_portal_persona()`` from ``lms_saas.utils.portal`` and the
# permission map returned by ``_persona_permissions()``.
# ---------------------------------------------------------------------------

VALID_PERSONA_LEGACY_ROLES = (
	"Loan Officer",
	"Collector",
	"Branch Manager",
)


def _get_active_persona():
	"""Return the user's persona label (Loan Officer / Collector / Branch Manager)
	or None. Prefers ``Employee.custom_lms_persona``; falls back to the legacy
	role-name for installs that haven't migrated yet.
	"""
	# Try the v3 persona resolver first.
	try:
		from lms_saas.utils.portal import resolve_portal_persona
		persona = resolve_portal_persona()
		if persona in VALID_PERSONA_LEGACY_ROLES:
			return persona
	except Exception:
		pass

	# Legacy fallback: any portal-staff role maps to "Loan Officer" by default.
	roles = set(frappe.get_roles())
	if "LMS Portal Staff" in roles:
		if "LMS Collector" in roles:
			return "Collector"
		if "LMS Branch Manager" in roles:
			return "Branch Manager"
		return "Loan Officer"
	return None


def _require_staff_role(required_role: str):
	"""Generic guard to ensure the logged-in user has the given staff role.
	Raises frappe.PermissionError if the role is missing.

	Phase 4.4: kept for backwards compat. New code should use
	``utils.portal.require_persona_for_page`` (persona-aware).
	"""
	user_roles = frappe.get_roles()
	if required_role not in user_roles:
		frappe.throw(_("User does not have required role: {0}").format(required_role), frappe.PermissionError)


def _require_collector():
	_require_staff_role('LMS Collector')


def _require_officer():
	_require_staff_role('LMS Loan Officer')


def _require_manager():
	_require_staff_role('LMS Branch Manager')


def verify_portal_role(role: str):
	"""Compatibility shim — verify the user has the given legacy role.

	Phase 4.4: the v3 persona guard lives in
	``lms_saas.utils.portal.require_persona_for_page``. This shim maps the
	legacy role name to a permission bit and delegates.
	"""
	role_to_perm = {
		"LMS Loan Officer": "can_officer",
		"LMS Branch Manager": "can_manager",
		"LMS Collector": "can_collect",
	}
	perm = role_to_perm.get(role)
	if not perm:
		frappe.throw(_("Unknown portal role: {0}").format(role), frappe.PermissionError)
	from lms_saas.utils.portal import _user_can
	if not _user_can(perm):
		frappe.throw(
			_("You do not have access to the {0} portal.").format(role),
			frappe.PermissionError,
		)


def apply_staff_portal_context(context, nav_active: str, page_title: str | None = None):
	"""Inject LMS staff-portal base context. Phase 4.4: persona-aware.

	Merges brand, persona bitmask, and a persona-driven staff_nav into the
	Frappe web context. Backwards compatible with the old keyword args.
	"""
	from lms_saas.utils.brand import apply_portal_context
	from lms_saas.utils.portal import resolve_portal_persona, _persona_permissions, show_staff_desk_link

	apply_portal_context(context, nav_active=nav_active)
	persona = resolve_portal_persona()
	roles = set(frappe.get_roles())
	context.lms_user_permissions = _persona_permissions(persona, roles)
	context.staff_user_role_label = persona or _("Staff")
	if page_title:
		context.title = page_title
		context.page_title = page_title
	context.staff_nav = get_staff_nav()
	context.show_staff_desk = show_staff_desk_link()
	# Persona-aware body class for the staff-portal theme.
	body_class = getattr(context, "body_class", None) or ""
	if "lms-staff" not in body_class:
		context.body_class = f"{body_class} lms-staff lms-themed".strip()
	return context


def get_staff_nav():
	"""Return a list of navigation items for the staff portal sidebar.

	Phase 4.4: persona (not legacy role name) drives the nav. Each persona
	sees only its own landing — Officers don't see Manager / Collector links.
	"""
	nav = []
	persona = _get_active_persona()
	# Loan Officer and Branch Manager can also see Manager.
	if persona in ("Loan Officer", "Branch Manager"):
		nav.append({"key": "officer", "label": _("Loans"), "route": "/lms/officer"})
		nav.append({"key": "manager", "label": _("Management"), "route": "/lms/manager"})
	if persona in ("Collector", "Loan Officer", "Branch Manager"):
		nav.append({"key": "collector", "label": _("Collections"), "route": "/lms/collect"})
	return nav


def get_staff_context():
	"""Inject common staff context variables used by the base template.

	Phase 4.4: persona drives the role label (not the legacy role name).
	Returns a dict that will be merged into the Jinja context.
	"""
	user = frappe.session.user
	user_doc = frappe.get_doc('User', user)
	name = getattr(user_doc, 'full_name', user)
	persona = _get_active_persona()
	role_label = _(persona) if persona else _("Staff")
	return {
		"staff_user_name": name,
		"staff_user_role_label": role_label,
		"staff_nav": get_staff_nav(),
	}
