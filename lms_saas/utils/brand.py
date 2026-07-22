"""Portal branding defaults and context helpers."""

from lms_saas.utils.frappe_version import desk_url, lending_home_url

BRAND_LOGO_PATH = "/assets/lms_saas/images/lms-logo.svg"
BRAND_FAVICON_PATH = "/assets/lms_saas/images/lms-favicon.svg"

DESK_ADMIN_ROLES = frozenset({
	"System Manager",
	"Administrator",
	"Desk User",
})


def _get_user_persona(user: str | None = None) -> str | None:
	"""Resolve the LMS persona for ``user`` (defaults to current session).

	Thin wrapper around ``lms_saas.utils.portal.resolve_portal_persona`` kept
	here so other utils (and addons that may import from brand directly) have
	a stable import path. Returns one of ``"Loan Officer"``, ``"Branch Manager"``,
	``"Collector"``, ``"Borrower"`` (website Customer), or ``None`` for guests /
	users without a persona.
	"""
	from lms_saas.utils.portal import resolve_portal_persona

	return resolve_portal_persona(user)


def _get_user_permissions(persona: str | None, roles: set) -> dict:
	"""Return a dict of boolean permission flags for the current user.

	Mirrors the permission flags consumed by templates and JS bootinfo.
	Admins (System Manager / Administrator / Desk User) get every flag.
	"""
	roles = roles or set()
	is_admin = bool(roles & DESK_ADMIN_ROLES)
	is_borrower = "Customer" in roles and not is_admin
	is_staff = bool(persona in {"Loan Officer", "Branch Manager", "Collector"}) and not is_admin

	return {
		"is_admin": is_admin,
		"is_portal_borrower": is_borrower,
		"is_portal_staff": is_staff,
		"can_borrower": is_borrower or is_admin,
		"can_officer": (persona == "Loan Officer") or is_admin,
		"can_manager": (persona == "Branch Manager") or is_admin,
		"can_collect": (persona in {"Loan Officer", "Branch Manager", "Collector"}) or is_admin,
		"persona": persona,
	}


DEFAULT_BRAND = {
	"portal_title": "Kesari",
	"tagline": "Stewardship in every repayment",
	"product_subtitle": "Loan management with accountability",
	"primary_color": "#2f4f46",
	"theme_id": "default",
	"support_email": "",
	"footer_text": "Powered by Kesari",
	"logo_url": None,
	"favicon_url": None,
}

VALID_LMS_THEMES = frozenset({"default", "midnight", "dark", "auto"})


def get_lms_theme():
	"""Active UI theme id (switch via site_config.json → lms_theme)."""
	import frappe

	theme = (frappe.conf.get("lms_theme") or DEFAULT_BRAND.get("theme_id") or "default").strip().lower()
	return theme if theme in VALID_LMS_THEMES else "default"


def get_brand_logo_url() -> str:
	"""Desk/portal logo — Website Settings app_logo, else bundled LMS logo."""
	import frappe

	try:
		logo = frappe.get_single_value("Website Settings", "app_logo")
		if logo:
			return logo
	except Exception:
		pass
	return BRAND_LOGO_PATH


def get_brand_favicon_url() -> str:
	"""Tab icon + loading indicator — Website Settings favicon, else bundled mark."""
	import frappe

	try:
		favicon = frappe.get_single_value("Website Settings", "favicon")
		if favicon:
			return favicon
	except Exception:
		pass
	return BRAND_FAVICON_PATH


def get_brand_splash_url() -> str:
	"""Desk boot splash — Website Settings splash_image, else favicon mark."""
	import frappe

	try:
		splash = frappe.get_single_value("Website Settings", "splash_image")
		if splash:
			return splash
	except Exception:
		pass
	return get_brand_favicon_url()


def enrich_brand(brand: dict | None = None) -> dict:
	"""Attach resolved logo/favicon URLs to a brand dict."""
	merged = dict(DEFAULT_BRAND)
	if brand:
		merged.update(brand)
	import frappe

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if company:
		merged["company_name"] = company
	for key, conf_key in (
		("portal_title", "lms_brand_portal_title"),
		("tagline", "lms_brand_tagline"),
		("product_subtitle", "lms_brand_product_subtitle"),
		("footer_text", "lms_brand_footer_text"),
		("primary_color", "lms_brand_primary_color"),
	):
		override = frappe.conf.get(conf_key)
		if override:
			merged[key] = override
	merged["logo_url"] = get_brand_logo_url()
	merged["favicon_url"] = get_brand_favicon_url()
	return merged


def get_portal_brand():
	"""Return branding dict for portal templates (extensible via settings later)."""
	return enrich_brand()


def apply_favicon_context(context) -> None:
	context.brand_favicon_url = get_brand_favicon_url()
	context.favicon_url = context.brand_favicon_url
	brand = getattr(context, "brand", None)
	if brand is not None:
		if isinstance(brand, dict):
			brand["favicon_url"] = context.brand_favicon_url
		else:
			context.brand = enrich_brand()


def apply_portal_context(context, nav_active="loans", page_js=None):
	"""Merge brand into Frappe web page context and prepare the standalone shell."""
	import frappe

	from lms_saas.install import PORTAL_STAFF_ROLE
	from lms_saas.utils.portal import show_staff_desk_link, resolve_portal_persona

	brand = get_portal_brand()
	context.brand = brand
	apply_favicon_context(context)
	context.lms_theme = get_lms_theme()
	context.lms_primary_color = brand.get("primary_color")
	context.portal_nav_active = nav_active
	context.show_staff_desk = show_staff_desk_link()
	# Portal staff (Loan Officers / Collectors) see a Collection Run nav link.
	user_roles = set(frappe.get_roles(frappe.session.user)) if frappe.session.user != "Guest" else set()
	context.is_portal_staff = PORTAL_STAFF_ROLE in user_roles and not show_staff_desk_link()
	# Resolve persona so the nav shows only the relevant items per role.
	context.lms_persona = resolve_portal_persona()
	context.is_portal_borrower = "Customer" in user_roles and not context.is_portal_staff and not show_staff_desk_link()
	context.lms_desk_home = lending_home_url()
	context.lms_risk_disclosure = (
		frappe.conf.get("lms_risk_disclosure")
		or frappe.conf.get("lms_email_legal_footer")
		or frappe._("Lending involves credit risk. Terms apply to approved borrowers only.")
	)
	context.show_sidebar = False
	context.no_header = True
	context.no_cache = 1
	body_class = getattr(context, "body_class", None) or ""
	context.body_class = f"{body_class} lms-portal lms-themed".strip()

	# Prepare the standalone shell's CSS/JS stacks.
	context.lms_css_stack = _lms_portal_css_stack()
	context.lms_js_stack = _lms_portal_js_stack(page_js)
	context.lms_nav = _build_lms_nav(context)
	context.lms_page_title = _lms_page_title(nav_active, context)

	# Frappe web bundle expects boot data + build version to be present.
	from frappe.website.utils import get_boot_data
	from frappe.utils import get_build_version

	context.boot = get_boot_data()
	context.build_version = get_build_version()
	context.dev_server = bool(frappe._dev_server)
	return context


def _lms_portal_css_stack():
	"""CSS files for the standalone LMS portal shell."""
	from lms_saas.hooks import _lms_css_stack, _versioned_asset

	return _lms_css_stack(
		_versioned_asset("css/lms_portal.css", "/assets/lms_saas/css/lms_portal.css"),
		# Form primitives + popout combobox styles. Without this the
		# <select> popout triggers and inputs inside modals fall back
		# to raw browser defaults (2008 grey `2px outset` buttons).
		_versioned_asset("css/lms_form.css", "/assets/lms_saas/css/lms_form.css"),
	)


def _lms_portal_js_stack(page_js=None):
	"""JS files for the standalone LMS portal shell.

	Order matters: lms_modal.js (LMSModal namespace) and lms_forms.js
	(LMSForms namespace) must load BEFORE any page-specific portal JS
	that uses LMSModal.open(...) or LMSForms.bindAll(...) — the officer,
	collector and borrower portals all reference both.
	"""
	from lms_saas.hooks import _versioned_asset

	stack = [
		_versioned_asset("js/lms_brand.js", "/assets/lms_saas/js/lms_brand.js"),
		_versioned_asset("js/lms_theme.js", "/assets/lms_saas/js/lms_theme.js"),
		_versioned_asset("js/vendor/chart.min.js", "/assets/lms_saas/js/vendor/chart.min.js"),
		_versioned_asset("js/lms_modal.js", "/assets/lms_saas/js/lms_modal.js"),
		_versioned_asset("js/lms_forms.js", "/assets/lms_saas/js/lms_forms.js"),
		_versioned_asset("js/lms_charts.js", "/assets/lms_saas/js/lms_charts.js"),
		_versioned_asset("js/lms_portal.js", "/assets/lms_saas/js/lms_portal.js"),
	]
	if page_js:
		stack.append(_versioned_asset(page_js, f"/assets/lms_saas/{page_js}"))
	return stack


def _build_lms_nav(context):
	"""Build persona-filtered navigation items for the portal sidebar.

	Addon nav items are appended after the core nav, before the account link.
	Each addon is only shown if it is enabled in site_config and the user's
	persona is in the addon's allowed-personas list.
	"""
	import frappe

	from lms_saas.utils.addons import addon_nav_items

	items = []
	persona = context.get("lms_persona")
	is_borrower = context.get("is_portal_borrower")
	is_staff = context.get("is_portal_staff")

	if is_borrower or not is_staff:
		items.extend([
			{"key": "loans", "label": "My Loans", "route": "/lms", "icon": "loans"},
			{"key": "apply", "label": "Apply", "route": "/lms/apply", "icon": "apply"},
			{"key": "pay", "label": "Pay", "route": "/lms/pay", "icon": "pay"},
		])

	if is_staff:
		if persona == "Loan Officer":
			items.append({"key": "officer", "label": "Officer", "route": "/lms/officer", "icon": "officer"})
		elif persona == "Branch Manager":
			items.append({"key": "manager", "label": "Manager", "route": "/lms/manager", "icon": "manager"})
			items.append({"key": "manager_books", "label": "Books & Import", "route": "/lms/manager-books", "icon": "books"})
		items.append({"key": "collect", "label": "Collection Run", "route": "/lms/collect", "icon": "collect"})

	# ── Addon nav items ──
	# Borrowers see borrower-tagged addons; staff see persona-matched addons.
	addon_persona = persona
	if is_borrower and not is_staff:
		addon_persona = "Borrower"
	elif not is_staff and not is_borrower:
		# Admins (desk users) browsing the portal — show all staff addons.
		addon_persona = "Admin"
	items.extend(addon_nav_items(addon_persona))

	if frappe.session.user != "Guest":
		items.append({"key": "account", "label": "My Account", "route": "/lms/account", "icon": "account"})

	return items


def _lms_page_title(nav_active, context):
	"""Return a human-readable page title based on active nav key."""
	labels = {
		"loans": "My Loans",
		"apply": "Apply for a Loan",
		"pay": "Make a Payment",
		"account": "My Account",
		"officer": "Loan Officer Dashboard",
		"manager": "Branch Manager Dashboard",
		"manager_books": "Books & Import",
		"collect": "Collection Run",
		# ── Addon page titles ──
		"announcements": "Announcements",
		"tasks": "Tasks",
		"documents": "Document Center",
		"support": "Support",
		"hr": "HR Management",
		"analytics": "Branch Analytics",
		"regulatory": "Regulatory Hub",
		"payroll": "Payroll",
		"appraisals": "Appraisals",
		"training": "Training & Development",
		"recruitment": "Recruitment",
		"procurement": "Procurement",
		"savings": "Savings Club",
		"feedback": "Customer Feedback",
		"visits": "Field Visits",
		"inventory": "Inventory & Assets",
		"budgeting": "Budgeting",
		"insurance": "Insurance",
		"whatsapp": "WhatsApp",
		"reconciliation": "Wallet Reconciliation",
	}
	return labels.get(nav_active, context.get("brand", {}).get("portal_title", "Kesari"))


def update_website_context(context):
	"""Global website hook — hide ERPNext portal sidebar for LMS borrowers."""
	from lms_saas.utils.portal import apply_borrower_web_context, show_staff_desk_link

	apply_borrower_web_context(context)
	apply_favicon_context(context)
	context.show_staff_desk = show_staff_desk_link()
	context.lms_desk_home = lending_home_url()


def apply_login_context(context):
	"""Brand the Frappe /login page (staff desk + borrower portal entry)."""
	import frappe

	brand = get_portal_brand()
	context.brand = brand
	context.logo = brand.get("logo_url")
	apply_favicon_context(context)
	context.lms_theme = get_lms_theme()
	context.lms_primary_color = brand.get("primary_color")
	context.lms_desk_home = lending_home_url()
	product = brand.get("portal_title") or "Kesari"
	context.lms_login = {
		"headline": frappe._("Sign in to {0}").format(product),
		"subtitle": brand.get("product_subtitle") or frappe._("Loan management with accountability"),
		"staff_label": frappe._("Staff desk"),
		"staff_hint": frappe._("Loan officers, collections, and compliance teams"),
		"staff_url": lending_home_url(),
		"borrower_label": frappe._("Borrower portal"),
		"borrower_hint": frappe._("View balances, schedules, and account details"),
		"features": [
			frappe._("End-to-end loan lifecycle"),
			frappe._("Portfolio risk and compliance oversight"),
			frappe._("Secure borrower self-service"),
		],
	}
	context.body_class = "lms-login-page lms-themed"
	context.show_sidebar = False
	context.no_cache = 1
	context.no_header = True
	context.hide_login = True
	return context
