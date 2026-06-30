import json
import os
import shutil

import frappe
from frappe import _

LMS_LEGACY_LANDING_WORKSPACE = "Loan Management"
LEGACY_WORKSPACES = ("LMS Operations",)
MODULE_NAME = "Lms Saas"
LENDING_MODULE = "Loan Management"
LOAN_DASHBOARD_NAME = "Loan Dashboard"
CHART_SOURCE_NAME = "LMS Portfolio"

# Role groups used to scope the sidebar navigation tree.
SYS_ROLE = "System Manager"
ALL_LMS_ROLES = ("LMS Admin", "LMS Branch Manager", "LMS Loan Officer", "LMS Collector")
ORIGINATION_ROLES = ("LMS Admin", "LMS Branch Manager", "LMS Loan Officer", SYS_ROLE)
COLLECTIONS_ROLES = ("LMS Admin", "LMS Branch Manager", "LMS Collector", SYS_ROLE)
OVERSIGHT_ROLES = ("LMS Admin", "LMS Branch Manager", SYS_ROLE)
ADMIN_ROLES = ("LMS Admin", SYS_ROLE)
EVERYONE_ROLES = (*ALL_LMS_ROLES, SYS_ROLE)
# CRM delete + native /app/crm report access (branch oversight, not collectors).
CRM_DELETE_ROLES = ("LMS Admin", "LMS Branch Manager", SYS_ROLE)
# Desk email from Customer / Loan timeline (collections + origination).
BORROWER_EMAIL_ROLES = (*ALL_LMS_ROLES, SYS_ROLE)

# Persona → roles/records mapping for the LMS User Setup onboarding form.
# Single source of truth (DRY): add a persona by adding one row here; the
# LMS User Setup doctype on_submit reads this config to decide which records
# to create. The before_validate User hook auto-applies the LMS Staff module
# profile for desk personas, so no extra wiring is needed.
PERSONA_CONFIG = {
    "Borrower": {
        "roles": ["Customer"],
        "create_customer": True,
        "create_employee": False,
        "desk": False,
        "landing_workspace": None,  # portal users land on /lms, not the desk
    },
    "Loan Officer": {
        "roles": ["LMS Loan Officer", "Desk User"],
        "create_customer": False,
        "create_employee": True,
        "desk": True,
        "landing_workspace": "Applications",  # origination pipeline is their daily focus
    },
    "Branch Manager": {
        "roles": ["LMS Branch Manager", "Desk User"],
        "create_customer": False,
        "create_employee": True,
        "desk": True,
        "landing_workspace": "Loans & Disbursements",  # oversight of the live book
    },
    "Collector": {
        "roles": ["LMS Collector", "Desk User"],
        "create_customer": False,
        "create_employee": True,
        "desk": True,
        "landing_workspace": "Collections",  # repayments + arrears are their daily focus
    },
    "Admin": {
        "roles": ["LMS Admin", "Desk User"],
        "create_customer": False,
        "create_employee": False,
        "desk": True,
        "landing_workspace": "Loan Management",  # full portfolio overview
    },
}

# Role → desk landing route (slugified workspace title). Single source of truth
# for post-login routing; boot.py reads this so each persona lands on the screen
# that matters most to their job instead of a generic home page.
ROLE_LANDING_ROUTES = {
    "LMS Admin": "loan-management",
    "LMS Branch Manager": "loans-disbursements",
    "LMS Loan Officer": "applications",
    "LMS Collector": "collections",
}

# Module Profile that hides every non-LMS module (and thus its sidebar workspace)
# from LMS staff. Blocking modules never affects DocType permissions.
MODULE_PROFILE_NAME = "LMS Staff"
CRM_MODULE = "CRM"
ALLOWED_MODULES = {MODULE_NAME, LENDING_MODULE, CRM_MODULE}

# Native Number Cards (type=Custom) backed by lms_saas.api.dashboard.get_kpi_card.
# Number Card autonames from `label`, so name == label here (used by workspace refs).
NUMBER_CARDS = (
    {"name": "LMS Portfolio Outstanding", "label": "Portfolio Outstanding", "kpi": "portfolio_outstanding", "color": "#2f4f46"},
    {"name": "LMS Active Loans", "label": "Active Loans (LMS)", "kpi": "active_loans", "color": "#5d9cec"},
    {"name": "LMS PAR 30+ Outstanding", "label": "PAR 30+ Outstanding", "kpi": "par30_outstanding", "color": "#f4b942"},
    {"name": "PAR 90+ Outstanding", "label": "PAR 90+ Outstanding", "kpi": "par90_outstanding", "color": "#e15c5c"},
    {"name": "LMS NPA Count", "label": "NPA Count", "kpi": "npa_count", "color": "#e15c5c"},
)

# Charts appended to the native Frappe Lending Loan Dashboard (Half width = 2-column grid).
LOAN_DASHBOARD_CHARTS = (
    {"name": "LMS Risk Composition", "width": "Half"},
    {"name": "LMS Collections Trend", "width": "Half"},
    {"name": "LMS Branch Concentration", "width": "Half"},
)

# Native Dashboard Charts (chart_type=Custom) backed by the LMS Portfolio source.
DASHBOARD_CHARTS = (
    {"name": "LMS Risk Composition", "metric": "risk_composition", "type": "Bar", "color": "#e15c5c", "col": 6},
    {"name": "LMS Collections Trend", "metric": "collections_trend", "type": "Line", "color": "#5faf61", "col": 6},
    {"name": "LMS Branch Concentration", "metric": "branch_concentration", "type": "Bar", "color": "#5d9cec", "col": 12},
)

# ---------------------------------------------------------------------------
# Sidebar navigation tree (single source of truth).
#
# Each entry is one Desk Workspace in the "Loan Management" app. The Frappe desk
# sidebar nests workspaces by `parent_page` and shows each one only if the user
# holds one of its `roles`, so this spec drives both the navigation and the
# per-role visibility. Add or re-scope a screen by editing one entry here; the
# after_migrate hook re-applies it. Nothing here touches frappe/erpnext/lending.
#
# Shortcut row keys: label, type (DocType|Report|URL), link_to, doc_view, color, url.
# Card group keys:   label, links[] where each link is (label, link_to, link_type, is_query_report).
# ---------------------------------------------------------------------------
LMS_NAV_SPEC = (
    {
        "key": "loan_management",
        "title": LMS_LEGACY_LANDING_WORKSPACE,
        "parent": None,
        "roles": EVERYONE_ROLES,
        "icon": "loan",
        "sequence_id": 1,
        "hidden": True,
        "landing": False,
        "greeting": "Portfolio overview and daily loan operations are on the Loan Dashboard.",
        "shortcuts": [],
        "cards": [],
    },
    {
        "key": "applications",
        "title": "Applications",
        "parent": "",
        "roles": ORIGINATION_ROLES,
        "icon": "edit",
        "sequence_id": 2,
        "greeting": "Capture, review, and progress loan applications from intake to approval.",
        "shortcut_heading": "Origination",
        "shortcuts": [
            {"label": "Loan Pipeline", "type": "DocType", "link_to": "Loan Application", "doc_view": "List", "color": "Cyan"},
            {"label": "New Application", "type": "URL", "url": "/app/loan-application/new", "color": "Blue"},
        ],
        "cards": [],
    },
    {
        "key": "crm",
        "title": "CRM & Prospects",
        "parent": "",
        "roles": ORIGINATION_ROLES,
        "icon": "crm",
        "sequence_id": 3,
        "hidden": True,
        "greeting": "Capture leads, track opportunities, and convert prospects to borrowers.",
        "shortcut_heading": "Prospects",
        "shortcuts": [
            {"label": "Lead Pipeline", "type": "DocType", "link_to": "Lead", "doc_view": "List", "color": "Cyan"},
            {"label": "New Lead", "type": "URL", "url": "/app/lead/new", "color": "Blue"},
            {"label": "Opportunities", "type": "DocType", "link_to": "Opportunity", "doc_view": "List", "color": "Green"},
            {"label": "Communications", "type": "DocType", "link_to": "Communication", "doc_view": "List", "color": "Grey"},
        ],
        "cards": [],
    },
    {
        "key": "loans_disbursements",
        "title": "Loans & Disbursements",
        "parent": "",
        "roles": ORIGINATION_ROLES,
        "icon": "loan",
        "sequence_id": 4,
        "greeting": "Manage the active loan book, schedules, and disbursements.",
        "shortcut_heading": "Servicing",
        "shortcuts": [
            {"label": "Active Loans", "type": "DocType", "link_to": "Loan", "doc_view": "List", "color": "Blue"},
            {"label": "Disbursements", "type": "DocType", "link_to": "Loan Disbursement", "doc_view": "List", "color": "Green"},
            {"label": "Loan Outstanding", "type": "Report", "link_to": "Loan Outstanding Report", "color": "Cyan"},
            {"label": "Loan Interest", "type": "Report", "link_to": "Loan Interest Report", "color": "Orange"},
        ],
        "cards": [],
    },
    {
        "key": "collections",
        "title": "Collections",
        "parent": "",
        "roles": COLLECTIONS_ROLES,
        "icon": "getting-started",
        "sequence_id": 5,
        "greeting": "Record repayments, monitor arrears, and support field collections.",
        "shortcut_heading": "Collections",
        "shortcuts": [
            {"label": "Collections Ledger", "type": "DocType", "link_to": "Loan Repayment", "doc_view": "List", "color": "Orange"},
            {"label": "New Repayment", "type": "URL", "url": "/app/loan-repayment/new", "color": "Green"},
            {"label": "PAR Snapshot", "type": "Report", "link_to": "Portfolio At Risk", "color": "Red"},
            {"label": "Arrears Ladder", "type": "Report", "link_to": "Arrears Aging", "color": "Orange"},
            {"label": "Collector Run Sheet", "type": "Report", "link_to": "Collection Sheet", "color": "Green"},
            {"label": "Past Cashflow", "type": "Report", "link_to": "Past Cashflow Report", "color": "Blue"},
            {"label": "Loan Repayment & Closure", "type": "Report", "link_to": "Loan Repayment and Closure", "color": "Green"},
            {"label": "Onboard Borrower", "type": "URL", "url": "/app/lms-user-setup/new", "color": "Blue"},
        ],
        "cards": [],
    },
    {
        "key": "borrowers_collateral",
        "title": "Borrowers & Collateral",
        "parent": "",
        "roles": ORIGINATION_ROLES,
        "icon": "users",
        "sequence_id": 6,
        "greeting": "Borrower profiles, KYC status, and pledged collateral.",
        "shortcut_heading": "Borrowers",
        "shortcuts": [
            {"label": "Borrower Ledger", "type": "DocType", "link_to": "Customer", "doc_view": "List", "color": "Cyan"},
            {"label": "Collateral Register", "type": "DocType", "link_to": "LMS Collateral", "doc_view": "List", "color": "Green"},
            {"label": "Compliance Queue", "type": "DocType", "link_to": "LMS Borrower Compliance", "doc_view": "List", "color": "Purple"},
            {"label": "Onboard User", "type": "URL", "url": "/app/lms-user-setup/new", "color": "Blue"},
        ],
        "cards": [],
    },
    {
        "key": "reports",
        "title": "Reports",
        "parent": "",
        "roles": EVERYONE_ROLES,
        "icon": "file",
        "sequence_id": 7,
        "greeting": "Portfolio performance, arrears, provisions, and management reporting.",
        "shortcut_heading": "Reports",
        "shortcuts": [
            {"label": "Portfolio At Risk", "type": "Report", "link_to": "Portfolio At Risk", "color": "Red"},
            {"label": "Arrears Aging", "type": "Report", "link_to": "Arrears Aging", "color": "Orange"},
            {"label": "Loan Outstanding", "type": "Report", "link_to": "Loan Outstanding Report", "color": "Blue"},
            {"label": "Loan Repayment & Closure", "type": "Report", "link_to": "Loan Repayment and Closure", "color": "Green"},
        ],
        "cards": [],
    },
    {
        "key": "compliance_risk",
        "title": "Compliance & Risk",
        "parent": "",
        "roles": OVERSIGHT_ROLES,
        "icon": "review",
        "sequence_id": 8,
        "greeting": "Credit provisions, operational incidents, and audit trail.",
        "shortcut_heading": "Compliance & risk",
        "shortcuts": [
            {"label": "IFRS9 ECL Provision", "type": "Report", "link_to": "IFRS9 ECL Provision", "color": "Red"},
            {"label": "Incident & Risk Register", "type": "DocType", "link_to": "LMS Incident Log", "doc_view": "List", "color": "Orange"},
            {"label": "Audit Trail", "type": "DocType", "link_to": "LMS Audit Event", "doc_view": "List", "color": "Grey"},
            {"label": "Notification Log", "type": "DocType", "link_to": "LMS Notification Log", "doc_view": "List", "color": "Cyan"},
            {"label": "Weekly Sandbox KPI", "type": "Report", "link_to": "LMS Sandbox Weekly KPI", "color": "Blue"},
        ],
        "cards": [],
    },
    {
        "key": "investors",
        "title": "Investors",
        "parent": "",
        "roles": ADMIN_ROLES,
        "icon": "organization",
        "sequence_id": 9,
        "greeting": "Investor register, capital movements, and ledger reconciliation.",
        "shortcut_heading": "Investors",
        "shortcuts": [
            {"label": "Investor Book", "type": "DocType", "link_to": "LMS Investor", "doc_view": "List", "color": "Blue"},
            {"label": "Investor Transactions", "type": "DocType", "link_to": "LMS Investor Transaction", "doc_view": "List", "color": "Cyan"},
        ],
        "cards": [],
    },
)


def after_install():
    _ensure_loan_agreement_template()
    _seed_branches()
    _seed_loan_product()
    _sync_loan_product_accounts()
    _setup_lms_roles()
    _ensure_lms_page_permissions()
    _ensure_lending_permissions()
    _ensure_lms_report_support_permissions()
    _sync_lms_report_roles()
    _sync_dashboard_chart_source()
    _sync_number_cards()
    _sync_dashboard_charts()
    _sync_loan_dashboard_extensions()
    _sync_lms_workspaces()
    _setup_module_lockdown()
    _setup_navbar_branding()
    _seed_print_formats()
    _sync_print_formats()
    _ensure_crm_permissions()
    _seed_dev_email_account()
    _seed_branded_emails()
    _setup_portal_menu()
    _ensure_customer_portal_role()
    _seed_payment_providers()


def _seed_payment_providers():
    """Default payment provider rows (disabled until configured)."""
    providers = (
        ("ecocash", "EcoCash"),
        ("onemoney", "OneMoney"),
        ("bank_transfer", "Bank Transfer"),
    )
    for code, label in providers:
        if frappe.db.exists("LMS Payment Provider", code):
            continue
        frappe.get_doc(
            {
                "doctype": "LMS Payment Provider",
                "provider_code": code,
                "provider_name": label,
                "enabled": 0,
            }
        ).insert(ignore_permissions=True)


def _ensure_loan_agreement_template():
    site_template = frappe.get_site_path("public", "files", "loan_template.docx")
    if os.path.exists(site_template):
        return

    app_template = frappe.get_app_path("lms_saas", "public", "files", "loan_template.docx")
    if not os.path.exists(app_template):
        return

    os.makedirs(os.path.dirname(site_template), exist_ok=True)
    shutil.copy2(app_template, site_template)


def _seed_branches():
    company = _default_company()
    if not company:
        return

    parent = frappe.db.get_value(
        "Cost Center",
        {"company": company, "is_group": 1, "parent_cost_center": ("is", "not set")},
        "name",
    ) or frappe.db.get_value("Cost Center", {"company": company, "is_group": 1}, "name")
    if not parent:
        return

    branches = ["Main Branch", "North Branch", "South Branch"]
    for branch_name in branches:
        if frappe.db.exists("Cost Center", {"cost_center_name": branch_name, "company": company}):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "Cost Center",
                "cost_center_name": branch_name,
                "company": company,
                "parent_cost_center": parent,
                "is_group": 0,
            }
        )
        doc.insert(ignore_permissions=True)


def _seed_loan_product():
    company = _default_company()
    if not company or frappe.db.exists("Loan Product", {"company": company, "product_code": "LMS-STD"}):
        return

    accounts = _loan_product_accounts(company)
    if not accounts:
        return

    doc = frappe.get_doc(
        {
            "doctype": "Loan Product",
            "product_code": "LMS-STD",
            "product_name": "LMS Standard Loan",
            "company": company,
            "maximum_loan_amount": 500000,
            "rate_of_interest": 24,
            "is_term_loan": 1,
            "repayment_schedule_type": "Monthly as per repayment start date",
            "days_past_due_threshold_for_npa": 90,
            "min_days_bw_disbursement_first_repayment": 30,
            "min_auto_closure_tolerance_amount": 1,
            "max_auto_closure_tolerance_amount": 10,
            "mode_of_payment": accounts.get("mode_of_payment"),
            "disbursement_account": accounts["disbursement_account"],
            "payment_account": accounts["payment_account"],
            "loan_account": accounts["loan_account"],
            "interest_income_account": accounts["interest_income_account"],
            "interest_receivable_account": accounts["interest_receivable_account"],
            "penalty_income_account": accounts["penalty_income_account"],
            "penalty_receivable_account": accounts["penalty_receivable_account"],
        }
    )
    doc.insert(ignore_permissions=True)


def _sync_loan_product_accounts():
    company = _default_company()
    if not company or not frappe.db.exists("Loan Product", "LMS-STD"):
        return
    accounts = _loan_product_accounts(company)
    if not accounts:
        return
    frappe.db.set_value(
        "Loan Product",
        "LMS-STD",
        {
            "disbursement_account": accounts["disbursement_account"],
            "payment_account": accounts["payment_account"],
            "loan_account": accounts["loan_account"],
            "interest_receivable_account": accounts["interest_receivable_account"],
            "penalty_receivable_account": accounts["penalty_receivable_account"],
        },
    )


def _loan_product_accounts(company):
    """Resolve loan product GL accounts.

    Precedence: explicit overrides in site_config (recommended for production)
    take priority over heuristic auto-discovery. Never returns a non-existent
    account name; logs and aborts mapping if a required account is missing.
    """

    def acc(account_type=None, root_type=None, name_like=None):
        filters = {"company": company, "is_group": 0}
        if account_type:
            filters["account_type"] = account_type
        if root_type:
            filters["root_type"] = root_type
        if name_like:
            filters["name"] = ("like", f"%{name_like}%")
        return frappe.db.get_value("Account", filters, "name")

    def configured(key):
        """Account explicitly configured in site_config, validated to exist."""
        name = frappe.conf.get(key)
        if name and frappe.db.exists("Account", {"name": name, "company": company}):
            return name
        if name:
            frappe.log_error(
                title="LMS GL config",
                message=f"Configured account '{name}' ({key}) not found for {company}",
            )
        return None

    loan_account = configured("lms_loan_account") or acc(account_type="Receivable") or acc(name_like="Debtors")
    income = configured("lms_interest_income_account") or acc(account_type="Income")
    bank = (
        configured("lms_disbursement_account")
        or acc(account_type="Cash")
        or acc(account_type="Bank")
        or acc(name_like="Cash")
    )
    mop = frappe.db.get_value("Mode of Payment", {}, "name")
    receivable = loan_account

    # All money-movement accounts must resolve to real GL accounts.
    if not loan_account or not bank or not income:
        frappe.log_error(
            title="LMS GL mapping incomplete",
            message=(
                f"company={company} loan_account={loan_account} bank={bank} income={income}. "
                "Set lms_loan_account / lms_interest_income_account / lms_disbursement_account "
                "in site_config."
            ),
        )
        return None

    return {
        "mode_of_payment": mop or "Cash",
        "disbursement_account": bank,
        "payment_account": bank,
        "loan_account": loan_account,
        "interest_income_account": income,
        "interest_receivable_account": receivable,
        "penalty_income_account": income,
        "penalty_receivable_account": receivable,
    }


def _default_company():
    return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
        "Company", {}, "name"
    )


def _setup_lms_roles():
    roles_config = {
        "LMS Admin": {
            "desk_access": 1,
            "home_page": "loan-management",
            "doctypes": _lms_doctypes() + _oversight_doctypes(),
            "perm": {
                "read": 1,
                "report": 1,
                "export": 1,
                "write": 1,
                "create": 1,
                "delete": 1,
                "submit": 1,
                "cancel": 1,
                "amend": 1,
            },
        },
        "LMS Branch Manager": {
            "desk_access": 1,
            "home_page": "loans-disbursements",
            "doctypes": _lms_doctypes() + _oversight_doctypes(),
            "perm": {"read": 1, "report": 1, "export": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1},
        },
        "LMS Loan Officer": {
            "desk_access": 1,
            "home_page": "applications",
            "doctypes": _lms_doctypes(),
            "perm": {"read": 1, "report": 1, "export": 1, "write": 1, "create": 1, "submit": 1},
        },
        "LMS Collector": {
            "desk_access": 1,
            "home_page": "collections",
            "doctypes": [
                "Loan",
                "Loan Repayment",
                "Loan Disbursement",
                "Customer",
                "LMS Borrower Compliance",
                "LMS Notification Log",
                "LMS User Setup",
            ],
            "perm": {"read": 1, "report": 1, "export": 1, "write": 0, "create": 0},
            # Collectors record field repayments — they need create+write on Loan
            # Repayment only, while staying read-only on the rest of the book.
            # Collectors can also onboard borrowers (but not staff — the validate
            # scope guard enforces that).
            "extra_perms": {
                "Loan Repayment": {"read": 1, "write": 1, "create": 1, "submit": 1},
                "LMS User Setup": {"read": 1, "write": 1, "create": 1, "submit": 1},
            },
        },
    }

    for role_name, cfg in roles_config.items():
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": cfg["desk_access"]}).insert(
                ignore_permissions=True
            )

        # Set the Role home_page so the post-login redirect (auth.py → get_home_page)
        # sends desk staff to their role-specific workspace, not the portal /lms.
        # Portal Settings.default_portal_home is /lms, which get_home_page() returns
        # for ALL users unless a Role.home_page override exists (Role is checked first).
        # The value must be the full /desk/<slug> path because get_home_page() returns
        # it as-is to the login redirect (no slugification is applied).
        home_page = cfg.get("home_page")
        if home_page:
            from lms_saas.utils.frappe_version import desk_prefix
            from frappe.desk.utils import slug

            workspace_title = {
                "loan-management": "Loan Management",
                "loans-disbursements": "Loans & Disbursements",
                "applications": "Applications",
                "collections": "Collections",
            }.get(home_page, home_page)
            frappe.db.set_value("Role", role_name, "home_page", f"{desk_prefix()}/{slug(workspace_title)}")

        for dt in cfg["doctypes"]:
            _ensure_role_perm(role_name, dt, cfg.get("perm", {}))

        # Per-doctype overrides (e.g. Collector can create Loan Repayments but
        # is read-only on everything else). These win over the default perm set.
        for dt, extra in (cfg.get("extra_perms") or {}).items():
            _ensure_role_perm(role_name, dt, extra)


def _ensure_lms_page_permissions():
    """Desk workspace routes resolve through Page — LMS staff need read access."""
    for role in ALL_LMS_ROLES:
        _ensure_role_perm(role, "Page", {"read": 1})


def _lending_doctypes():
    return [
        "Loan",
        "Loan Application",
        "Loan Repayment",
        "Loan Disbursement",
        "Loan Product",
        "Loan Repayment Schedule",
    ]


def _lms_doctypes():
    return _lending_doctypes() + [
        "Customer",
        "LMS Investor",
        "LMS Investor Transaction",
        "LMS Borrower Compliance",
        "LMS Collateral",
        "LMS Payment Intent",
        "LMS Payment Provider",
        "LMS Payment Reconciliation",
        "LMS API Key",
        "LMS Credit Policy",
        "LMS Webhook Subscription",
        "LMS Lending Group",
        "LMS Group Meeting",
        "LMS Center",
        "LMS Savings Account",
        "LMS Savings Transaction",
        "LMS User Setup",
    ]


def _oversight_doctypes():
    return ["LMS Incident Log", "LMS Audit Event", "LMS Notification Log"]


LMS_REPORT_NAMES = (
    "Portfolio At Risk",
    "Arrears Aging",
    "Collection Sheet",
    "IFRS9 ECL Provision",
    "LMS Sandbox Weekly KPI",
    "LMS Group Portfolio",
)

# Standard Frappe Lending script reports (see frappe.io/lending docs). Links are
# omitted from workspaces until the Report record exists (after lending migrate).
LENDING_PORTFOLIO_REPORT_NAMES = (
    "Loan Outstanding Report",
    "Past Cashflow Report",
    "Future Cashflow Report",
    "Loan Statement of Account",
    "ALM Audit Report",
    "Loan Interest Report",
)

LENDING_SECURITY_REPORT_NAMES = (
    "Loan Security Ledger",
    "Loan Security Exposure",
    "Applicant-Wise Loan Security Exposure",
    "Loan Security Status",
    "Loan Repayment and Closure",
)

LENDING_STANDARD_REPORT_NAMES = LENDING_PORTFOLIO_REPORT_NAMES + LENDING_SECURITY_REPORT_NAMES

DESK_REPORT_NAMES = LMS_REPORT_NAMES + LENDING_STANDARD_REPORT_NAMES

# Workspace card groups: label -> report display names (link tuples built at sync).
LENDING_REPORT_CARD_GROUPS = (
    ("Lending Reports", LENDING_PORTFOLIO_REPORT_NAMES),
    ("Loan Security", LENDING_SECURITY_REPORT_NAMES),
    ("LMS Portfolio & Collections", LMS_REPORT_NAMES),
)


def _ensure_lms_report_support_permissions():
    """Reports link to branches (Cost Center) and company filters — LMS staff need read."""
    read_only = {"read": 1}
    for role in (*ALL_LMS_ROLES, SYS_ROLE):
        for doctype in ("Cost Center", "Company"):
            _ensure_role_perm(role, doctype, read_only)


def _sync_lms_report_roles():
    """Ensure LMS and lending script reports are runnable by all desk LMS roles."""
    for report_name in DESK_REPORT_NAMES:
        if not frappe.db.exists("Report", report_name):
            continue
        for role in EVERYONE_ROLES:
            if frappe.db.exists(
                "Has Role",
                {"parent": report_name, "parenttype": "Report", "parentfield": "roles", "role": role},
            ):
                continue
            frappe.get_doc(
                {
                    "doctype": "Has Role",
                    "parent": report_name,
                    "parenttype": "Report",
                    "parentfield": "roles",
                    "role": role,
                }
            ).insert(ignore_permissions=True)


# Script/query reports linked from ERPNext CRM workspace (/app/crm).
CRM_REPORT_NAMES = (
    "Lead Details",
    "Sales Pipeline Analytics",
    "Opportunity Summary by Sales Stage",
    "Prospects Engaged But Not Converted",
    "First Response Time for Opportunity",
    "Inactive Customers",
    "Campaign Efficiency",
    "Lead Owner Efficiency",
)


def _sync_crm_report_roles():
    """CRM analytics reports are for origination roles only (not collectors)."""
    for report_name in CRM_REPORT_NAMES:
        if not frappe.db.exists("Report", report_name):
            continue
        for role in ORIGINATION_ROLES:
            if frappe.db.exists(
                "Has Role",
                {"parent": report_name, "parenttype": "Report", "parentfield": "roles", "role": role},
            ):
                continue
            frappe.get_doc(
                {
                    "doctype": "Has Role",
                    "parent": report_name,
                    "parenttype": "Report",
                    "parentfield": "roles",
                    "role": role,
                }
            ).insert(ignore_permissions=True)


def _ensure_lending_permissions():
    """Script reports require ref_doctype 'report' perm (not just read)."""
    full_perm = {
        "read": 1,
        "report": 1,
        "export": 1,
        "write": 1,
        "create": 1,
        "delete": 1,
        "submit": 1,
        "cancel": 1,
        "amend": 1,
    }
    for role in ("System Manager", "Administrator"):
        for dt in _lending_doctypes():
            _ensure_role_perm(role, dt, full_perm)
        _sync_standard_docperm_report(role, _lending_doctypes())

    for dt in ("LMS Investor", "LMS Investor Transaction", "LMS Borrower Compliance", "LMS Collateral"):
        _ensure_role_perm("System Manager", dt, full_perm)
        _ensure_role_perm("Administrator", dt, full_perm)

    report_perm = {"read": 1, "report": 1, "export": 1}
    for dt in _lending_doctypes():
        _ensure_role_perm(
            "LMS Admin",
            dt,
            {**report_perm, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1},
        )

    for role in ("LMS Branch Manager", "LMS Loan Officer", "LMS Collector"):
        for dt in _lending_doctypes():
            _ensure_role_perm(role, dt, {**report_perm, "write": 1, "create": 1})


def _ensure_role_perm(role, doctype, extra_perm=None):
    extra_perm = extra_perm or {}
    existing = frappe.db.get_value("Custom DocPerm", {"role": role, "parent": doctype}, "name")

    if existing:
        updates = {}
        for field in (
            "read",
            "report",
            "export",
            "write",
            "create",
            "delete",
            "submit",
            "cancel",
            "amend",
            "email",
        ):
            if field in extra_perm:
                updates[field] = extra_perm[field]
        if updates:
            frappe.db.set_value("Custom DocPerm", existing, updates)
        return

    perm = {
        "doctype": "Custom DocPerm",
        "parent": doctype,
        "parenttype": "DocType",
        "parentfield": "permissions",
        "role": role,
        "read": extra_perm.get("read", 1),
        "report": extra_perm.get("report", 0),
        "export": extra_perm.get("export", 0),
        "write": extra_perm.get("write", 1),
        "create": extra_perm.get("create", 1),
        "delete": extra_perm.get("delete", 0),
        "submit": extra_perm.get("submit", 0),
        "cancel": extra_perm.get("cancel", 0),
        "amend": extra_perm.get("amend", 0),
        "email": extra_perm.get("email", 0),
    }
    frappe.get_doc(perm).insert(ignore_permissions=True)


def _sync_standard_docperm_report(role, doctypes):
    """Update standard DocPerm rows shipped by Lending (report=0 by default)."""
    for dt in doctypes:
        name = frappe.db.get_value("DocPerm", {"parent": dt, "role": role}, "name")
        if name:
            frappe.db.set_value("DocPerm", name, {"report": 1, "export": 1})


def _report_link_tuple(report_name):
    return (report_name, report_name, "Report", 1)


def _existing_report_links(report_names):
    return [_report_link_tuple(name) for name in report_names if frappe.db.exists("Report", name)]


def _reports_workspace_cards():
    cards = []
    for card_label, report_names in LENDING_REPORT_CARD_GROUPS:
        links = _existing_report_links(report_names)
        if links:
            cards.append({"label": card_label, "links": links})
    return cards


def _resolve_workspace_spec(spec):
    """Expand dynamic workspace fragments (e.g. report card menus)."""
    if spec.get("key") == "reports":
        return {**spec, "cards": _reports_workspace_cards()}
    return spec


def _sync_lms_workspaces():
    """Create/refresh the 'Loan Management' sidebar app tree from LMS_NAV_SPEC.

    Each spec entry becomes one public Workspace (module Lms Saas). Children nest
    under the landing via parent_page, and each workspace's `roles` control which
    staff see it in the sidebar. Idempotent: safe to re-run on every migrate.
    """
    _retire_legacy_workspaces()
    for spec in LMS_NAV_SPEC:
        _upsert_workspace(_resolve_workspace_spec(spec))


def _retire_legacy_workspaces():
    """Remove superseded LMS workspaces (our own records) so the sidebar is clean."""
    for name in LEGACY_WORKSPACES:
        if frappe.db.exists("Workspace", name):
            frappe.delete_doc("Workspace", name, ignore_permissions=True, force=True)


def _upsert_workspace(spec):
    name = spec["title"]
    if frappe.db.exists("Workspace", name):
        ws = frappe.get_doc("Workspace", name)
    else:
        ws = frappe.new_doc("Workspace")
        ws.name = name

    ws.label = name
    ws.title = name
    ws.module = MODULE_NAME
    ws.icon = spec.get("icon") or "loan"
    ws.public = 1
    ws.is_hidden = 1 if spec.get("hidden") else 0
    ws.parent_page = spec.get("parent") or ""
    ws.sequence_id = spec.get("sequence_id") or 0
    ws.indicator_color = "blue"
    ws.content = json.dumps(_ws_content_blocks(spec))

    ws.roles = []
    for role in spec.get("roles", ()):  # role-scoped sidebar visibility
        ws.append("roles", {"role": role})

    ws.shortcuts = []
    for sc in spec.get("shortcuts", ()):  # big clickable tiles (1-click to screen)
        if sc.get("type") == "Report" and not frappe.db.exists("Report", sc.get("link_to")):
            continue
        row = dict(sc)
        if row.get("url"):
            from lms_saas.utils.frappe_version import rewrite_desk_path

            row["url"] = rewrite_desk_path(row["url"])
        ws.append("shortcuts", row)

    ws.links = []
    for card in spec.get("cards", ()):  # link-card menus
        links = card.get("links", [])
        ws.append("links", {"type": "Card Break", "label": card["label"], "link_count": len(links)})
        for label, link_to, link_type, is_query in links:
            row = {"type": "Link", "label": label, "link_to": link_to, "link_type": link_type}
            if is_query:
                row["is_query_report"] = 1
            ws.append("links", row)

    ws.number_cards = []
    ws.charts = []

    ws.flags.ignore_permissions = True
    ws.save(ignore_permissions=True)


def _ws_content_blocks(spec):
    """Build workspace content layout blocks (Frappe v15/v16 compatible)."""
    key = spec["key"]
    blocks = [
        {
            "id": f"{key}_hdr",
            "type": "header",
            "data": {
                "text": (
                    f'<span class="h4 lms-hero__title-wrap"><b>{spec["title"]}</b></span>'
                    f'<p class="text-muted lms-hero__subtitle">{spec.get("greeting", "")}</p>'
                ),
                "col": 12,
            },
        }
    ]

    shortcuts = spec.get("shortcuts") or []
    if shortcuts:
        heading = spec.get("shortcut_heading", "Quick actions")
        blocks.append(
            {"id": f"{key}_hdr_sc", "type": "header", "data": {"text": f'<span class="h5"><b>{heading}</b></span>', "col": 12}}
        )
        for i, sc in enumerate(shortcuts):
            sc_col = sc.get("col")
            if not sc_col:
                if len(shortcuts) <= 2:
                    sc_col = 6
                elif len(shortcuts) == 3:
                    sc_col = 4
                else:
                    sc_col = 3
            blocks.append({"id": f"{key}_sc_{i}", "type": "shortcut", "data": {"shortcut_name": sc["label"], "col": sc_col}})
        blocks.append({"id": f"{key}_sp_sc", "type": "spacer", "data": {"col": 12}})

    cards = spec.get("cards") or []
    if cards:
        blocks.append(
            {"id": f"{key}_hdr_br", "type": "header", "data": {"text": '<span class="h5"><b>Browse</b></span>', "col": 12}}
        )
        for i, card in enumerate(cards):
            blocks.append({"id": f"{key}_card_{i}", "type": "card", "data": {"card_name": card["label"], "col": 4}})

    return blocks


def _sync_dashboard_chart_source():
    """Register the custom chart source that feeds the native LMS charts.

    The matching JS (frappe.dashboards.chart_sources["LMS Portfolio"]) lives at
    lms_saas/dashboard_chart_source/lms_portfolio/lms_portfolio.js and is read by
    Frappe via get_module_path; only the DB record is created here.
    """
    if frappe.db.exists("Dashboard Chart Source", CHART_SOURCE_NAME):
        return
    frappe.get_doc(
        {
            "doctype": "Dashboard Chart Source",
            "source_name": CHART_SOURCE_NAME,
            "module": MODULE_NAME,
            "timeseries": 0,
        }
    ).insert(ignore_permissions=True)


def _sync_number_cards():
    """Create/refresh native KPI Number Cards (idempotent, code-managed)."""
    for card in NUMBER_CARDS:
        payload = {
            "type": "Custom",
            "method": "lms_saas.api.dashboard.get_kpi_card",
            "document_type": "Loan",
            "filters_json": json.dumps({"kpi": card["kpi"]}),
            "is_public": 1,
            "show_percentage_stats": 0,
            "module": MODULE_NAME,
            "color": card["color"],
        }
        if frappe.db.exists("Number Card", card["name"]):
            frappe.db.set_value("Number Card", card["name"], {**payload, "label": card["label"]})
            continue
        frappe.get_doc(
            {
                "doctype": "Number Card",
                "name": card["name"],
                "label": card["label"],
                **payload,
            }
        ).insert(ignore_permissions=True)


def _sync_dashboard_charts():
    """Create/refresh native Dashboard Charts (idempotent, code-managed)."""
    for chart in DASHBOARD_CHARTS:
        payload = {
            "chart_type": "Custom",
            "source": CHART_SOURCE_NAME,
            "type": chart["type"],
            "filters_json": json.dumps({"metric": chart["metric"]}),
            "is_public": 1,
            "color": chart["color"],
            "module": MODULE_NAME,
        }
        if frappe.db.exists("Dashboard Chart", chart["name"]):
            frappe.db.set_value("Dashboard Chart", chart["name"], payload)
            continue
        frappe.get_doc(
            {
                "doctype": "Dashboard Chart",
                "chart_name": chart["name"],
                "document_type": "Loan",
                **payload,
            }
        ).insert(ignore_permissions=True)


def _append_loan_dashboard_card(card_name: str) -> None:
    """Link a Number Card to Loan Dashboard without saving the standard parent doc."""
    if not frappe.db.exists("Number Card", card_name):
        return
    if frappe.db.exists(
        "Number Card Link",
        {"parent": LOAN_DASHBOARD_NAME, "parenttype": "Dashboard", "card": card_name},
    ):
        return
    idx = frappe.db.count(
        "Number Card Link",
        {"parent": LOAN_DASHBOARD_NAME, "parenttype": "Dashboard"},
    ) + 1
    frappe.get_doc(
        {
            "doctype": "Number Card Link",
            "parent": LOAN_DASHBOARD_NAME,
            "parenttype": "Dashboard",
            "parentfield": "cards",
            "idx": idx,
            "card": card_name,
        }
    ).insert(ignore_permissions=True)


def _append_loan_dashboard_chart(chart_name: str, width: str = "Half") -> None:
    """Link a Dashboard Chart to Loan Dashboard without saving the standard parent doc."""
    if not frappe.db.exists("Dashboard Chart", chart_name):
        return
    if frappe.db.exists(
        "Dashboard Chart Link",
        {"parent": LOAN_DASHBOARD_NAME, "parenttype": "Dashboard", "chart": chart_name},
    ):
        return
    idx = frappe.db.count(
        "Dashboard Chart Link",
        {"parent": LOAN_DASHBOARD_NAME, "parenttype": "Dashboard"},
    ) + 1
    frappe.get_doc(
        {
            "doctype": "Dashboard Chart Link",
            "parent": LOAN_DASHBOARD_NAME,
            "parenttype": "Dashboard",
            "parentfield": "charts",
            "idx": idx,
            "chart": chart_name,
            "width": width,
        }
    ).insert(ignore_permissions=True)


def _sync_loan_dashboard_extensions():
    """Append LMS risk KPIs and charts to the native Frappe Lending Loan Dashboard."""
    if not frappe.db.exists("Dashboard", LOAN_DASHBOARD_NAME):
        return

    _sync_number_cards()
    _sync_dashboard_charts()

    for card in NUMBER_CARDS:
        card_name = card["name"]
        if not frappe.db.exists("Number Card", card_name) and frappe.db.exists(
            "Number Card", card["label"]
        ):
            card_name = card["label"]
        _append_loan_dashboard_card(card_name)

    for chart in LOAN_DASHBOARD_CHARTS:
        _append_loan_dashboard_chart(chart["name"], chart["width"])


def _seed_print_formats():
    formats = [
        {
            "name": "LMS Loan Statement",
            "doc_type": "Loan",
            "standard": "Yes",
            "html": frappe.read_file(
                frappe.get_app_path("lms_saas", "templates", "print", "lms_loan_statement.html")
            ),
        },
        {
            "name": "LMS Loan Agreement",
            "doc_type": "Loan",
            "standard": "Yes",
            "html": frappe.read_file(
                frappe.get_app_path("lms_saas", "templates", "print", "lms_loan_agreement.html")
            ),
        },
        {
            "name": "LMS Collection Receipt",
            "doc_type": "Loan Repayment",
            "standard": "Yes",
            "html": frappe.read_file(
                frappe.get_app_path("lms_saas", "templates", "print", "lms_collection_receipt.html")
            ),
        },
        {
            "name": "LMS Repayment Schedule",
            "doc_type": "Loan",
            "standard": "Yes",
            "html": frappe.read_file(
                frappe.get_app_path("lms_saas", "templates", "print", "lms_repayment_schedule.html")
            ),
        },
    ]
    for pf in formats:
        if frappe.db.exists("Print Format", pf["name"]):
            continue
        doc = frappe.get_doc({"doctype": "Print Format", **pf})
        doc.insert(ignore_permissions=True)


def _sync_print_formats():
    """Refresh print HTML from app templates on migrate."""
    formats = {
        "LMS Loan Statement": "lms_loan_statement.html",
        "LMS Loan Agreement": "lms_loan_agreement.html",
        "LMS Collection Receipt": "lms_collection_receipt.html",
        "LMS Repayment Schedule": "lms_repayment_schedule.html",
    }
    for name, filename in formats.items():
        if not frappe.db.exists("Print Format", name):
            continue
        html = frappe.read_file(frappe.get_app_path("lms_saas", "templates", "print", filename))
        frappe.db.set_value("Print Format", name, "html", html)


def _crm_core_doctypes():
    return ("Lead", "Opportunity", "Contact", "Communication")


def _crm_email_support_doctypes():
    """Desk compose/send needs read on outgoing account + templates (Frappe defaults are Inbox User / Desk User)."""
    return ("Email Account", "Email Template")


def _crm_master_read_doctypes():
    """Link fields on Lead/Opportunity forms and native CRM workspace master cards."""
    return (
        "Territory",
        "Customer Group",
        "Lead Source",
        "Sales Stage",
        "Sales Person",
        "Prospect",
    )


def _crm_rw_perm():
    return {"read": 1, "report": 1, "export": 1, "write": 1, "create": 1, "email": 1}


def _crm_read_only_perm():
    return {"read": 1, "report": 1, "export": 0, "write": 0, "create": 0, "delete": 0, "email": 0}


def _crm_email_support_read_perm():
    return {"read": 1, "write": 0, "create": 0, "delete": 0, "email": 0}


def _crm_address_perm():
    return {"read": 1, "write": 1, "create": 1, "export": 0, "report": 0, "delete": 0, "email": 0}


def _ensure_crm_permissions():
    """Role-scoped CRM + desk email (STAFF_GUIDE §2; collectors get borrower email only).

    | Capability                         | Admin / Mgr / Officer | Collector |
    |------------------------------------|-----------------------|-----------|
    | Lead / Opportunity / Contact       | read/write + email    | —         |
    | Communication (CRM + collections)  | read/write + email    | read/write + email |
    | Email Account / Template (read)    | yes                   | yes       |
    | Customer (email from timeline)     | yes                   | yes       |
    | CRM masters (Territory, …)         | read                  | —         |
    | CRM delete                         | Admin, Branch Mgr     | —         |
    """
    crm_rw = _crm_rw_perm()
    crm_delete = {**crm_rw, "delete": 1}
    master_read = _crm_read_only_perm()
    email_read = _crm_email_support_read_perm()

    for role in ORIGINATION_ROLES:
        for dt in _crm_core_doctypes():
            _ensure_role_perm(role, dt, crm_rw)
        for dt in _crm_email_support_doctypes():
            _ensure_role_perm(role, dt, email_read)
        for dt in _crm_master_read_doctypes():
            _ensure_role_perm(role, dt, master_read)
        _ensure_role_perm(role, "Address", _crm_address_perm())
        _ensure_role_perm(role, "Print Format", {"read": 1, "write": 0, "create": 0, "delete": 0})

    for role in CRM_DELETE_ROLES:
        for dt in _crm_core_doctypes():
            _ensure_role_perm(role, dt, crm_delete)

    for role in BORROWER_EMAIL_ROLES:
        _ensure_role_perm(role, "Customer", {"email": 1})
        for dt in _crm_email_support_doctypes():
            _ensure_role_perm(role, dt, email_read)
        _ensure_role_perm(role, "Print Format", {"read": 1, "write": 0, "create": 0, "delete": 0})

    for role in ("LMS Collector",):
        _ensure_role_perm(role, "Communication", crm_rw)

    _sync_crm_report_roles()


def _seed_dev_email_account():
    """Default outgoing account for local dev (developer_mode / lms_seed_dev_email only)."""
    from lms_saas.setup.seed_dev_email import ensure_dev_email_account

    ensure_dev_email_account()


def _seed_branded_emails():
    from lms_saas.utils.email import seed_email_templates, sync_email_template_records

    seed_email_templates()
    sync_email_template_records()

    # Legacy plain Notification replaced by branded doc_event email on Loan Repayment.
    if frappe.db.exists("Notification", "LMS Loan Repayment Received"):
        frappe.db.set_value("Notification", "LMS Loan Repayment Received", "enabled", 0)
    elif not frappe.db.exists("Notification", "LMS Loan Repayment Received"):
        frappe.get_doc(
            {
                "doctype": "Notification",
                "name": "LMS Loan Repayment Received",
                "subject": "Payment received for {{ doc.against_loan }}",
                "document_type": "Loan Repayment",
                "event": "Submit",
                "channel": "Email",
                "enabled": 0,
                "message": "<p>Disabled — LMS sends branded email via lms_saas.api.crm.</p>",
            }
        ).insert(ignore_permissions=True)


def _setup_portal_menu():
    from lms_saas.utils.portal import prune_customer_portal_menu

    prune_customer_portal_menu()


def _ensure_customer_portal_role():
    if not frappe.db.exists("Role", "Customer"):
        return
    for dt in ("Loan", "Loan Application", "Loan Repayment"):
        if frappe.db.exists("Custom DocPerm", {"role": "Customer", "parent": dt}):
            continue
        frappe.get_doc(
            {
                "doctype": "Custom DocPerm",
                "parent": dt,
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": "Customer",
                "read": 1,
                "write": 0,
                "create": 0,
                "delete": 0,
                "submit": 0,
                "cancel": 0,
            }
        ).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Desk lockdown + branding (upgrade-safe: only our own / config records)
# ---------------------------------------------------------------------------
def _all_module_names():
    from frappe.utils.modules import get_modules_from_all_apps

    return sorted({m.get("module_name") for m in get_modules_from_all_apps() if m.get("module_name")})


def _blocked_modules():
    return [m for m in _all_module_names() if m not in ALLOWED_MODULES]


def _clear_doc_lock(doc):
    from frappe.utils import file_lock

    try:
        file_lock.delete_lock(doc.get_signature())
    except Exception:
        pass


def _setup_module_lockdown():
    """Hide non-LMS sidebar workspaces from LMS staff via a Module Profile we own.

    Blocking a module only affects the desk sidebar / module pages
    (frappe/desk/desktop.py); it is never consulted by frappe/permissions.py, so
    Loan/Customer lists still open from the Loan Management shortcuts. No ERPNext
    workspace records are edited, so upgrades + migrate stay clean.
    """
    blocked = _blocked_modules()
    if not blocked:
        return

    if frappe.db.exists("Module Profile", MODULE_PROFILE_NAME):
        profile = frappe.get_doc("Module Profile", MODULE_PROFILE_NAME)
    else:
        profile = frappe.new_doc("Module Profile")
        profile.module_profile_name = MODULE_PROFILE_NAME

    profile.block_modules = []
    for module in blocked:
        profile.append("block_modules", {"module": module})
    profile.flags.ignore_permissions = True
    _clear_doc_lock(profile)
    profile.save(ignore_permissions=True)

    for user in _lms_staff_users():
        apply_lms_module_profile_to_user(user)


def _lms_staff_users():
    """Users holding an LMS role but not System Manager (admins keep full access)."""
    candidates = set()
    for role in ALL_LMS_ROLES:
        candidates.update(
            frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
        )
    staff = []
    for user in candidates:
        if user in ("Administrator", "Guest"):
            continue
        if SYS_ROLE in set(frappe.get_roles(user)):
            continue
        staff.append(user)
    return staff


def apply_lms_module_profile_to_user(user):
    """Assign the LMS Staff module profile; core validate copies block_modules."""
    if not frappe.db.exists("Module Profile", MODULE_PROFILE_NAME):
        return
    doc = frappe.get_doc("User", user)
    if doc.module_profile == MODULE_PROFILE_NAME:
        return
    doc.module_profile = MODULE_PROFILE_NAME
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)


def _setup_navbar_branding():
    """Set the desk/login brand logo + app name and trim unneeded navbar items.

    Navbar Settings and Website Settings are config Singles intended for
    customization, so this is upgrade-safe.
    """
    from lms_saas.utils.brand import BRAND_FAVICON_PATH, BRAND_LOGO_PATH, DEFAULT_BRAND

    logo = BRAND_LOGO_PATH
    favicon = BRAND_FAVICON_PATH
    brand_name = frappe.conf.get("lms_brand_portal_title") or DEFAULT_BRAND["portal_title"]

    if frappe.db.exists("DocType", "Navbar Settings"):
        navbar = frappe.get_single("Navbar Settings")
        navbar.app_logo = logo
        _hide_navbar_items(navbar)
        from lms_saas.utils.help import sync_navbar_help_dropdown

        sync_navbar_help_dropdown(navbar)
        navbar.flags.ignore_permissions = True
        navbar.save(ignore_permissions=True)

    try:
        website = frappe.get_single("Website Settings")
        website.app_logo = logo
        website.favicon = favicon
        if frappe.get_meta("Website Settings").has_field("splash_image"):
            website.splash_image = favicon
        website.app_name = brand_name
        website.brand_html = f'<span style="font-weight:600">{brand_name}</span>'
        website.flags.ignore_permissions = True
        website.save(ignore_permissions=True)
    except Exception:
        frappe.log_error(title="LMS branding (Website Settings)", message=frappe.get_traceback())

    try:
        frappe.db.set_single_value("System Settings", "app_name", brand_name)
    except Exception:
        pass


# Navbar dropdown items LMS staff do not need (framework chrome).
_HIDE_NAVBAR_LABELS = {
    "About",
    "Keyboard Shortcuts",
    "Frappe Support",
    "Documentation",
    "Report an Issue",
    "Toggle Theme",
    "Apps",
    "Session Defaults",
    "Toggle Full Width",
    "View Website",
}


def _hide_navbar_items(navbar):
    for fieldname in ("help_dropdown", "settings_dropdown"):
        for row in navbar.get(fieldname) or []:
            if row.item_label in _HIDE_NAVBAR_LABELS:
                row.hidden = 1


def apply_lms_module_profile(doc, method=None):
    """before_validate hook: route LMS staff onto the LMS Staff module profile.

    Setting `module_profile` lets core `validate_allowed_modules` copy block_modules
    in the same save (no extra write, no recursion). Admins/System Managers and
    users with an explicit profile are left untouched.
    """
    if doc.name in ("Administrator", "Guest"):
        return
    if doc.get("module_profile"):
        return
    roles = {r.role for r in (doc.get("roles") or [])}
    if SYS_ROLE in roles or not roles.intersection(set(ALL_LMS_ROLES)):
        return
    if not frappe.db.exists("Module Profile", MODULE_PROFILE_NAME):
        return
    doc.module_profile = MODULE_PROFILE_NAME
