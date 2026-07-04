"""Portal branding defaults and context helpers."""

from lms_saas.utils.frappe_version import desk_url, lending_home_url

BRAND_LOGO_PATH = "/assets/lms_saas/images/lms-logo.svg"
BRAND_FAVICON_PATH = "/assets/lms_saas/images/lms-favicon.svg"

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
	context.lms_page_subtitle = _lms_page_subtitle(nav_active, context)

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
	)


def _lms_portal_js_stack(page_js=None):
	"""JS files for the standalone LMS portal shell."""
	from lms_saas.hooks import _versioned_asset

	stack = [
		_versioned_asset("js/lms_brand.js", "/assets/lms_saas/js/lms_brand.js"),
		_versioned_asset("js/lms_theme.js", "/assets/lms_saas/js/lms_theme.js"),
		_versioned_asset("js/vendor/chart.min.js", "/assets/lms_saas/js/vendor/chart.min.js"),
		_versioned_asset("js/lms_charts.js", "/assets/lms_saas/js/lms_charts.js"),
		_versioned_asset("js/lms_portal.js", "/assets/lms_saas/js/lms_portal.js"),
	]
	if page_js:
		stack.append(_versioned_asset(page_js, f"/assets/lms_saas/{page_js}"))
	return stack


def _build_lms_nav(context):
	"""Build persona-filtered navigation items for the portal sidebar."""
	import frappe

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
		items.append({"key": "collect", "label": "Collection Run", "route": "/lms/collect", "icon": "collect"})

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
		"collect": "Collection Run",
	}
	return labels.get(nav_active, context.get("brand", {}).get("portal_title", "Kesari"))


def _lms_page_subtitle(nav_active, context):
	"""Return a short per-page description shown in the topbar under the title.

	Falls back to the risk disclosure line when no subtitle is defined for
	the active page (e.g. borrower-facing pages keep the compliance text).
	"""
	import frappe

	subtitles = {
		"officer": "Track applications, manage your loan portfolio, and onboard borrowers.",
		"manager": "Branch metrics, loan approvals, and team performance.",
		"collect": "Field collections and repayment tracking.",
	}
	if nav_active in subtitles:
		return subtitles[nav_active]
	return (
		frappe.conf.get("lms_risk_disclosure")
		or frappe.conf.get("lms_email_legal_footer")
		or frappe._("Lending involves credit risk. Terms apply to approved borrowers only.")
	)


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
