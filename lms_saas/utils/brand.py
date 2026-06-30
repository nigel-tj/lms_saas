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


def apply_portal_context(context, nav_active="loans"):
	"""Merge brand into Frappe web page context."""
	import frappe

	from lms_saas.utils.portal import show_staff_desk_link

	brand = get_portal_brand()
	context.brand = brand
	apply_favicon_context(context)
	context.lms_theme = get_lms_theme()
	context.lms_primary_color = brand.get("primary_color")
	context.portal_nav_active = nav_active
	context.show_staff_desk = show_staff_desk_link()
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
	return context


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
