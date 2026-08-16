import os

from lms_saas.utils.frappe_version import lending_home_url

_APP_ROOT = os.path.dirname(os.path.abspath(__file__))
_PUBLIC_ROOT = os.path.join(_APP_ROOT, "public")


def _versioned_asset(public_path: str, assets_path: str) -> str:
	"""Append file mtime so desk CSS/JS refresh after deploy without hard-reload."""
	full = os.path.join(_PUBLIC_ROOT, public_path)
	version = int(os.path.getmtime(full)) if os.path.isfile(full) else 1
	return f"{assets_path}?v={version}"


app_name = "lms_saas"
app_title = "Kesari"
app_publisher = "Nigel Tsungai Jena"
app_description = "Kesari — loan management with stewardship and accountability"
app_email = "admin@3dprintingvillage.co.za"
app_license = "mit"

# Server-side SVG icon helper for Jinja templates (mirror of lms_icons in JS).
# R49: also expose get_email_brand_context so Frappe-default email template
# overrides (password_reset, new_user, etc.) can access brand tokens without
# hardcoding operator names or colors. DRY — single source of truth via
# utils.brand.enrich_brand → site_config lms_brand_*.
jinja = {
    "methods": [
        "lms_saas.utils.brand.lms_icon_svg",
        "lms_saas.utils.email.get_email_brand_context",
    ],
}

after_install = "lms_saas.install.after_install"
after_migrate = "lms_saas.install.after_install"
boot_session = "lms_saas.boot.apply_default_route"
# R35-#24 / R35-#26: rewrite Frappe's post-login ``home_page`` so portal
# users land on their persona page instead of /desk/lending (which Frappe
# v15+v16 no longer resolves to a Workspace).
on_login = "lms_saas.boot.on_login"

# R20-L1: clear transient security flags at end of request so a leaked
# `frappe.flags.ignore_permissions` set inside one endpoint cannot carry
# into a later endpoint within the same request lifecycle.
after_request = [
	"lms_saas.utils.request_lifecycle.reset_permission_flags",
]

# Desk boot splash (overridden by Website Settings splash_image on migrate).
splash_image = "/assets/lms_saas/images/lms-favicon.svg"

required_apps = [
	"frappe",
	"erpnext",
	"lending",
	"hrms",
]
# B19 (board MEDIUM): declare minimum versions. Major-version mismatches
# (e.g. installing against Frappe 14) cause silent breakage in newer
# loan Repayment Schedule schema and the popover API. Bench enforces
# these via `bench update --patch`; the historical bare-list form
# (`required_apps = ["erpnext", ...]`) accepted any version.
#
# R42 fix: Frappe v16's `parse_app_name` calls `name.rstrip("/")` on each
# entry, which only works on strings. The dict form
# (`{"name": "frappe", "version": ">=15.0.0,<16.0.0"}`) was supported in
# Frappe 14/15 but breaks `bench install-app` on v16 with
# `'dict' object has no attribute 'rstrip'`. The version constraints
# also capped at `<16.0.0` which would reject the v16 bench we run on.
# Reverted to the bare-list form; version enforcement moves to
# `bench update --patch` and the verify_spec suite.

add_to_apps_screen = [
	{
		"name": app_name,
		"logo": "/assets/lms_saas/images/lms-logo.svg",
		"title": app_title,
		"route": lending_home_url(),
	},
]

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            [
                "name",
                "in",
                [
                    "Loan-custom_days_past_due",
                    "Loan-custom_asset_classification",
                    "Loan-custom_lms_branch",
                    "Loan Application-custom_lms_branch",
                    "Loan-custom_loan_officer",
                    "Loan Application-custom_loan_officer",
                    "Customer-custom_lms_branch",
                    "Loan Application-custom_collateral_section",
                    "Loan Application-custom_collateral",
                    "Loan-custom_collateral_section",
                    "Loan-custom_collateral",
                    "Lead-custom_lms_branch",
                    "Lead-custom_loan_officer",
                    "Lead-custom_national_id_number",
                    "Lead-custom_consent_given",
                    "Lead-custom_consent_date",
                    "Opportunity-custom_lms_branch",
                    "Loan Application-custom_lending_group",
                    "Customer-custom_national_id_number",
                    "Employee-custom_lms_persona",
                ],
            ]
        ],
    },
    {
        "dt": "Property Setter",
        "filters": [["name", "in", ["Repayment Schedule-payment_date-in_list_view"]]],
    },
]

def _lms_css_stack(*surface_assets: str) -> list:
	base = [
		_versioned_asset("css/lms_tokens.css", "/assets/lms_saas/css/lms_tokens.css"),
		_versioned_asset("css/lms_themes/default.css", "/assets/lms_saas/css/lms_themes/default.css"),
		_versioned_asset("css/lms_themes/midnight.css", "/assets/lms_saas/css/lms_themes/midnight.css"),
		_versioned_asset("css/lms_themes/dark.css", "/assets/lms_saas/css/lms_themes/dark.css"),
		_versioned_asset("css/lms_components.css", "/assets/lms_saas/css/lms_components.css"),
	]
	return base + list(surface_assets)


app_include_css = _lms_css_stack(
	_versioned_asset("css/lms_desk.css", "/assets/lms_saas/css/lms_desk.css"),
)

app_include_js = [
	_versioned_asset("js/lms_brand.js", "/assets/lms_saas/js/lms_brand.js"),
	_versioned_asset("js/lms_theme.js", "/assets/lms_saas/js/lms_theme.js"),
	_versioned_asset("js/lms_desk.js", "/assets/lms_saas/js/lms_desk.js"),
]

web_include_css = _lms_css_stack(
	_versioned_asset("css/lms_portal.css", "/assets/lms_saas/css/lms_portal.css"),
	_versioned_asset("css/lms_staff_portal.css", "/assets/lms_saas/css/lms_staff_portal.css"),
	_versioned_asset("css/lms_form.css", "/assets/lms_saas/css/lms_form.css"),
	_versioned_asset("css/lms_login.css", "/assets/lms_saas/css/lms_login.css"),
	_versioned_asset("css/lms_help.css", "/assets/lms_saas/css/lms_help.css"),
)

web_include_js = [
	# Core portal JS is loaded conditionally per page via apply_portal_context().
	# Chart.js is loaded only on dashboard pages that need charts.
	_versioned_asset("js/lms_brand.js", "/assets/lms_saas/js/lms_brand.js"),
	_versioned_asset("js/lms_theme.js", "/assets/lms_saas/js/lms_theme.js"),
	_versioned_asset("js/vendor/chart.min.js", "/assets/lms_saas/js/vendor/chart.min.js"),
	_versioned_asset("js/lms_charts.js", "/assets/lms_saas/js/lms_charts.js"),
	_versioned_asset("js/lms_portal.js", "/assets/lms_saas/js/lms_portal.js"),
]

doctype_js = {
    "Loan": "public/js/loan.js",
    "Lead": "public/js/lead.js",
    "LMS Investor": "public/js/lms_investor.js",
    "LMS User Setup": "public/js/lms_user_setup.js",
}

website_route_rules = [
    {"from_route": "/lms", "to_route": "lms"},
    {"from_route": "/lms/loan", "to_route": "lms/loan"},
    {"from_route": "/lms/account", "to_route": "lms/account"},
    {"from_route": "/lms/apply", "to_route": "lms/apply"},
    {"from_route": "/lms/applications", "to_route": "lms/applications"},
    {"from_route": "/lms/pay", "to_route": "lms/pay"},
    {"from_route": "/lms/collect", "to_route": "lms/collect"},
    {"from_route": "/lms-portal/collector", "to_route": "lms-portal/collector"},
    {"from_route": "/lms-portal/officer", "to_route": "lms-portal/officer"},
    {"from_route": "/lms-portal/manager", "to_route": "lms-portal/manager"},
    {"from_route": "/lms/officer", "to_route": "lms/officer"},
    {"from_route": "/lms/manager", "to_route": "lms/manager"},
    {"from_route": "/lms/manager-books", "to_route": "lms/manager-books"},
    {"from_route": "/lms-help", "to_route": "lms-help"},
    {"from_route": "/lms-help/<slug>", "to_route": "lms-help"},
    # ── Addon routes ──
    {"from_route": "/lms/announcements", "to_route": "lms/announcements"},
    {"from_route": "/lms/tasks", "to_route": "lms/tasks"},
    {"from_route": "/lms/documents", "to_route": "lms/documents"},
    {"from_route": "/lms/support", "to_route": "lms/support"},
    {"from_route": "/lms/hr", "to_route": "lms/hr"},
    {"from_route": "/lms/analytics", "to_route": "lms/analytics"},
    {"from_route": "/lms/regulatory", "to_route": "lms/regulatory"},
    {"from_route": "/lms/payroll", "to_route": "lms/payroll"},
    {"from_route": "/lms/appraisals", "to_route": "lms/appraisals"},
    {"from_route": "/lms/training", "to_route": "lms/training"},
    {"from_route": "/lms/recruitment", "to_route": "lms/recruitment"},
    {"from_route": "/lms/procurement", "to_route": "lms/procurement"},
    {"from_route": "/lms/savings", "to_route": "lms/savings"},
    {"from_route": "/lms/feedback", "to_route": "lms/feedback"},
    {"from_route": "/lms/visits", "to_route": "lms/visits"},
    {"from_route": "/lms/inventory", "to_route": "lms/inventory"},
    {"from_route": "/lms/budgeting", "to_route": "lms/budgeting"},
    {"from_route": "/lms/insurance", "to_route": "lms/insurance"},
    {"from_route": "/lms/whatsapp", "to_route": "lms/whatsapp"},
    {"from_route": "/lms/reconciliation", "to_route": "lms/reconciliation"},
]

standard_portal_menu_items = [
    {"title": "My Loans", "route": "/lms", "reference_doctype": "Loan", "role": "Customer"},
    {"title": "My Applications", "route": "/lms/applications", "role": "Customer"},
    {"title": "Apply for Loan", "route": "/lms/apply", "role": "Customer"},
    {"title": "Make Payment", "route": "/lms/pay", "role": "Customer"},
    {"title": "My Account", "route": "/lms/account", "role": "Customer"},
]

update_website_context = "lms_saas.utils.brand.update_website_context"

# Post-login redirect: return the correct slugified desk workspace URL for each
# LMS role. Frappe's get_home_page() checks Portal Settings.default_portal_home
# (/lms) for ALL users, which sends desk staff to the portal. This hook wins over
# that default and returns /desk/<slug> for desk staff, /lms for borrowers.
get_website_user_home_page = "lms_saas.boot.get_lms_home_page"

override_whitelisted_methods = {
	# Shorthand cmd from portal links: /?cmd=web_logout
	"web_logout": "lms_saas.utils.web_auth.web_logout",
	# Full path for REST /api/method/frappe.handler.web_logout
	"frappe.handler.web_logout": "lms_saas.utils.web_auth.web_logout",
}

has_website_permission = {
    "Loan": "lms_saas.permissions.has_loan_permission",
    "Loan Application": "lms_saas.permissions.has_loan_application_permission",
    "Loan Repayment": "lms_saas.permissions.has_loan_repayment_permission",
    "Loan Disbursement": "lms_saas.permissions.has_loan_disbursement_permission",
    "LMS Investor Transaction": "lms_saas.permissions.has_investor_transaction_permission",
    "LMS Collateral": "lms_saas.permissions.has_collateral_permission",
    "LMS Borrower Compliance": "lms_saas.permissions.has_borrower_compliance_permission",
}

scheduler_events = {
    "daily": [
        "lms_saas.tasks.run_daily_loan_cron",
    ],
    "weekly": [
        "lms_saas.tasks.send_weekly_sandbox_kpi_pack",
    ],
    # R12 board (B6): CDPA retention scheduler. Run monthly — a no-op for most
    # sites (default retention window is 7 years), so daily would just flood
    # the background-jobs queue.
    "monthly": [
        "lms_saas.api.compliance.anonymize_expired_personal_data",
    ],
}

doc_events = {
    "LMS Borrower Compliance": {
        "after_insert": "lms_saas.api.aml.on_compliance_after_insert",
    },
    "Loan Application": {
        "before_submit": [
            "lms_saas.api.compliance.enforce_origination_controls",
            "lms_saas.api.aml.enforce_aml_on_origination",
            "lms_saas.api.decisioning.evaluate_credit_policy",
            "lms_saas.api.collateral.enforce_collateral_coverage",
            "lms_saas.api.underwriting.execute_credit_bureau_check",
        ],
    },
    "LMS Collateral": {
        "on_submit": "lms_saas.api.collateral.record_collateral_event",
        "on_cancel": "lms_saas.api.collateral.record_collateral_event",
    },
    "Loan": {
        # R20-P5: four-eyes must gate the Loan submit too — without this,
        # the maker of a Loan can self-disburse because the maker of the
        # originating Loan Application and the maker of the Loan are the
        # same user.
        "before_submit": "lms_saas.api.compliance.enforce_four_eyes",
        "on_submit": "lms_saas.api.compliance.record_money_event",
        "on_cancel": "lms_saas.api.compliance.record_money_event",
    },
    "Loan Disbursement": {
        "before_submit": "lms_saas.api.compliance.enforce_four_eyes",
        "on_submit": [
            "lms_saas.api.compliance.record_money_event",
            "lms_saas.api.disbursement_hooks.notify_disbursed",
        ],
        "on_cancel": "lms_saas.api.compliance.record_money_event",
    },
    "Loan Repayment": {
        "on_submit": [
            "lms_saas.api.compliance.record_money_event",
            "lms_saas.api.crm.send_repayment_branded_email",
        ],
        "on_cancel": "lms_saas.api.compliance.record_money_event",
    },
    "Lead": {
        "validate": "lms_saas.api.crm.validate_lead",
        "after_insert": "lms_saas.api.crm.on_lead_created",
    },
    "Loan Write Off": {
        "before_submit": "lms_saas.api.compliance.enforce_four_eyes",
        "on_submit": "lms_saas.api.compliance.record_money_event",
        "on_cancel": "lms_saas.api.compliance.record_money_event",
    },
    "LMS Investor Transaction": {
        "validate": "lms_saas.lms_saas.doctype.lms_investor_transaction.lms_investor_transaction.set_investor_accounts",
        "on_submit": [
            "lms_saas.api.investors.post_investor_gl_entry",
            "lms_saas.api.compliance.record_money_event",
        ],
        "on_cancel": [
            "lms_saas.api.investors.cancel_investor_gl_entry",
            "lms_saas.api.compliance.record_money_event",
        ],
    },
    # ── Addon doctype events ──
    "LMS Announcement": {
        "validate": "lms_saas.lms_saas.doctype.lms_announcement.lms_announcement.validate",
        "on_update": "lms_saas.lms_saas.doctype.lms_announcement.lms_announcement.on_update",
    },
    "LMS Addon Settings": {
        "on_update": "lms_saas.lms_saas.doctype.lms_addon_settings.lms_addon_settings.on_update",
    },
}


# ---------------------------------------------------------------------------
# Whitelist bootstrap
# ---------------------------------------------------------------------------
# Frappe only adds a function to `frappe.whitelisted` when the module that
# declares it is actually imported on the bench process. Our api/ submodules
# are not referenced by any auto-boot code path (no doctype, no scheduled
# job, no fixture depends on them), so on a fresh Frappe Cloud deploy
# the first request to /api/method/lms_saas.api.manager.get_approval_queue
# (or any other whitelisted function in api/) returned
# 'Function lms_saas.api.manager.get_approval_queue is not whitelisted.'
#
# Fix: register a `connect` hook that imports every lms_saas.api.* module
# once on the first request of the process. This is the canonical way
# Frappe apps ensure their @frappe.whitelist() methods are available
# without forcing operators to manually restart the bench.
#
# Idempotent + safe: `frappe.connect` runs at the start of every HTTP
# request; we keep a module-level flag so the package walk happens at
# most once per process. `importlib.import_module` is cached, so even
# a forced re-run is a no-op beyond the dict iteration.
import importlib
import pkgutil

import frappe

import lms_saas  # noqa: F401  (ensure package object is created)

_LMS_WHITELIST_BOOTSTRAP_DONE = False


def _bootstrap_lms_whitelisted_methods():
    """Import every lms_saas.api.* module so its @frappe.whitelist() methods
    are registered with the handler.

    R35-#22 hardening: the flag is only set after ALL modules import
    successfully. If any one fails (transient DB / Redis / sandbox import
    state), the bootstrap keeps retrying on the next request until every
    module is loaded — preventing the post-deploy "Function is not
    whitelisted" race that bites the very next API call after a long
    disburse round-trip on the live bench.
    """
    global _LMS_WHITELIST_BOOTSTRAP_DONE
    try:
        api_pkg = importlib.import_module("lms_saas.api")
    except Exception as exc:  # noqa: BLE001 - never break the request loop
        frappe.log_error(
            title="LMS whitelist bootstrap: import lms_saas.api failed",
            message=f"{type(exc).__name__}: {exc}",
        )
        return
    failures = 0
    for _mod_info in pkgutil.iter_modules(api_pkg.__path__):
        mod_name = f"lms_saas.api.{_mod_info.name}"
        try:
            importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001 - never break the request loop
            frappe.log_error(
                title=f"LMS whitelist bootstrap: import {mod_name} failed",
                message=f"{type(exc).__name__}: {exc}",
            )
            failures += 1
    # Only short-circuit future bootstraps once every module imported
    # clean. If even one failed, the next request will retry the sweep
    # so we don't leave a half-loaded lms_saas.api behind.
    if not failures:
        _LMS_WHITELIST_BOOTSTRAP_DONE = True


# Register the hook so it runs on every request lifecycle. Doing it via the
# official `connect` hook key (rather than monkey-patching frappe.connect)
# means Frappe runs it on every new request and operators do not need to
# restart the bench after a deploy.
connect = ["lms_saas.hooks._lms_on_connect"]


def _lms_on_connect(*_args, **_kwargs):
    """Frappe ``connect`` hook — run once per request lifecycle."""
    _bootstrap_lms_whitelisted_methods()

# Run the bootstrap at module import time so the whitelisted set is populated
# BEFORE any request is served. This eliminates the first-load race condition
# where the very first API call hits "not whitelisted" because the connect
# hook hasn't fired yet. The module-level flag keeps this idempotent.
_bootstrap_lms_whitelisted_methods()