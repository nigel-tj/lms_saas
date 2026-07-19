import json
import os
import shutil

import frappe
from frappe import _

LMS_LEGACY_LANDING_WORKSPACE = "Loan Management"
# Superseded workspaces retired on migrate (our own records, safe to delete).
LEGACY_WORKSPACES = (
    "LMS Operations",
    "Applications",
    "CRM & Prospects",
    "Loans & Disbursements",
    "Collections",
    "Borrowers & Collateral",
)
MODULE_NAME = "Lms Saas"
LENDING_MODULE = "Loan Management"
LOAN_DASHBOARD_NAME = "Loan Dashboard"
CHART_SOURCE_NAME = "LMS Portfolio"

# The desk is admin-only: Administrator / System Manager manage and monitor the
# app. Staff (loan officers, collectors) interact through the portal/PWA, not
# the desk. A single portal-only role gates those staff views.
SYS_ROLE = "System Manager"
PORTAL_STAFF_ROLE = "LMS Portal Staff"
# Workspaces are visible to System Manager (Administrator inherits all perms).
ADMIN_ROLES = (SYS_ROLE,)
CRM_MODULE = "CRM"

# Persona → roles/records mapping for the LMS User Setup onboarding form.
# Borrowers get the Customer role and land on the portal.
# Admins get System Manager and use the desk.
# Loan Officers / Collectors get the portal-only LMS Portal Staff role and an
# Employee record (for branch resolution); they use /lms/collect and related
# portal APIs, not the desk.
PERSONA_CONFIG = {
    "Borrower": {
        "roles": ["Customer"],
        "create_customer": True,
        "create_employee": False,
        "desk": False,
        "landing_workspace": None,  # portal users land on /lms, not the desk
    },
    "Admin": {
        "roles": ["System Manager", "Desk User"],
        "create_customer": False,
        "create_employee": False,
        "desk": True,
        "landing_workspace": "Loan Management",  # full portfolio overview
    },
    "Loan Officer": {
        "roles": [PORTAL_STAFF_ROLE],
        "create_customer": False,
        "create_employee": True,
        "desk": False,
        "landing_workspace": None,  # portal-only staff
    },
    "Collector": {
        "roles": [PORTAL_STAFF_ROLE],
        "create_customer": False,
        "create_employee": True,
        "desk": False,
        "landing_workspace": None,  # portal-only staff
    },
    "Branch Manager": {
        "roles": [PORTAL_STAFF_ROLE],
        "create_customer": False,
        "create_employee": True,
        "desk": False,
        "landing_workspace": None,  # portal-only staff
    },
}

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
# Sidebar navigation tree (single source of truth) — admin-only.
#
# The desk is for Administrators / System Managers to manage and monitor the
# loan app and app operations. Four workspaces cover the full surface area:
#
#   1. Loan Management  — portfolio overview, KPIs, loans, applications,
#                         disbursements, repayments, borrowers, collateral,
#                         credit policy (the admin landing page).
#   2. Reports          — portfolio, arrears, provisions, collections reports.
#   3. Compliance & Risk — audit trail, incidents, notifications, IFRS9 ECL.
#   4. Investors        — investor book, transactions, payments, integrations,
#                         group lending, user setup, webhooks, API keys.
#
# Each entry is one Desk Workspace (module "Lms Saas"). The after_migrate hook
# re-applies this spec idempotently. Nothing here touches frappe/erpnext/lending.
#
# Shortcut row keys: label, type (DocType|Report|URL), link_to, doc_view, color, url.
# Card group keys:   label, links[] where each link is (label, link_to, link_type, is_query_report).
# ---------------------------------------------------------------------------
LMS_NAV_SPEC = (
    {
        "key": "loan_management",
        "title": LMS_LEGACY_LANDING_WORKSPACE,
        "parent": None,
        "roles": ADMIN_ROLES,
        "icon": "loan",
        "sequence_id": 1,
        "hidden": False,
        "landing": True,
        "greeting": "Monitor and manage the loan portfolio, applications, and disbursements.",
        "shortcut_heading": "Quick actions",
        "shortcuts": [
            {"label": "Active Loans", "type": "DocType", "link_to": "Loan", "doc_view": "List", "color": "Blue"},
            {"label": "Loan Applications", "type": "DocType", "link_to": "Loan Application", "doc_view": "List", "color": "Cyan"},
            {"label": "Disbursements", "type": "DocType", "link_to": "Loan Disbursement", "doc_view": "List", "color": "Green"},
            {"label": "Repayments", "type": "DocType", "link_to": "Loan Repayment", "doc_view": "List", "color": "Orange"},
            {"label": "Loan Dashboard", "type": "URL", "url": "/app/dashboard-view/Loan Dashboard", "color": "Purple"},
        ],
        "cards": [],  # populated dynamically by _resolve_workspace_spec
        "number_cards": [c["name"] for c in NUMBER_CARDS],
        "charts": [c["name"] for c in DASHBOARD_CHARTS],
    },
    {
        "key": "reports",
        "title": "Reports",
        "parent": "",
        "roles": ADMIN_ROLES,
        "icon": "file",
        "sequence_id": 2,
        "greeting": "Portfolio performance, arrears, provisions, and management reporting.",
        "shortcut_heading": "Reports",
        "shortcuts": [
            {"label": "Portfolio At Risk", "type": "Report", "link_to": "Portfolio At Risk", "color": "Red"},
            {"label": "Arrears Aging", "type": "Report", "link_to": "Arrears Aging", "color": "Orange"},
            {"label": "Loan Outstanding", "type": "Report", "link_to": "Loan Outstanding Report", "color": "Blue"},
            {"label": "Loan Repayment & Closure", "type": "Report", "link_to": "Loan Repayment and Closure", "color": "Green"},
            {"label": "Loan Dashboard", "type": "URL", "url": "/app/dashboard-view/Loan Dashboard", "color": "Purple"},
        ],
        "cards": [],  # populated dynamically by _resolve_workspace_spec
    },
    {
        "key": "compliance_risk",
        "title": "Compliance & Risk",
        "parent": "",
        "roles": ADMIN_ROLES,
        "icon": "review",
        "sequence_id": 3,
        "greeting": "Credit provisions, operational incidents, and audit trail.",
        "shortcut_heading": "Compliance & risk",
        "shortcuts": [
            {"label": "IFRS9 ECL Provision", "type": "Report", "link_to": "IFRS9 ECL Provision", "color": "Red"},
            {"label": "Incident & Risk Register", "type": "DocType", "link_to": "LMS Incident Log", "doc_view": "List", "color": "Orange"},
            {"label": "Audit Trail", "type": "DocType", "link_to": "LMS Audit Event", "doc_view": "List", "color": "Grey"},
            {"label": "Notification Log", "type": "DocType", "link_to": "LMS Notification Log", "doc_view": "List", "color": "Cyan"},
            {"label": "Weekly Sandbox KPI", "type": "Report", "link_to": "LMS Sandbox Weekly KPI", "color": "Blue"},
        ],
        "cards": [],  # populated dynamically by _resolve_workspace_spec
    },
    {
        "key": "investors",
        "title": "Investors",
        "parent": "",
        "roles": ADMIN_ROLES,
        "icon": "organization",
        "sequence_id": 4,
        "greeting": "Investor register, capital movements, payments, integrations, and app operations.",
        "shortcut_heading": "Investors",
        "shortcuts": [
            {"label": "Investor Book", "type": "DocType", "link_to": "LMS Investor", "doc_view": "List", "color": "Blue"},
            {"label": "Investor Transactions", "type": "DocType", "link_to": "LMS Investor Transaction", "doc_view": "List", "color": "Cyan"},
        ],
        "cards": [],  # populated dynamically by _resolve_workspace_spec
    },
    {
        "key": "addons",
        "title": "Addons",
        "parent": "",
        "roles": ADMIN_ROLES,
        "icon": "extension",
        "sequence_id": 5,
        "greeting": "Toggle portal addons on or off. Enabled addons appear in the portal sidebar for users with the matching persona.",
        "shortcut_heading": "Addons",
        "shortcuts": [
            {"label": "Addon Settings", "type": "DocType", "link_to": "LMS Addon Settings", "color": "Blue"},
            {"label": "Announcements", "type": "DocType", "link_to": "LMS Announcement", "doc_view": "List", "color": "Cyan"},
            {"label": "Tasks", "type": "URL", "url": "/app/task", "color": "Green"},
            {"label": "Document Categories", "type": "DocType", "link_to": "LMS Document Category", "doc_view": "List", "color": "Orange"},
            {"label": "Issues (Tickets)", "type": "URL", "url": "/app/issue", "color": "Red"},
        ],
        "cards": [],
    },
)


def after_install():
    _ensure_loan_agreement_template()
    _seed_branches()
    _seed_loan_product()
    _sync_loan_product_accounts()
    _ensure_lending_permissions()
    _ensure_lms_report_support_permissions()
    _sync_lms_report_roles()
    _sync_dashboard_chart_source()
    _sync_number_cards()
    _sync_dashboard_charts()
    _sync_loan_dashboard_extensions()
    _sync_lms_workspaces()
    _setup_navbar_branding()
    _seed_print_formats()
    _sync_print_formats()
    _ensure_crm_permissions()
    _seed_dev_email_account()
    _seed_branded_emails()
    _setup_portal_menu()
    _ensure_customer_portal_role()
    _ensure_portal_staff_role()
    _seed_payment_providers()
    _retire_legacy_roles_and_profile()
    _set_admin_home_page()
    _seed_addon_settings()


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
    """Reports link to branches (Cost Center) and company filters — admin needs read."""
    read_only = {"read": 1}
    for role in (SYS_ROLE,):
        for doctype in ("Cost Center", "Company"):
            _ensure_role_perm(role, doctype, read_only)


def _sync_lms_report_roles():
    """Ensure LMS and lending script reports are runnable by System Manager."""
    for report_name in DESK_REPORT_NAMES:
        if not frappe.db.exists("Report", report_name):
            continue
        for role in ADMIN_ROLES:
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
    """CRM analytics reports are runnable by System Manager (admin-only desk)."""
    for report_name in CRM_REPORT_NAMES:
        if not frappe.db.exists("Report", report_name):
            continue
        for role in ADMIN_ROLES:
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


def _doctype_link_tuple(doctype_name):
    """Build a (label, link_to, link_type, is_query_report) tuple if doctype exists."""
    if not frappe.db.exists("DocType", doctype_name):
        return None
    return (doctype_name, doctype_name, "DocType", 0)


def _existing_doctype_links(doctype_names):
    """Filter a list of doctype names to existing-doctype link tuples."""
    links = []
    for name in doctype_names:
        tup = _doctype_link_tuple(name)
        if tup:
            links.append(tup)
    return links


def _loan_management_cards():
    """Card groups for the Loan Management admin landing workspace."""
    groups = (
        ("Borrowers", ("Customer", "LMS Borrower Compliance")),
        ("Collateral", ("LMS Collateral", "LMS Loan Collateral")),
        ("Credit Policy", ("LMS Credit Policy", "LMS Credit Rule")),
        ("CRM", ("Lead", "Opportunity", "Communication")),
    )
    cards = []
    for card_label, doctype_names in groups:
        links = _existing_doctype_links(doctype_names)
        if links:
            cards.append({"label": card_label, "links": links})
    return cards


def _compliance_risk_cards():
    """Card groups for the Compliance & Risk workspace."""
    groups = (
        ("Compliance Queue", ("LMS Borrower Compliance", "LMS Collateral")),
        ("Audit & Logs", ("LMS Audit Event", "LMS Incident Log", "LMS Notification Log")),
    )
    cards = []
    for card_label, doctype_names in groups:
        links = _existing_doctype_links(doctype_names)
        if links:
            cards.append({"label": card_label, "links": links})
    return cards


def _investors_cards():
    """Card groups for the Investors workspace (app operations hub)."""
    groups = (
        ("App Operations", ("LMS Payment Provider", "LMS Payment Reconciliation", "LMS Payment Intent")),
        ("Integrations", ("LMS API Key", "LMS Webhook Subscription")),
        ("Group Lending", ("LMS Lending Group", "LMS Center", "LMS Group Meeting", "LMS Savings Account", "LMS Savings Transaction")),
        ("Administration", ("LMS User Setup", "LMS Credit Policy")),
    )
    cards = []
    for card_label, doctype_names in groups:
        links = _existing_doctype_links(doctype_names)
        if links:
            cards.append({"label": card_label, "links": links})
    return cards


def _resolve_workspace_spec(spec):
    """Expand dynamic workspace fragments (report/doctype card menus)."""
    key = spec.get("key")
    if key == "reports":
        return {**spec, "cards": _reports_workspace_cards()}
    if key == "loan_management":
        return {**spec, "cards": _loan_management_cards()}
    if key == "compliance_risk":
        return {**spec, "cards": _compliance_risk_cards()}
    if key == "investors":
        return {**spec, "cards": _investors_cards()}
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


def _retire_legacy_roles_and_profile():
    """Remove superseded LMS staff roles and the LMS Staff module profile.

    The desk is now admin-only (System Manager / Administrator). These artifacts
    from the previous multi-role design are cleaned up so verify_spec passes and
    no stale permissions linger. Users who held these roles keep their System
    Manager access (or should be reassigned manually on the live site).

    Phase 4.4: also strips ``Has Role`` rows for the legacy role names from
    every User (and from Reports, though the patch in patches/v15_1/ handles
    the exhaustive one-time migration).
    """
    legacy_roles = ("LMS Admin", "LMS Branch Manager", "LMS Loan Officer", "LMS Collector")
    for role in legacy_roles:
        if frappe.db.exists("Role", role):
            # Remove Custom DocPerm rows for this role before deleting the role.
            frappe.db.delete("Custom DocPerm", {"role": role})
            # Strip Has Role child rows on User so the user.roles virtual field
            # no longer reports the legacy name.
            for hr_name in frappe.get_all(
                "Has Role", filters={"role": role, "parenttype": "User"}, pluck="name"
            ):
                frappe.delete_doc("Has Role", hr_name, ignore_permissions=True, force=True)
            # Also strip Has Role rows on Report.
            for hr_name in frappe.get_all(
                "Has Role", filters={"role": role, "parenttype": "Report"}, pluck="name"
            ):
                frappe.delete_doc("Has Role", hr_name, ignore_permissions=True, force=True)

def _set_admin_home_page():
    """Set System Manager / Administrator Role.home_page to the Loan Management workspace.

    Without this, Frappe's get_home_page() falls through to Portal Settings
    default_portal_home (/lms) and sends the admin to the borrower portal.
    Role.home_page is checked before the portal default.
    """
    from frappe.desk.utils import slug
    from lms_saas.utils.frappe_version import desk_prefix

    admin_home = f"{desk_prefix()}/{slug(LMS_LEGACY_LANDING_WORKSPACE)}"
    for role_name in ("System Manager", "Administrator"):
        if frappe.db.exists("Role", role_name):
            frappe.db.set_value("Role", role_name, "home_page", admin_home)


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
        if sc.get("type") == "DocType" and not frappe.db.exists("DocType", sc.get("link_to")):
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
    for card_name in spec.get("number_cards", ()):  # KPI widgets (loan_management landing)
        if frappe.db.exists("Number Card", card_name):
            ws.append("number_cards", {"number_card_name": card_name, "label": card_name})

    ws.charts = []
    for chart_name in spec.get("charts", ()):  # dashboard charts (loan_management landing)
        if frappe.db.exists("Dashboard Chart", chart_name):
            ws.append("charts", {"chart_name": chart_name, "label": chart_name})

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

    # Embed KPI number cards and dashboard charts directly in the workspace
    # (loan_management landing page) so the admin sees live metrics immediately.
    number_cards = spec.get("number_cards") or []
    if number_cards:
        blocks.append(
            {"id": f"{key}_hdr_nc", "type": "header", "data": {"text": '<span class="h5"><b>Portfolio KPIs</b></span>', "col": 12}}
        )
        for i, nc_name in enumerate(number_cards):
            blocks.append({"id": f"{key}_nc_{i}", "type": "number_card", "data": {"number_card_name": nc_name, "col": 2}})

    charts = spec.get("charts") or []
    if charts:
        blocks.append(
            {"id": f"{key}_hdr_ch", "type": "header", "data": {"text": '<span class="h5"><b>Portfolio Charts</b></span>', "col": 12}}
        )
        for i, chart_name in enumerate(charts):
            col = 6 if i < 2 else 12  # first two charts side-by-side, third full-width
            blocks.append({"id": f"{key}_ch_{i}", "type": "chart", "data": {"chart_name": chart_name, "col": col}})

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
    """CRM + desk email permissions for admin (System Manager / Administrator).

    The desk is admin-only, so System Manager gets full CRM + email access to
    manage leads, opportunities, and configure SMTP/email templates.
    """
    crm_rw = _crm_rw_perm()
    crm_delete = {**crm_rw, "delete": 1}
    master_read = _crm_read_only_perm()
    email_admin = {"read": 1, "write": 1, "create": 1, "delete": 1, "email": 0}

    for role in ADMIN_ROLES + ("Administrator",):
        for dt in _crm_core_doctypes():
            _ensure_role_perm(role, dt, crm_delete)
        for dt in _crm_email_support_doctypes():
            _ensure_role_perm(role, dt, email_admin)
        for dt in _crm_master_read_doctypes():
            _ensure_role_perm(role, dt, master_read)
        _ensure_role_perm(role, "Address", _crm_address_perm())
        _ensure_role_perm(role, "Customer", {"email": 1})
        _ensure_role_perm(role, "Print Format", {"read": 1, "write": 0, "create": 0, "delete": 0})

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


def _ensure_portal_staff_role():
    """Create the portal-only LMS staff role (no desk access)."""
    if not frappe.db.exists("Role", PORTAL_STAFF_ROLE):
        frappe.get_doc(
            {"doctype": "Role", "role_name": PORTAL_STAFF_ROLE, "desk_access": 0}
        ).insert(ignore_permissions=True)
    else:
        frappe.db.set_value("Role", PORTAL_STAFF_ROLE, "desk_access", 0)


# ---------------------------------------------------------------------------
# Desk branding (upgrade-safe: only our own / config records)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Addon settings — seed the LMS Addon Settings singleton with all registered
# addons. Admins then toggle addons on/off via the desk page.
# ---------------------------------------------------------------------------

def _seed_addon_settings():
    """Populate the LMS Addon Settings single with rows for every registered addon."""
    from lms_saas.utils.addons import ADDON_REGISTRY

    if not frappe.db.exists("DocType", "LMS Addon Settings"):
        return

    # Force the DocType record to match the JSON's issingle flag. Older sites
    # installed from a JSON that used the wrong key (``is_single`` instead of
    # ``issingle``), so the DocType was created as a normal table-backed type
    # and frappe.get_single() raises DoesNotExistError. Reload from JSON fixes
    # the record; this is idempotent and cheap.
    meta = frappe.get_meta("LMS Addon Settings")
    if not meta.issingle:
        from frappe.modules.import_file import import_file_by_path

        path = frappe.get_app_path("lms_saas") + (
            "/lms_saas/doctype/lms_addon_settings/lms_addon_settings.json"
        )
        import_file_by_path(path, force=True, ignore_version=True)
        frappe.db.commit()
        frappe.clear_cache(doctype="LMS Addon Settings")

        # Drop the stale table-backed copy created when the DocType was
        # wrongly treated as a normal (non-single) type. It only ever held
        # the standard Frappe meta columns (no real field data, since the
        # JSON fields were never synced into it), so it is safe to remove.
        # Single DocTypes store their values in tabSingles instead.
        table_name = "tabLMS Addon Settings"
        if frappe.db.sql("SHOW TABLES LIKE %s", table_name):
            frappe.db.sql_ddl("DROP TABLE IF EXISTS `%s`" % table_name)
            frappe.db.commit()

    doc = frappe.get_single("LMS Addon Settings")
    existing_keys = {row.addon_key for row in (doc.addons or [])}
    if existing_keys == set(ADDON_REGISTRY.keys()):
        return  # already fully populated

    for key, spec in ADDON_REGISTRY.items():
        if key in existing_keys:
            continue
        doc.append(
            "addons",
            {
                "addon_key": key,
                "addon_label": str(spec.get("label", key)),
                "description": str(spec.get("description", "")),
                "enabled": 0,
            },
        )
    doc.flags.ignore_permissions = True
    doc.save()
    frappe.db.commit()
