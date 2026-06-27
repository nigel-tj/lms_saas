"""Desk help menu and /lms-help documentation pages."""

from __future__ import annotations

import os

import frappe
from frappe import _

from lms_saas.install import (
	ALL_LMS_ROLES,
	EVERYONE_ROLES,
	ORIGINATION_ROLES,
	OVERSIGHT_ROLES,
	SYS_ROLE,
)

# App package lives in lms_saas/lms_saas/; markdown sources are in lms_saas/docs/
DOCS_DIR = os.path.join(os.path.dirname(frappe.get_app_path("lms_saas")), "docs")

# slug → markdown file + roles that may open the page
HELP_PAGES: tuple[dict, ...] = (
	{
		"slug": "staff",
		"title": _("Staff guide"),
		"file": "STAFF_GUIDE.md",
		"roles": EVERYONE_ROLES,
		"description": _("Day-to-day desk workflows, roles, and FAQs"),
	},
	{
		"slug": "admin",
		"title": _("System admin guide"),
		"file": "SYSADMIN_GUIDE.md",
		"roles": (SYS_ROLE, "LMS Admin"),
		"description": _("Install, site config, GL, backups, and troubleshooting"),
	},
	{
		"slug": "compliance",
		"title": _("Compliance"),
		"file": "COMPLIANCE.md",
		"roles": OVERSIGHT_ROLES,
		"description": _("RBZ sandbox control mapping"),
	},
	{
		"slug": "setup",
		"title": _("Setup reference"),
		"file": "SETUP.md",
		"roles": (SYS_ROLE, "LMS Admin"),
		"description": _("Quick install and verification"),
	},
	{
		"slug": "data-import",
		"title": _("Data import"),
		"file": "DATA_IMPORT.md",
		"roles": ORIGINATION_ROLES,
		"description": _("Bulk loan repayment import"),
	},
	{
		"slug": "backup",
		"title": _("Backup & restore"),
		"file": "BACKUP.md",
		"roles": (SYS_ROLE,),
		"description": _("Backup and disaster recovery"),
	},
	{
		"slug": "branding",
		"title": _("Branding"),
		"file": "BRANDING.md",
		"roles": (SYS_ROLE, "LMS Admin"),
		"description": _("Desk and portal themes"),
	},
)

_HELP_SLUGS = {p["slug"]: p for p in HELP_PAGES}

# Navbar Settings rows (all pages; desk JS filters by role via boot).
NAVBAR_HELP_ITEMS: tuple[tuple[str, str], ...] = tuple(
	(spec["title"], f"/lms-help/{spec['slug']}") for spec in HELP_PAGES
)

DESK_HELP_ROLES = frozenset(ALL_LMS_ROLES) | {SYS_ROLE, "Desk User"}


def _user_roles(user: str | None = None) -> set[str]:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return set()
	return set(frappe.get_roles(user))


def user_has_desk_help(user: str | None = None) -> bool:
	return bool(_user_roles(user) & DESK_HELP_ROLES)


def _roles_overlap(user_roles: set[str], required: tuple[str, ...]) -> bool:
	return bool(user_roles.intersection(required))


def pages_for_user(user: str | None = None) -> list[dict]:
	user_roles = _user_roles(user)
	if not user_roles:
		return []
	if SYS_ROLE in user_roles:
		allowed = list(HELP_PAGES)
	else:
		allowed = [p for p in HELP_PAGES if _roles_overlap(user_roles, p["roles"])]
	return allowed


def get_lms_help_menu(user: str | None = None) -> dict:
	"""Role-filtered help dropdown items for desk boot + client JS."""
	if not user_has_desk_help(user):
		return {"enabled": False, "items": []}

	items: list[dict] = []
	for page in pages_for_user(user):
		items.append(
			{
				"label": page["title"],
				"url": f"/lms-help/{page['slug']}",
				"description": page.get("description") or "",
			}
		)

	support = _support_email()
	if support:
		items.append({"separator": True})
		items.append(
			{
				"label": _("Contact support"),
				"url": f"mailto:{support}",
				"description": support,
			}
		)

	return {"enabled": bool(items), "items": items}


def _support_email() -> str | None:
	try:
		raw = frappe.db.get_single_value("Website Settings", "support_email")
	except Exception:
		raw = None
	if not raw:
		from lms_saas.utils.brand import DEFAULT_BRAND

		raw = DEFAULT_BRAND.get("support_email")
	email = (raw or "").strip()
	return email or None


def get_help_page(slug: str) -> dict | None:
	slug = (slug or "").strip().lower()
	return _HELP_SLUGS.get(slug)


def user_may_view_help_page(slug: str, user: str | None = None) -> bool:
	page = get_help_page(slug)
	if not page:
		return False
	user_roles = _user_roles(user)
	if not user_roles:
		return False
	if SYS_ROLE in user_roles:
		return True
	return _roles_overlap(user_roles, page["roles"])


def load_help_markdown(filename: str) -> str:
	path = os.path.join(DOCS_DIR, filename)
	if not os.path.isfile(path):
		frappe.throw(_("Help document not found."), frappe.DoesNotExistError)
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def markdown_to_html(text: str) -> str:
	"""Render markdown files to sanitized HTML.

	Help docs are always markdown on disk. ``frappe.utils.markdown`` skips
	conversion when ``is_html`` matches placeholders like ``<national_id>`` in
	SYSADMIN_GUIDE.md, so use ``md_to_html`` directly then sanitize.
	"""
	html = frappe.utils.md_to_html(text or "")
	if not html:
		import html as html_module

		return f'<pre class="lms-help-pre">{html_module.escape(text or "")}</pre>'
	return frappe.utils.sanitize_html(str(html), linkify=True)


def rewrite_help_links(html: str, site_url: str) -> str:
	"""Replace {site-url} placeholders and map doc cross-links to /lms-help routes."""
	base = (site_url or "").rstrip("/")
	html = html.replace("{site-url}", base)
	for spec in HELP_PAGES:
		filename = spec["file"]
		target = f"/lms-help/{spec['slug']}"
		html = html.replace(f'href="{filename}"', f'href="{target}"')
		html = html.replace(f"href='{filename}'", f"href='{target}'")
	return html


def apply_help_page_context(context, slug: str) -> dict:
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to=/lms-help/{slug}"
		raise frappe.Redirect

	if not user_may_view_help_page(slug):
		frappe.throw(_("You do not have permission to view this help page."), frappe.PermissionError)

	page = get_help_page(slug)
	assert page is not None

	raw = load_help_markdown(page["file"])
	site_url = frappe.utils.get_url()
	body_html = rewrite_help_links(markdown_to_html(raw), site_url)

	from lms_saas.utils.brand import apply_favicon_context, get_portal_brand
	from lms_saas.utils.frappe_version import desk_url

	brand = get_portal_brand()
	pages = pages_for_user()
	nav = [
		{
			"slug": p["slug"],
			"title": p["title"],
			"url": f"/lms-help/{p['slug']}",
			"active": p["slug"] == slug,
		}
		for p in pages
	]

	context.no_cache = 1
	context.show_sidebar = False
	context.title = page["title"]
	context.help_slug = slug
	context.help_title = page["title"]
	context.help_body = body_html
	context.help_nav = nav
	context.brand = brand
	apply_favicon_context(context)
	context.lms_desk_home = desk_url("loans")
	context.lms_theme = frappe.get_attr("lms_saas.utils.brand.get_lms_theme")()
	context.show_staff_desk = frappe.get_attr("lms_saas.utils.portal.show_staff_desk_link")()
	context.body_class = "lms-help-page lms-themed"
	return context


def sync_navbar_help_dropdown(navbar) -> None:
	"""Ensure Navbar Settings lists LMS help routes (Frappe desk reads this on load)."""
	rows = list(navbar.get("help_dropdown") or [])
	by_label = {row.item_label: row for row in rows}

	for label, route in NAVBAR_HELP_ITEMS:
		row = by_label.get(label)
		if row:
			row.hidden = 0
			row.item_type = "Route"
			row.route = route
			continue
		navbar.append(
			"help_dropdown",
			{
				"item_label": label,
				"item_type": "Route",
				"route": route,
				"hidden": 0,
			},
		)
