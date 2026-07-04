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

after_install = "lms_saas.install.after_install"
after_migrate = "lms_saas.install.after_install"
boot_session = "lms_saas.boot.apply_default_route"

# Desk boot splash (overridden by Website Settings splash_image on migrate).
splash_image = "/assets/lms_saas/images/lms-favicon.svg"

required_apps = ["erpnext", "lending", "hrms"]

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
    {"from_route": "/lms-help", "to_route": "lms-help"},
    {"from_route": "/lms-help/<slug>", "to_route": "lms-help"},
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
}

scheduler_events = {
    "daily": [
        "lms_saas.tasks.run_daily_loan_cron",
    ],
    "weekly": [
        "lms_saas.tasks.send_weekly_sandbox_kpi_pack",
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
}
