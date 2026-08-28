"""Portal branding defaults and context helpers."""

import frappe

from lms_saas.utils.frappe_version import desk_url, lending_home_url

# R23 decision: the operator's product brand is "Kesari" (a competitive
# identity against the operator's peers in microfinance). The brand mark
# (logo + favicon) defaults to the Kesari mark — that's intentional, not
# an accident. The fallback is config-overridable so a rebrand to a
# different product line (e.g. a future white-label partner) can swap
# the mark without a code change.
#
#   lms_brand_logo_path    (site_config) — operator-supplied logo path
#   lms_brand_favicon_path (site_config) — operator-supplied favicon path
#
# The fallback chain is:
#   1. lms_brand_logo_path / lms_brand_favicon_path (operator override)
#   2. BRAND_LOGO_PATH / BRAND_FAVICON_PATH (default — the Kesari mark)
#   3. Website Settings.app_logo / favicon (the desk-side value)
BRAND_LOGO_PATH = "/assets/lms_saas/images/lms-logo.svg"
BRAND_FAVICON_PATH = "/assets/lms_saas/images/lms-favicon.svg"

# R12 board: "Desk User" is the Frappe default role that every authenticated
# user (staff, borrowers, everyone) gets just for logging in. It grants
# access to /desk but does NOT confer LMS admin rights. Including it in
# DESK_ADMIN_ROLES would incorrectly mark every Branch Manager as a system
# admin, hiding the persona-landing redirect and the per-persona permission
# flags. Sites that historically relied on Desk User = admin can opt back
# in via site_config `lms_treat_desk_user_as_admin = 1`.
DESK_ADMIN_ROLES = frozenset({
	"System Manager",
	"Administrator",
})

LEGACY_DESK_ADMIN_ROLES = frozenset({
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
	Admins (System Manager / Administrator) get every flag. Desk User alone
	is not enough — see ``DESK_ADMIN_ROLES`` for the rationale. Sites that
	need the legacy "Desk User = admin" behaviour can opt in via
	``lms_treat_desk_user_as_admin = 1`` in site_config.
	"""
	roles = roles or set()
	if frappe.conf.get("lms_treat_desk_user_as_admin"):
		admin_roles = LEGACY_DESK_ADMIN_ROLES
	else:
		admin_roles = DESK_ADMIN_ROLES
	is_admin = bool(roles & admin_roles)
	is_borrower = "Customer" in roles and not is_admin
	is_staff = bool(persona in {"Loan Officer", "Branch Manager", "Collector", "Operations Manager"}) and not is_admin

	return {
		"is_admin": is_admin,
		"is_portal_borrower": is_borrower,
		"is_portal_staff": is_staff,
		"can_borrower": is_borrower or is_admin,
		"can_officer": (persona in {"Loan Officer", "Branch Manager"}) or is_admin,
		"can_manager": (persona == "Branch Manager") or is_admin,
		"can_collect": (persona in {"Loan Officer", "Branch Manager", "Collector"}) or is_admin,
		# R52: Operations Manager — portal-staff persona for loan catalogue +
		# operational config. Gates the /lms/setup route + the api.setup guard.
		"can_setup": (persona == "Operations Manager") or is_admin,
		"can_admin": is_admin,
		"persona": persona,
	}


# R23-C1 fix: DEFAULT_BRAND is the vendor-neutral product family fallback.
# The OPERATOR's brand (e.g. "Kesari") is set per-site via
# `lms_brand_portal_title` in site_config and overrides these defaults.
# Keeping these as the product-family defaults (rather than the operator's
# brand) is correct because:
#   1. The package name is `lms_saas` (vendor-neutral) and ships to any
#      site. If a different operator installs it, the visible brand should
#      not be "Kesari" by accident.
#   2. A typo / unset `lms_brand_portal_title` should fall through to a
#      neutral product name, not a competitor's brand.
#   3. Operators can set `lms_brand_portal_title` in site_config and the
#      after_install hook writes the value to Website Settings + System
#      Settings + Navbar Settings (see install.py).
DEFAULT_BRAND = {
	"portal_title": "LMS",
	"tagline": "Stewardship in every repayment",
	"product_subtitle": "Loan management with accountability",
	"primary_color": "#2f4f46",
	"theme_id": "default",
	"support_email": "",
	"footer_text": "Powered by LMS",
	"logo_url": None,
	"favicon_url": None,
}

# Brand aliases — operator-specific brand strings that some fallback paths
# use (e.g. error paths in user setup, email subjects when no portal_title
# is configured). These are read from site_config so the operator can
# override them without a code change. Default to the product family name
# (vendor-neutral) — the operator's actual brand is set via
# lms_brand_portal_title.
_BRAND_ALIAS_DEFAULTS = {
	"operator_brand": "LMS",
	"operator_tagline": "Stewardship in every repayment",
}


def _brand_alias(key: str) -> str:
	"""Return the operator-specific brand string for ``key``.

	The operator sets these in site_config so the same code base can ship
	under different operator brands without code changes. The fallback chain
	is:
	  1. site_config ``lms_brand_<key>`` (operator override)
	  2. ``lms_brand_portal_title`` (the main operator brand)
	  3. ``_BRAND_ALIAS_DEFAULTS[key]`` (vendor-neutral fallback)
	"""
	override = frappe.conf.get(f"lms_brand_{key}")
	if override:
		return override
	main = frappe.conf.get("lms_brand_portal_title")
	if main:
		return main
	return _BRAND_ALIAS_DEFAULTS.get(key, "LMS")

VALID_LMS_THEMES = frozenset({"default", "midnight", "dark", "auto"})


def get_lms_theme():
	"""Active UI theme id (switch via site_config.json → lms_theme)."""
	import frappe

	theme = (frappe.conf.get("lms_theme") or DEFAULT_BRAND.get("theme_id") or "default").strip().lower()
	return theme if theme in VALID_LMS_THEMES else "default"


def resolve_operator_app_name() -> str | None:
	"""R32: return the operator's desk wordmark, or None to leave the
	build-time default in place.

	The desk chrome (navbar title, login page wordmark, app launcher) reads
	``bootinfo.app_name`` which mirrors ``frappe.conf["app_name"]`` /
	``hooks.app_title``. ``hooks.app_title`` is a build-time constant and
	can't be runtime-overridden per site, so this helper resolves the
	operator's brand from site_config so the operator can rebrand the desk
	without a code change.

	Resolution chain:
	  1. ``lms_app_title`` site_config — explicit per-site override. Use
	     this when the operator wants the desk chrome to say something
	     different from the portal title (e.g. portal wordmark set to
	     the group name, desk wordmark set to the loan-product line).
	  2. ``lms_brand_portal_title`` site_config — the unified brand key
	     every other LMS UI surface reads from.
	  3. None — leave the build-time value alone. The R30 board decided
	     to keep ``hooks.app_title`` set to the operator's brand so a
	     fresh install shows the brand accurately without any site_config
	     editing. The runtime override here is the safety net for
	     rebrand operations.

	Returns the stripped, non-empty string, or None if neither key is set.
	"""
	import frappe

	override = (frappe.conf.get("lms_app_title") or "").strip()
	if override:
		return override
	main = (frappe.conf.get("lms_brand_portal_title") or "").strip()
	if main:
		return main
	return None


def get_brand_logo_url() -> str:
	"""Desk/portal logo — operator-supplied, then Website Settings, then bundled mark.

	Fallback chain (R23-H2 fix):
	  1. ``lms_brand_logo_path`` site_config (operator override)
	  2. Website Settings.app_logo (DB value the operator may have set)
	  3. BRAND_LOGO_PATH (the bundled Kesari mark — operator's product brand)
	"""
	import frappe

	override = frappe.conf.get("lms_brand_logo_path")
	if override:
		return override
	try:
		logo = frappe.get_single_value("Website Settings", "app_logo")
		if logo:
			return logo
	except Exception:
		pass
	return BRAND_LOGO_PATH


def get_brand_favicon_url() -> str:
	"""Tab icon + loading indicator — operator-supplied, then Website Settings, then bundled mark.

	Fallback chain (R23-H2 fix):
	  1. ``lms_brand_favicon_path`` site_config (operator override)
	  2. Website Settings.favicon (DB value the operator may have set)
	  3. BRAND_FAVICON_PATH (the bundled Kesari mark)
	"""
	import frappe

	override = frappe.conf.get("lms_brand_favicon_path")
	if override:
		return override
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
	"""Attach resolved logo/favicon URLs to a brand dict.

	R23-H1 fix: validate the operator's configured brand values. A typo
	or unrendered template placeholder in `lms_brand_portal_title` would
	otherwise leak verbatim to the portal boot, navbar, and email footers.
	"""
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
			merged[key] = _sanitize_brand_value(key, override)
	# R23-H1: surface a validation warning so the operator's portal boot
	# shows a banner if any brand value looks suspicious. The warning is
	# best-effort — it's a list, not a raise, so the portal still renders.
	merged["brand_validation_warnings"] = _validate_brand(merged)
	merged["logo_url"] = get_brand_logo_url()
	merged["favicon_url"] = get_brand_favicon_url()
	return merged


def _sanitize_brand_value(key: str, value: str) -> str:
	"""Strip a brand value of obviously-broken placeholders.

	A misconfigured `lms_brand_portal_title` with a literal `{{ ... }}`
	or `<placeholder>` token would render verbatim to the portal. Strip
	common template markers but keep the value otherwise intact.
	"""
	if not isinstance(value, str):
		return value
	import re

	# Remove literal Jinja / mustache / angle-bracket placeholders that
	# would otherwise render as visible text in the portal.
	patterns = (
		r"\{\{[^}]*\}\}",     # {{ ... }}
		r"\{%[^}]*%\}",       # {% ... %}
		r"<placeholder[^>]*>", # <placeholder ...>
	)
	for pat in patterns:
		value = re.sub(pat, "", value)
	return value.strip()


def _validate_brand(brand: dict) -> list[str]:
	"""Return a list of human-readable warnings for suspicious brand values.

	R23-H1: a configured `lms_brand_portal_title` with a typo, RTL
	characters, or unrendered placeholder is the operator's first
	surface for the new client. Surface a warning in the portal boot
	so the operator notices before going live.
	"""
	warnings = []
	title = brand.get("portal_title") or ""
	if not title:
		warnings.append("portal_title is empty — set lms_brand_portal_title in site_config")
	elif len(title) > 60:
		warnings.append(f"portal_title is {len(title)} chars — most brand names fit in 30")
	# Detect right-to-left override (U+202E) which has been used in
	# phishing-style brand spoofing.
	if "\u202e" in title:
		warnings.append("portal_title contains a right-to-left override (U+202E) — possible spoofing")
	return warnings


def get_portal_brand():
	"""Return branding dict for portal templates (extensible via settings later)."""
	return enrich_brand()


# R33: One-call brand setter. Operators (and the rebrand script) use this
# to set the visible brand name + tagline + footer in a single transaction
# so the three values can never drift apart. Without this, the brand name
# can fall through to the vendor-neutral "LMS" fallback in one place
# while a custom footer sticks around in another, and the operator ends
# up debugging drift tickets between the login page heading and the
# portal footer.
#
# Use:
#   bench --site <site> execute lms_saas.utils.brand.set_brand \
#     --kwargs '{"portal_title": "Acme Capital", "tagline": "Loans for good", "footer_text": "Powered by Acme"}'
#
# This writes to:
#   1. site_config.json → lms_brand_portal_title / lms_brand_tagline /
#      lms_brand_footer_text (the canonical source of truth — picked up
#      by every subsequent request without a restart).
#   2. Website Settings → app_name, brand_html (so the desk chrome
#      matches the login page).
#   3. System Settings → app_name (the title-bar / browser tab string).
#
# All three writes are idempotent. The function returns a structured
# report so the operator can audit what changed:
#   {"applied": [...], "skipped": [...], "failed": [...]}
def set_brand(
	portal_title: str | None = None,
	tagline: str | None = None,
	footer_text: str | None = None,
	primary_color: str | None = None,
	support_email: str | None = None,
	logo_path: str | None = None,
	favicon_path: str | None = None,
	dry_run: bool = False,
) -> dict:
	"""Set the operator's brand in site_config + Website Settings + System Settings.

	Args:
	    portal_title: the operator's product brand name (e.g. a specific
	        operator's product line — vendor-neutral in the source).
	        This is the value the login page, navbar, email subjects, and
	        desk chrome will display.
	    tagline: one-line under-brand text. Shows on the login page brand
	        panel.
	    footer_text: portal footer copy. Pass "" to hide the footer.
	    primary_color: hex colour for the portal accent.
	    support_email: operator support address.
	    logo_path: operator-supplied logo asset path. Defaults to the
	        bundled mark if not set.
	    favicon_path: operator-supplied favicon path. Defaults to the
	        bundled favicon if not set.
	    dry_run: when True, return the plan without writing anything.

	Returns:
	    dict with keys ``applied``, ``skipped``, ``failed`` — each a list
	    of human-readable strings describing what happened.
	"""
	import json
	from pathlib import Path

	import frappe

	# 1. Normalise + validate inputs.
	payload: dict[str, str | None] = {
		"portal_title": (portal_title or "").strip() or None,
		"tagline": (tagline or "").strip() or None,
		"footer_text": None if footer_text is None else footer_text.strip(),
		"primary_color": (primary_color or "").strip() or None,
		"support_email": (support_email or "").strip() or None,
		"logo_path": (logo_path or "").strip() or None,
		"favicon_path": (favicon_path or "").strip() or None,
	}
	# Discard empty strings so the caller can opt out of a key by passing "".
	payload = {k: v for k, v in payload.items() if v}

	if not payload:
		return {"applied": [], "skipped": [], "failed": ["nothing to set — all values empty"], "plan": ["DRY RUN — nothing to set"]}

	result = {"applied": [], "skipped": [], "failed": []}

	# 2. Plan (always shown for clarity, even on apply).
	plan = [
		"lms_brand_portal_title = " + repr(payload.get("portal_title", "<unchanged>")),
		"lms_brand_tagline = " + repr(payload.get("tagline", "<unchanged>")),
		"lms_brand_footer_text = " + repr(payload.get("footer_text", "<unchanged>")),
		"lms_brand_primary_color = " + repr(payload.get("primary_color", "<unchanged>")),
		"lms_support_email = " + repr(payload.get("support_email", "<unchanged>")),
		"lms_brand_logo_path = " + repr(payload.get("logo_path", "<unchanged>")),
		"lms_brand_favicon_path = " + repr(payload.get("favicon_path", "<unchanged>")),
		"Website Settings.app_name = " + repr(payload.get("portal_title", "<unchanged>")),
		"System Settings.app_name = " + repr(payload.get("portal_title", "<unchanged>")),
	]
	if dry_run:
		result["plan"] = ["DRY RUN — no writes performed"] + plan
		return result

	# 3. Write site_config.json (the canonical source of truth).
	site_config_key_map = {
		"portal_title": "lms_brand_portal_title",
		"tagline": "lms_brand_tagline",
		"footer_text": "lms_brand_footer_text",
		"primary_color": "lms_brand_primary_color",
		"support_email": "lms_support_email",
		"logo_path": "lms_brand_logo_path",
		"favicon_path": "lms_brand_favicon_path",
	}
	try:
		site_path = Path(frappe.utils.get_site_path("site_config.json"))
		if not site_path.exists():
			raise FileNotFoundError(f"site_config.json not found at {site_path}")
		raw = json.loads(site_path.read_text() or "{}")
		for src, dst in site_config_key_map.items():
			if src in payload:
				raw[dst] = payload[src]
				# In-memory mirror so the current process picks up the
				# change without a restart.
				frappe.conf[dst] = payload[src]
		site_path.write_text(json.dumps(raw, indent=2, sort_keys=True))
		result["applied"].append(
			f"site_config.json: wrote {len([k for k in payload if k in site_config_key_map])} key(s)"
		)
	except Exception as exc:  # noqa: BLE001
		result["failed"].append(f"site_config write failed: {exc}")
		return result

	# 4. Write Website Settings (the desk chrome).
	if "portal_title" in payload:
		try:
			if frappe.db.exists("DocType", "Website Settings"):
				website = frappe.get_single("Website Settings")
				website.app_name = payload["portal_title"]
				website.brand_html = f'<span style="font-weight:600">{payload["portal_title"]}</span>'
				if "logo_path" in payload:
					website.app_logo = payload["logo_path"]
				if "favicon_path" in payload:
					website.favicon = payload["favicon_path"]
					if frappe.get_meta("Website Settings").has_field("splash_image"):
						website.splash_image = payload["favicon_path"]
				website.flags.ignore_permissions = True
				website.save(ignore_permissions=True)
				result["applied"].append(
					"website_settings: app_name, brand_html"
					+ (", app_logo" if "logo_path" in payload else "")
					+ (", favicon, splash_image" if "favicon_path" in payload else "")
					+ " updated"
				)
		except Exception as exc:  # noqa: BLE001
			result["failed"].append(f"website_settings write failed: {exc}")

	# 5. Write System Settings (the title-bar / browser-tab string).
	if "portal_title" in payload:
		try:
			if frappe.db.exists("DocType", "System Settings"):
				frappe.db.set_single_value("System Settings", "app_name", payload["portal_title"])
				result["applied"].append("system_settings: app_name updated")
		except Exception as exc:  # noqa: BLE001
			result["failed"].append(f"system_settings write failed: {exc}")

	# 6. Clear caches so the next request sees the new brand without a restart.
	try:
		frappe.clear_cache()
		result["applied"].append("frappe cache cleared")
	except Exception as exc:  # noqa: BLE001
		result["skipped"].append(f"cache clear skipped: {exc}")

	return result


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
	# Desk admins (System Manager / Administrator) get a synthetic "Admin"
	# persona so the sidebar role label shows something useful and the nav
	# builder treats them like Admin-tagged addons (Admin sees all staff
	# addons). Without this, admins visiting /lms/* have an empty sidebar
	# brand and get incorrectly defaulted to the borrower nav.
	resolved_persona = resolve_portal_persona()
	if not resolved_persona and show_staff_desk_link():
		resolved_persona = "Admin"
	context.lms_persona = resolved_persona
	context.is_portal_borrower = "Customer" in user_roles and not context.is_portal_staff and not show_staff_desk_link()
	# R12 board: expose the per-persona permission flags on the template
	# context so nav templates and JS bootinfo can read them in one place.
	# (Previously only the portal JS used these; the templates assumed
	# context.lms_user_permissions existed and silently got AttributeError.)
	context.lms_user_permissions = _get_user_permissions(
		context.lms_persona, user_roles
	)
	context.lms_desk_home = lending_home_url()
	context.lms_show_staff_desk = bool(
		set(frappe.get_roles(frappe.session.user)) & {
			"System Manager",
			"Administrator",
			"Desk User",
		}
	)
	context.lms_risk_disclosure = (
		frappe.conf.get("lms_risk_disclosure")
		or frappe.conf.get("lms_email_legal_footer")
		or frappe._("Lending involves credit risk. Terms apply to approved borrowers only.")
	)
	# R18-5: surface the sandbox / production mode flag for the top banner.
	from lms_saas.api.compliance_config import is_sandbox_mode

	context.lms_sandbox_mode = is_sandbox_mode()
	# R44: expose the company's default currency so the portal shell
	# can set window.__lms_currency correctly. The previous template
	# defaulted to 'ZAR' when lms_currency was unset — which meant every
	# portal page showed ZAR even when the company was configured for
	# USD. Resolve from the default company's default_currency.
	try:
		_company = frappe.db.get_single_value("Global Defaults", "default_company")
		if _company:
			context.lms_currency = frappe.db.get_value("Company", _company, "default_currency") or "USD"
		else:
			context.lms_currency = frappe.conf.get("lms_currency") or "USD"
	except Exception:
		context.lms_currency = "USD"
	# R43: expose the current user's branch (Cost Center) so the portal
	# toolbar can render a "branch scope" badge. Falls back to empty
	# string when no branch is set (e.g. admins / borrowers).
	try:
		import lms_saas.api.staff as _staff
		context.lms_branch = _staff.get_current_user_branch() or ""
	except Exception:
		context.lms_branch = ""
	# R46-12: expose the current site's Company so the topbar can show
	# "Company · Branch" as a single context chip. Resolves through
	# `lms_company` site_config override, then Global Defaults, then
	# the first Company record (see lms_saas.api.lms_company for the
	# full resolution order). Empty string when the site has no Company
	# yet (e.g. fresh tenant bootstrap).
	try:
		from lms_saas.api.lms_company import get_lms_company
		context.lms_company = get_lms_company() or ""
	except Exception:
		context.lms_company = ""
	# R58: topbar company-chip popover metadata (country / abbr / tax_id /
	# default_currency). One row, one query — loaded up front so the popover
	# is instant on click. Falls back to "—" silently if Company isn't yet
	# wired (admins on a fresh tenant) — never raise into the page render.
	try:
		if context.lms_company:
			_meta = frappe.db.get_value(
				"Company",
				context.lms_company,
				["country", "abbr", "tax_id", "default_currency", "name"],
				as_dict=True,
			) or {}
			context.lms_company_country = _meta.get("country") or "—"
			context.lms_company_abbr = _meta.get("abbr") or "—"
			context.lms_company_tax_id = _meta.get("tax_id") or ""
			if _meta.get("default_currency"):
				context.lms_currency = _meta["default_currency"]
		else:
			context.lms_company_country = "—"
			context.lms_company_abbr = "—"
			context.lms_company_tax_id = ""
	except Exception:
		context.lms_company_country = "—"
		context.lms_company_abbr = "—"
		context.lms_company_tax_id = ""
	# R18-9: full display name (Employee / Customer / email-prefix fallback).
	context.lms_user_display_name = _resolve_user_display_name(frappe.session.user, context.lms_persona)
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
		_versioned_asset("js/lms_icons.js", "/assets/lms_saas/js/lms_icons.js"),
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

	# Detect desk admins (System Manager / Administrator without portal staff
	# or borrower roles). Without this guard, the `not is_staff` branch below
	# would dump admin users onto the borrower nav (My Loans / Apply / Pay),
	# which is meaningless and broken for them.
	roles = set(frappe.get_roles()) if frappe.session.user != "Guest" else set()
	is_desk_admin = bool(
		roles.intersection({"System Manager", "Administrator"})
	) and not is_staff and not is_borrower

	if is_borrower or (not is_staff and not is_desk_admin):
		items.extend([
			{"key": "loans", "label": "My Loans", "route": "/lms", "icon": "loans"},
			{"key": "apply", "label": "Apply", "route": "/lms/apply", "icon": "apply"},
			{"key": "pay", "label": "Pay", "route": "/lms/pay", "icon": "pay"},
		])

	# R18-16: tag each staff nav item with the perm that gates it so the
	# sidebar template can render `aria-disabled` honestly when the current
	# user lacks the perm (avoids the "22 nav items, 19 of which 403" trap).
	if is_staff:
		if persona == "Loan Officer":
			items.append({"key": "officer", "label": "Officer", "route": "/lms/officer", "icon": "officer", "requires_perm": "can_officer"})
		elif persona == "Branch Manager":
			items.append({"key": "manager", "label": "Manager", "route": "/lms/manager", "icon": "manager", "requires_perm": "can_manager"})
			items.append({"key": "manager_books", "label": "Books & Import", "route": "/lms/manager-books", "icon": "books", "requires_perm": "can_manager"})
		elif persona == "Operations Manager":
			# R52: Operations Manager — setup portal for loan catalogue +
			# operational config. The only nav item; the setup portal is
			# their entire surface (no portfolio / approvals / collections).
			items.append({"key": "setup", "label": "Setup", "route": "/lms/setup", "icon": "settings", "requires_perm": "can_setup"})
		# R18-17: the page, title, nav item, and Help link all use the single
	# string "Field Collection" — matches /lms/collect (page title) and
	# /lms-help/collector (nav label).
	items.append({"key": "collect", "label": "Field Collection", "route": "/lms/collect", "icon": "collect", "requires_perm": "can_collect"})

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
		"collect": "Field Collection",
		# ── Addon page titles ──
		# #35 fix: include both the addon registry keys (e.g.
		# "field_visits") AND the human-friendly nav keys (e.g. "visits")
		# so get_lms_page_context's default ``nav_key = addon`` does not
		# fall through to the brand name on /lms/visits and /lms/tasks.
		"announcements": "Announcements",
		"tasks": "Tasks",
		"task_management": "Tasks",
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
		"field_visits": "Field Visits",
		"inventory": "Inventory & Assets",
		"budgeting": "Budgeting",
		"insurance": "Insurance",
		"whatsapp": "WhatsApp",
		"reconciliation": "Wallet Reconciliation",
	}
	# R23-C1 fix: vendor-neutral fallback. The operator's brand is
	# available in context["brand"]["portal_title"] when configured;
	# when not, fall through to the vendor-neutral product family name
	# so a fresh install never leaks a competitor's brand.
	return labels.get(nav_active, context.get("brand", {}).get("portal_title") or "LMS")


def update_website_context(context):
	"""Global website hook — hide ERPNext portal sidebar for LMS borrowers."""
	from lms_saas.utils.portal import apply_borrower_web_context, show_staff_desk_link

	apply_borrower_web_context(context)
	apply_favicon_context(context)
	context.show_staff_desk = show_staff_desk_link()
	context.lms_show_staff_desk = show_staff_desk_link()
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
	# R24: hide the desk option on the login page for non-staff users.
	# The login page is a pre-authentication path chooser, so this is a
	# client-side UX gate (the server enforces it after login too).
	context.lms_show_staff_desk = bool(
		set(frappe.get_roles(frappe.session.user)) & {
			"System Manager",
			"Administrator",
			"Desk User",
		}
	)
	# R23-C1 fix: vendor-neutral fallback. The operator's brand from
	# `lms_brand_portal_title` shows on the login page when configured;
	# when not, fall through to the vendor-neutral product family name.
	# R27: install.py auto-detects the operator from the configured SMTP
	# domain and persists `lms_brand_portal_title` into site_config (so
	# `brand["portal_title"]` is populated before this resolution runs
	# in subsequent boots). Sites that haven't run an install hook yet
	# still get a sensible vendor-neutral name from DEFAULT_BRAND.
	product = brand.get("portal_title") or "LMS"
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


# ---------------------------------------------------------------------------
# Server-side icon helper
#
# The browser uses lms_icons.icon(name) (public/js/lms_icons.js) for JS-rendered
# surfaces. Server-rendered templates (the staff portal sidebar) need the same
# SVG markup without a round-trip to the client, so we mirror the icon registry
# here. Keep _LMS_ICON_PATHS in sync with lms_icons._PATHS in lms_icons.js.
# ---------------------------------------------------------------------------
_LMS_ICON_PATHS = {
	"dashboard": '<line x1="3" y1="3" x2="21" y2="3"/><rect x="3" y="13" width="7" height="8" rx="1"/><rect x="14" y="8" width="7" height="13" rx="1"/>',
	"bar-chart": '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>',
	"trending-up": '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
	"trophy": '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
	"leaderboard": "trophy",
	"clipboard": '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M9 12h6"/><path d="M9 16h6"/>',
	"file-text": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/>',
	"archive": '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><line x1="10" y1="12" x2="14" y2="12"/>',
	"folder": '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>',
	"log": "file-text",
	"scroll": '<path d="M8 21h12a2 2 0 0 0 2-2v-2H10v2a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v3h4"/><path d="M19 17V5a2 2 0 0 0-2-2H4"/>',
	"wallet": '<path d="M19 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5"/><path d="M16 12h.01"/>',
	"banknote": '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 12h.01M18 12h.01"/>',
	"receipt": '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M8 7h8"/><path d="M8 11h8"/><path d="M8 15h5"/>',
	"coins": "wallet",
	"user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
	"users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
	"alert-triangle": '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
	"check-circle": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
	"check": '<polyline points="20 6 9 17 4 12"/>',
	"message-square": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
	"message-circle": '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
	"megaphone": '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>',
	"ticket": '<path d="M3 7v2a3 3 0 0 1 0 6v2c0 1.1.9 2 2 2h14a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2Z"/>',
	"mail": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
	"list": '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
	"check-square": '<polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
	"shopping-cart": '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/>',
	"calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
	"clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
	"refresh": '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>',
	"target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
	"phone": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"/>',
	"home": '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><polyline points="9 22 9 12 15 12 15 22"/>',
	"shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/>',
	"package": '<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
	"briefcase": '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
	"building": '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01M16 6h.01M12 6h.01M12 10h.01M12 14h.01M16 10h.01M16 14h.01M8 10h.01M8 14h.01"/>',
	"bank": "building",
	"book-open": '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3Z"/>',
	"graduation-cap": '<path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/>',
	"map": '<polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21 3 6"/><line x1="9" y1="3" x2="9" y2="18"/><line x1="15" y1="6" x2="15" y2="21"/>',
	"send": '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
	"upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
	"download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
	"inbox": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/>',
	"diamond": '<path d="M6 3h12l4 6-10 13L2 9Z"/><path d="M11 3 8 9l4 13 4-13-3-6"/><path d="M2 9h20"/>',
	# Nav keys used by the staff/borrower sidebar (item.icon values)
	"loans": '<path d="M3 7h18"/><path d="M3 12h18"/><path d="M3 17h18"/><circle cx="7" cy="7" r="1.5" fill="currentColor"/><circle cx="7" cy="12" r="1.5" fill="currentColor"/><circle cx="7" cy="17" r="1.5" fill="currentColor"/>',
	"apply": '<path d="M12 5v14"/><path d="M5 12h14"/>',
	"pay": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/><circle cx="12" cy="15" r="1.5" fill="currentColor"/>',
	"officer": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
	"manager": '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
	"books": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
	"collect": '<path d="M12 2v20"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
	"account": '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
	"insurance": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="M12 8v6"/><path d="M9 11h6"/>',
	"savings": '<path d="M19 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5"/><circle cx="16" cy="12" r="1.5" fill="currentColor"/>',
	"payroll": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M8 14h4"/>',
	"visits": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/><path d="M9 16l2 2 4-4"/>',
	"budgeting": '<path d="M3 3v18h18"/><path d="M7 15l3-3 3 3 5-6"/>',
	"announcements": '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>',
	"regulatory": '<path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z"/><path d="M9 12l2 2 4-4"/>',
	"help": '<circle cx="12" cy="12" r="10"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.5-2.5 2-2.5 3.5"/><path d="M12 17h.01"/>',
	"hr": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
	"inventory": '<path d="M3 7l9-4 9 4-9 4-9-4z"/><path d="M3 7v10l9 4 9-4V7"/><path d="M12 11v10"/>',
	"procurement": '<circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.6L23 6H6"/>',
	"analytics": '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>',
	"training": '<path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/>',
	"tasks": '<path d="M9 11l3 3 8-8"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
	"feedback": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
	"recruitment": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
	"appraisals": '<path d="M12 2l2.4 7.4H22l-6 4.6 2.3 7.4-6.3-4.8L5.7 21.4 8 14 2 9.4h7.6z"/>',
	"loans-officer": "officer",
}


def _lms_asset_mtime(public_relpath: str) -> int:
	"""Return the file mtime (int seconds) of an asset under public/, used as a cache-bust
	query string by templates that load CSS/JS via ``<link>`` / ``<script>``.

	R27 (login scroll fix) — ``/login`` is a Frappe www route that does not pull
	``web_include_css``, so the login template loads its design tokens / themes /
	login styles directly. We version each URL by file mtime so deploys bust
	caches without a hard reload.

	The ``public_relpath`` is the path relative to ``apps/lms_saas/public/``
	(e.g. ``css/lms_login.css``). Returns the current epoch second when the file
	is missing so the URL still changes per deploy.
	"""
	import os

	full = os.path.join(os.path.dirname(__file__), "..", "public", public_relpath)
	try:
		return int(os.path.getmtime(os.path.normpath(full)))
	except OSError:
		return int(__import__("time").time())


def lms_icon_svg(name, size=18):
	"""Return an inline SVG string for a named icon (server-side mirror of lms_icons.icon).

	Used by server-rendered templates (staff portal sidebar) so icons appear
	without a client-side round trip. Unknown names fall back to a neutral
	diamond glyph so the UI never breaks.
	"""
	if not name:
		name = "diamond"
	seen = set()
	key = name
	while key in _LMS_ICON_PATHS and isinstance(_LMS_ICON_PATHS[key], str) and "<" not in _LMS_ICON_PATHS[key]:
		if key in seen:
			break
		seen.add(key)
		key = _LMS_ICON_PATHS[key]
	body = _LMS_ICON_PATHS.get(key)
	if not isinstance(body, str) or "<" in body or not body.strip():
		body = _LMS_ICON_PATHS["diamond"]
	return (
		'<svg class="lms-icon" width="{size}" height="{size}" viewBox="0 0 24 24" '
		'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
		'stroke-linejoin="round" aria-hidden="true" focusable="false">{body}</svg>'
	).format(size=size, body=body)


def _resolve_user_display_name(user, persona=None):
	"""Return the full display name for the current user.

	R18-9: stops showing "A / Admin" in the topbar avatar. Resolution order:
	  1. Employee.employee_name linked to the user (staff)
	  2. Customer.customer_name linked to the user (borrower)
	  3. Full Name from the User record (frappe.user.first_name + last_name)
	  4. Email-prefix fallback ("nigel.tj" from "nigel.tj@example.com")

	Returns "" for Guest sessions.
	"""
	if not user or user == "Guest":
		return ""
	try:
		import frappe as _fr
		# 1. Employee
		employee = _fr.db.get_value("Employee", {"user_id": user, "status": "Active"}, "employee_name")
		if employee:
			return employee
		# 2. Customer
		customer = _fr.db.get_value("Customer", {"user": user}, "customer_name")
		if customer:
			return customer
		# 3. User record
		first = _fr.db.get_value("User", user, "first_name") or ""
		last = _fr.db.get_value("User", user, "last_name") or ""
		full = f"{first} {last}".strip()
		if full:
			return full
		# 4. Email-prefix fallback
		if "@" in user:
			return user.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
		return user
	except Exception:  # noqa: BLE001
		# Never break page rendering on a name lookup miss; fall through to a
		# generic placeholder.
		return user or ""
