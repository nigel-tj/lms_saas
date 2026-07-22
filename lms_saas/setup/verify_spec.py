"""Bench verification: bench --site lms.localhost execute lms_saas.setup.verify_spec.run_all_checks"""


def run_checks():
    return run_all_checks()


def run_all_checks():
    import frappe

    results = {"ok": True, "checks": {}}

    def check(name, fn):
        try:
            results["checks"][name] = fn()
            if isinstance(results["checks"][name], dict) and results["checks"][name].get("ok") is False:
                results["ok"] = False
        except Exception as e:
            results["ok"] = False
            results["checks"][name] = {"ok": False, "error": str(e)}

    check("apps", _check_apps)
    check("custom_fields", _check_custom_fields)
    check("reports", _check_reports)
    check("roles", _check_roles)
    check("workspace", _check_workspace)
    check("loan_dashboard", _check_loan_dashboard)
    check("dashboard_api", _check_dashboard_api)
    check("admin_console", _check_admin_console)
    check("print_formats", _check_print_formats)
    check("notifications", _check_notifications)
    check("crm", _check_crm)
    check("portal_api", _check_portal_api)
    check("investor_gl", _check_investor_gl)
    check("loan_product", _check_loan_product)
    check("branches", _check_branches)
    check("demo_loan", _check_demo_loan)
    check("scheduler", _check_scheduler)
    check("workflow_automation", _check_workflow_automation)
    check("lending_jobs", _check_lending_jobs)
    check("credit_bureau_config", _check_credit_bureau_config)
    check("compliance", _check_compliance)
    check("collateral", _check_collateral)
    check("role_screen_access", _check_role_screen_access)
    check("aml", _check_aml)
    check("payments", _check_payments)
    check("portal_self_service", _check_portal_self_service)
    check("integrations", _check_integrations)
    check("decisioning", _check_decisioning)
    check("webhooks", _check_webhooks)
    check("field_collection", _check_field_collection)
    check("group_lending", _check_group_lending)
    check("savings", _check_savings)
    check("addons", _check_addons)

    return results


def _check_addons():
    """Verify the addon registry, settings doctype, and core addon modules."""
    import frappe
    from lms_saas.utils.addons import ADDON_REGISTRY
    from lms_saas.utils.portal import ADDON_PAGE_JS

    # 1. Registry must have entries
    if not ADDON_REGISTRY:
        return {"ok": False, "error": "ADDON_REGISTRY is empty"}

    # 2. LMS Addon Settings doctype + singleton
    if not frappe.db.exists("DocType", "LMS Addon Settings"):
        return {"ok": False, "error": "LMS Addon Settings DocType not found"}

    settings = frappe.get_single("LMS Addon Settings")
    if not (settings.addons or []):
        return {"ok": False, "error": "LMS Addon Settings has no rows — run after_install"}

    # 3. Verify each registered addon has its API module.
    #    Registry key → API module short name. Both share the same
    #    "business" name, but the filename is often shortened
    #    (e.g. "task_management" → "tasks").
    #    SSoT: ADDON_API_MODULE — keep in sync with the API directory.
    import os
    api_dir = os.path.join(os.path.dirname(__file__), "..", "api")
    ADDON_API_MODULE = {
        "announcements":     "announcements",
        "task_management":   "tasks",
        "document_center":   "documents_center",  # also has documents.py
        "helpdesk":          "helpdesk",
        "hr_management":     "hr",
        "branch_analytics":  "branch_analytics",
        "regulatory_hub":    "regulatory_hub",
        "payroll":           "payroll",
        "appraisals":        "appraisals",
        "training":          "training",
        "recruitment":       "recruitment",
        "procurement":       "procurement",
        "savings_club":      "savings_club",
        "customer_feedback": "feedback",
        "field_visits":      "field_visits",
        "inventory":         "inventory",
        "budgeting":         "budgeting",
        "insurance":         "insurance",
        "whatsapp":          "whatsapp",
        "wallet_recon":      "wallet_recon",
    }
    missing_modules = []
    for key, spec in ADDON_REGISTRY.items():
        module_short = ADDON_API_MODULE.get(key)
        if not module_short:
            missing_modules.append(f"(no API module mapping for {key!r})")
            continue
        module_path = os.path.join(api_dir, f"{module_short}.py")
        if not os.path.exists(module_path):
            missing_modules.append(f"lms_saas.api.{module_short}")

    # 4. Verify portal pages exist for each addon
    missing_pages = []
    www_dir = os.path.join(os.path.dirname(__file__), "..", "www", "lms")
    for key, spec in ADDON_REGISTRY.items():
        route = spec.get("route", "").lstrip("/").replace("lms/", "")
        page = os.path.join(www_dir, route + ".py")
        if not os.path.exists(page):
            missing_pages.append(route + ".py")

    # 5. Verify portal JS files exist (SSoT: ADDON_PAGE_JS in utils/portal.py)
    missing_js = []
    public_dir = os.path.join(os.path.dirname(__file__), "..", "public", "js")
    for key in ADDON_REGISTRY.keys():
        js_rel = ADDON_PAGE_JS.get(key)  # e.g. "js/lms_tasks_portal.js"
        if not js_rel:
            missing_js.append(f"(no ADDON_PAGE_JS entry for {key!r})")
            continue
        js_basename = os.path.basename(js_rel)  # e.g. "lms_tasks_portal.js"
        js_path = os.path.join(public_dir, js_basename)
        if not os.path.exists(js_path):
            missing_js.append(js_basename)

    result = {
        "ok": not (missing_modules or missing_pages or missing_js),
        "registered_addons": len(ADDON_REGISTRY),
        "settings_rows": len(settings.addons or []),
        "missing_modules": missing_modules,
        "missing_pages": missing_pages,
        "missing_js": missing_js,
    }
    if missing_modules or missing_pages or missing_js:
        result["error"] = (
            f"{len(missing_modules)} missing API modules, "
            f"{len(missing_pages)} missing portal pages, "
            f"{len(missing_js)} missing portal JS files"
        )
    return result


def _check_aml():
    """AML/CFT screening module and compliance fields."""
    import frappe

    from lms_saas.api import aml

    has_fields = all(
        frappe.db.has_column("LMS Borrower Compliance", f)
        for f in ("aml_status", "aml_screened_at", "aml_provider_ref")
    )
    has_api = all(
        hasattr(aml, fn)
        for fn in ("screen_borrower_compliance", "enforce_aml_on_origination", "_aml_config")
    )
    return {"ok": has_fields and has_api, "aml_fields": has_fields, "aml_api": has_api}


def _check_payments():
    """Payment intents, providers, adapters."""
    import frappe

    from lms_saas.api import payments

    doctypes = ["LMS Payment Provider", "LMS Payment Intent", "LMS Payment Reconciliation"]
    missing = [d for d in doctypes if not frappe.db.exists("DocType", d)]
    has_service = hasattr(payments, "create_payment_intent")
    return {"ok": not missing and has_service, "missing_doctypes": missing, "payments_api": has_service}


def _check_portal_self_service():
    from lms_saas.api import portal

    fns = ("submit_loan_application", "upload_kyc_document", "initiate_repayment", "get_apply_context")
    return {"ok": all(hasattr(portal, fn) for fn in fns), "required": fns}


def _check_integrations():
    import frappe

    has_key_dt = frappe.db.exists("DocType", "LMS API Key")
    modules = ["bureau", "sms", "payments", "aml"]
    ok = bool(has_key_dt)
    for mod in modules:
        try:
            __import__(f"lms_saas.api.integrations.{mod}")
        except Exception:
            ok = False
    return {"ok": ok, "api_key_doctype": bool(has_key_dt), "modules": modules}


def _check_decisioning():
    import frappe

    from lms_saas.api import decisioning

    has_policy = frappe.db.exists("DocType", "LMS Credit Policy")
    has_engine = hasattr(decisioning, "evaluate_credit_policy")
    return {"ok": bool(has_policy and has_engine), "credit_policy": bool(has_policy), "engine": has_engine}


def _check_webhooks():
    import frappe

    from lms_saas.api import webhooks

    has_dt = frappe.db.exists("DocType", "LMS Webhook Subscription")
    has_dispatch = hasattr(webhooks, "dispatch_webhook_event")
    return {"ok": bool(has_dt and has_dispatch), "subscription_doctype": bool(has_dt)}


def _check_field_collection():
    from lms_saas.api import field_collection

    fns = ("get_collection_run_sheet", "record_field_repayment", "sync_offline_batch")
    return {"ok": all(hasattr(field_collection, fn) for fn in fns), "required": fns}


def _check_group_lending():
    import frappe

    doctypes = ["LMS Lending Group", "LMS Group Member", "LMS Group Meeting", "LMS Center"]
    missing = [d for d in doctypes if not frappe.db.exists("DocType", d)]
    has_field = frappe.db.exists("Custom Field", "Loan Application-custom_lending_group")
    return {"ok": not missing and bool(has_field), "missing": missing, "loan_app_field": bool(has_field)}


def _check_savings():
    import frappe

    doctypes = ["LMS Savings Account", "LMS Savings Transaction"]
    missing = [d for d in doctypes if not frappe.db.exists("DocType", d)]
    return {"ok": not missing, "missing": missing}


def _check_role_screen_access():
    from lms_saas.setup.verify_access import run_all

    return run_all()


def _check_collateral():
    """Collateral register: doctypes, loan link fields, and coverage API."""
    import frappe

    from lms_saas.api import collateral

    doctypes = ["LMS Collateral", "LMS Loan Collateral"]
    missing_dt = [d for d in doctypes if not frappe.db.exists("DocType", d)]
    link_fields = frappe.get_all(
        "Custom Field",
        filters={"fieldname": "custom_collateral", "dt": ("in", ["Loan", "Loan Application"])},
        pluck="dt",
    )
    has_api = all(
        hasattr(collateral, fn)
        for fn in (
            "compute_net_realizable_value",
            "get_collateral_coverage",
            "enforce_collateral_coverage",
            "get_loan_collateral_summary",
        )
    )
    nrv_ok = collateral.compute_net_realizable_value(1000, 20) == 800.0
    return {
        "ok": not missing_dt and len(link_fields) == 2 and has_api and nrv_ok,
        "missing_doctypes": missing_dt,
        "loan_link_fields": link_fields,
        "collateral_api": has_api,
        "nrv_calc_ok": nrv_ok,
    }


def _check_compliance():
    """RBZ sandbox compliance artifacts: doctypes, IFRS9 report, sandbox API."""
    import frappe

    from lms_saas.api import compliance

    doctypes = ["LMS Audit Event", "LMS Incident Log", "LMS Notification Log"]
    missing_dt = [d for d in doctypes if not frappe.db.exists("DocType", d)]
    has_ifrs9 = bool(frappe.db.exists("Report", "IFRS9 ECL Provision"))
    has_consent = frappe.db.has_column("LMS Borrower Compliance", "consent_given")
    has_aml = frappe.db.has_column("LMS Borrower Compliance", "aml_status")
    has_api = all(
        hasattr(compliance, fn)
        for fn in ("write_audit_event", "enforce_four_eyes", "enforce_origination_controls", "get_sandbox_report")
    )
    return {
        "ok": not missing_dt and has_ifrs9 and has_consent and has_aml and has_api,
        "missing_doctypes": missing_dt,
        "ifrs9_report": has_ifrs9,
        "consent_field": has_consent,
        "aml_field": has_aml,
        "compliance_api": has_api,
    }


def _check_scheduler():
    """Loan lifecycle (accrual, classification, reminders) depends on the scheduler."""
    import frappe
    from frappe.utils.scheduler import is_scheduler_disabled

    disabled = is_scheduler_disabled(verbose=False)
    return {
        "ok": not disabled,
        "scheduler_enabled": not disabled,
        "hint": None if not disabled else "Run: bench --site <site> enable-scheduler",
    }


def _check_workflow_automation():
    """Collections/digest/KPI automation modules, notification log, weekly scheduler."""
    import frappe

    from lms_saas import hooks
    from lms_saas.api import collections, digests

    has_notification_log = frappe.db.exists("DocType", "LMS Notification Log") and frappe.db.table_exists(
        "LMS Notification Log"
    )
    has_weekly_report = frappe.db.exists("Report", "LMS Sandbox Weekly KPI")
    weekly_hook = "lms_saas.tasks.send_weekly_sandbox_kpi_pack" in (hooks.scheduler_events.get("weekly") or [])
    collections_api = all(
        hasattr(collections, fn)
        for fn in ("should_send_notification", "log_notification", "run_collections_escalation")
    )
    digest_api = hasattr(digests, "build_morning_digest_context")
    charts_util = False
    try:
        from lms_saas.utils import charts as charts_mod

        charts_util = all(
            hasattr(charts_mod, fn)
            for fn in ("to_frappe_report_chart", "render_email_bar_chart", "rows_from_risk_buckets")
        )
    except Exception:
        charts_util = False

    return {
        "ok": bool(
            has_notification_log
            and has_weekly_report
            and weekly_hook
            and collections_api
            and digest_api
            and charts_util
        ),
        "notification_log_doctype": bool(has_notification_log),
        "weekly_kpi_report": bool(has_weekly_report),
        "weekly_scheduler_hook": weekly_hook,
        "collections_api": collections_api,
        "digest_api": digest_api,
        "charts_util": charts_util,
    }


def _check_lending_jobs():
    """Native DPD/NPA classification + interest accrual run via lending scheduled jobs."""
    import frappe

    from lms_saas.utils.frappe_version import is_v16_or_later

    classification = (
        "lending.loan_management.doctype.process_loan_classification."
        "process_loan_classification.create_process_loan_classification"
    )
    accrual_v15 = (
        "lending.loan_management.doctype.process_loan_interest_accrual."
        "process_loan_interest_accrual.process_loan_interest_accrual_for_term_loans"
    )
    required = [classification]
    if not is_v16_or_later():
        required.append(accrual_v15)

    found, missing = [], []
    for method in required:
        if frappe.db.exists("Scheduled Job Type", {"method": method}):
            found.append(method.split(".")[-1])
        else:
            missing.append(method.split(".")[-1])

    accrual_ok = True
    if is_v16_or_later():
        accrual_jobs = frappe.get_all(
            "Scheduled Job Type",
            filters={"method": ["like", "%interest%accrual%"]},
            pluck="method",
        )
        accrual_ok = bool(accrual_jobs)
        if accrual_jobs:
            found.extend([m.split(".")[-1] for m in accrual_jobs[:3]])

    return {"ok": not missing and accrual_ok, "found": found, "missing": missing}


def _check_credit_bureau_config():
    """Informational: surface the credit bureau integration posture."""
    import frappe

    enabled = bool(frappe.conf.get("lms_credit_bureau_enabled", False))
    configured = bool(frappe.conf.get("lms_credit_bureau_url"))
    # Always ok: disabled is a valid (non-blocking) production posture.
    return {
        "ok": True,
        "enabled": enabled,
        "url_configured": configured,
        "block_on_error": bool(frappe.conf.get("lms_credit_bureau_block_on_error", False)),
    }


def _check_demo_loan():
    import frappe

    loan = frappe.db.get_value("Loan", {"docstatus": 1, "status": "Disbursed"}, "name")
    schedules = frappe.db.count("Loan Repayment Schedule", {"loan": loan}) if loan else 0
    return {"ok": bool(loan and schedules), "loan": loan, "schedules": schedules}


def _check_apps():
    import frappe

    from lms_saas.utils.frappe_version import get_major_version

    required = ["frappe", "erpnext", "lending", "hrms", "lms_saas"]
    installed = set(frappe.get_installed_apps())
    missing = [a for a in required if a not in installed]
    return {
        "ok": not missing,
        "installed": list(installed),
        "missing": missing,
        "frappe_major": get_major_version(),
    }


def _check_custom_fields():
    import frappe

    fields = frappe.get_all(
        "Custom Field",
        filters={
            "dt": "Loan",
            "fieldname": (
                "in",
                ["custom_days_past_due", "custom_asset_classification", "custom_lms_branch", "custom_loan_officer"],
            ),
        },
        pluck="fieldname",
    )
    return {"ok": len(fields) >= 4, "fields": fields}


def _check_reports():
    import frappe

    from lms_saas.install import LMS_REPORT_NAMES, _reports_workspace_cards

    lms_found = [n for n in LMS_REPORT_NAMES if frappe.db.exists("Report", n)]
    cards = _reports_workspace_cards()
    card_labels = [c["label"] for c in cards]
    return {
        "ok": len(lms_found) == len(LMS_REPORT_NAMES) and len(cards) >= 2,
        "lms_reports": lms_found,
        "workspace_cards": card_labels,
    }


def _check_roles():
    """Desk is admin-only: System Manager role must exist with desk access."""
    import frappe

    ok = bool(frappe.db.exists("Role", "System Manager"))
    desk_access = False
    if ok:
        desk_access = bool(frappe.db.get_value("Role", "System Manager", "desk_access"))
    return {"ok": ok and desk_access, "system_manager": ok, "desk_access": desk_access}


def _check_workspace():
    """Admin-only workspaces: Loan Management, Reports, Compliance & Risk, Investors."""
    import frappe

    from lms_saas.install import LMS_LEGACY_LANDING_WORKSPACE
    from lms_saas.utils.frappe_version import is_v16_or_later

    children = [
        "Reports",
        "Compliance & Risk",
        "Investors",
    ]

    legacy = bool(frappe.db.exists("Workspace", "LMS Operations"))
    # Loan Management should be visible (not hidden) — it's the admin landing.
    landing_visible = True
    if frappe.db.exists("Workspace", LMS_LEGACY_LANDING_WORKSPACE):
        landing_doc = frappe.get_doc("Workspace", LMS_LEGACY_LANDING_WORKSPACE)
        landing_visible = not bool(landing_doc.is_hidden)

    child_status = {}
    for title in children:
        if not frappe.db.exists("Workspace", title):
            child_status[title] = {"exists": False}
            continue
        doc = frappe.get_doc("Workspace", title)
        parent_ok = True if is_v16_or_later() else (doc.parent_page or "") == ""
        child_status[title] = {
            "exists": True,
            "parent_ok": parent_ok,
            "roles": sorted({r.role for r in (doc.roles or [])}),
        }

    all_children_ok = all(
        c.get("exists") and c.get("parent_ok") and c.get("roles") for c in child_status.values()
    )

    # Superseded staff workspaces should be retired.
    retired = [
        ws
        for ws in ("Applications", "Loans & Disbursements", "Collections", "Borrowers & Collateral", "CRM & Prospects")
        if not frappe.db.exists("Workspace", ws)
    ]

    return {
        "ok": bool(landing_visible and all_children_ok and not legacy and len(retired) == 5),
        "landing_visible": landing_visible,
        "children": child_status,
        "legacy_workspace_present": legacy,
        "retired_staff_workspaces": retired,
    }


def _check_loan_dashboard():
    """Native Loan Dashboard includes lending + LMS hybrid widgets."""
    import frappe

    from lms_saas.install import LOAN_DASHBOARD_NAME, NUMBER_CARDS

    if not frappe.db.exists("Dashboard", LOAN_DASHBOARD_NAME):
        return {"ok": False, "error": f"Dashboard {LOAN_DASHBOARD_NAME} missing"}

    doc = frappe.get_doc("Dashboard", LOAN_DASHBOARD_NAME)
    card_names = {row.card for row in doc.cards}
    chart_names = {row.chart for row in doc.charts}
    lms_cards = {c["name"] for c in NUMBER_CARDS}
    missing_cards = sorted(lms_cards - card_names)
    lms_chart_set = {"LMS Risk Composition", "LMS Collections Trend", "LMS Branch Concentration"}
    has_lms_charts = lms_chart_set.issubset(chart_names)
    lending_card_names = {"Active Loans", "Total Disbursed", "Active Loans (LMS)"}
    has_lending_cards = bool(lending_card_names & card_names) or len(card_names) >= 2

    return {
        "ok": not missing_cards and has_lms_charts and has_lending_cards,
        "missing_lms_cards": missing_cards,
        "lms_charts_present": has_lms_charts,
        "lms_charts_linked": sorted(lms_chart_set & chart_names),
        "lending_cards_present": has_lending_cards,
        "card_count": len(card_names),
        "chart_count": len(chart_names),
    }


def _check_print_formats():
    import frappe

    names = ["LMS Loan Statement", "LMS Loan Agreement", "LMS Collection Receipt", "LMS Repayment Schedule"]
    found = [n for n in names if frappe.db.exists("Print Format", n)]
    return {"ok": len(found) == len(names), "found": found}


def _check_notifications():
    import frappe

    templates = [
        "LMS Payment Reminder",
        "LMS Loan Repayment Received",
        "LMS Lead Acknowledgement",
    ]
    found = [n for n in templates if frappe.db.exists("Email Template", n)]
    branded = False
    if frappe.db.exists("Email Template", "LMS Payment Reminder"):
        html = frappe.db.get_value("Email Template", "LMS Payment Reminder", "response") or ""
        branded = "lms-email" in html.lower() or "2f4f46" in html.lower()
    return {
        "ok": len(found) == len(templates) and branded,
        "templates": found,
        "branded_html": branded,
    }


def _check_crm():
    import frappe

    from lms_saas.install import CRM_MODULE

    native_crm = bool(frappe.db.exists("Workspace", "CRM"))
    lead_field = frappe.db.exists("Custom Field", "Lead-custom_consent_given")
    return {
        "ok": bool(native_crm and lead_field),
        "crm_module": CRM_MODULE,
        "native_crm_workspace": native_crm,
        "lead_consent_field": bool(lead_field),
    }


def _check_portal_api():
    import frappe

    from lms_saas.api import portal

    return {
        "ok": all(
            hasattr(portal, m)
            for m in ("get_my_loans", "get_loan_detail", "get_statement_pdf")
        ),
        "route": frappe.db.exists("Portal Menu Item", {"route": "/lms"}),
    }


def _check_dashboard_api():
    import frappe

    from lms_saas.api import dashboard

    required = ("get_desk_dashboard", "get_chart_data", "get_kpi_card")
    fns_ok = all(hasattr(dashboard, fn) for fn in required)
    source_ok = frappe.db.exists("Dashboard Chart Source", "LMS Portfolio")
    charts_ok = all(
        frappe.db.exists("Dashboard Chart", name)
        for name in ("LMS Risk Composition", "LMS Collections Trend", "LMS Branch Concentration")
    )
    cards_ok = all(
        frappe.db.exists("Number Card", name)
        for name in (
            "LMS Portfolio Outstanding",
            "LMS Active Loans",
            "LMS PAR 30+ Outstanding",
            "LMS NPA Count",
        )
    )
    # Phase 2: new admin console endpoints.
    admin_console_endpoints = ("get_kyc_queue", "get_recent_activity", "get_active_branches")
    admin_console_ok = all(hasattr(dashboard, fn) for fn in admin_console_endpoints)
    return {
        "ok": bool(fns_ok and source_ok and charts_ok and cards_ok and admin_console_ok),
        "required": required,
        "source": bool(source_ok),
        "charts": bool(charts_ok),
        "number_cards": bool(cards_ok),
        "admin_console_endpoints": bool(admin_console_ok),
    }


def _check_admin_console():
    """Admin Console (/app/lms-admin) — desk-only dashboard wiring.

    Verifies the desk Page implementation:
    1. The page module (`apps/lms_saas/lms_saas/lms_saas/page/lms_admin/`)
       exists with __init__.py + .json + .py + .js + .css.
    2. The Page DocType row is registered in the DB with
       `name == "lms-admin"`, `standard == "Yes"`, and the System Manager
       role gate.
    3. The Loan Management workspace has the "Admin Console" shortcut
       of `type: Page` linking to `lms-admin`.

    The check does NOT make an HTTP request (which would require a live
    server); it just verifies the static artefacts are wired correctly.
    """
    import os

    import frappe

    from lms_saas.install import LMS_NAV_SPEC

    # ``frappe.get_app_path("lms_saas", "lms_saas")`` already returns
    # the inner module directory that contains ``page/``,
    # ``dashboard_chart_source/``, ``doctype/`` and ``report/``. So
    # the page dir is just ``<that>/page/lms_admin``.
    module_root = frappe.get_app_path("lms_saas", "lms_saas")
    page_dir = os.path.join(module_root, "page", "lms_admin")

    files = {
        "page_init": os.path.join(page_dir, "__init__.py"),
        "page_json": os.path.join(page_dir, "lms_admin.json"),
        "page_py":   os.path.join(page_dir, "lms_admin.py"),
        "page_js":   os.path.join(page_dir, "lms_admin.js"),
        "page_css":  os.path.join(page_dir, "lms_admin.css"),
    }
    present = {k: os.path.exists(v) for k, v in files.items()}

    # The Page DocType row must exist in the DB. We use frappe.get_all
    # (not frappe.db.table_exists) because the latter is cached and can
    # return False even when the table is present and queryable.
    try:
        page_row = frappe.db.get_value(
            "Page",
            "lms-admin",
            ["name", "standard", "title"],
            as_dict=True,
        )
    except Exception:
        page_row = None

    role_ok = False
    if page_row:
        page_doc = frappe.get_doc("Page", "lms-admin")
        role_names = {r.role for r in (page_doc.roles or [])}
        role_ok = "System Manager" in role_names and "Administrator" in role_names

    # The Loan Management workspace must have an "Admin Console" Page
    # shortcut pointing to lms-admin.
    loan_mgmt = next(
        (s for s in LMS_NAV_SPEC if s.get("key") == "loan_management"), None
    )
    has_shortcut = False
    if loan_mgmt:
        for sc in loan_mgmt.get("shortcuts", []):
            if (
                sc.get("label") == "Admin Console"
                and sc.get("type") == "Page"
                and sc.get("link_to") == "lms-admin"
            ):
                has_shortcut = True
                break

    files_ok = all(present.values())
    page_ok = bool(page_row) and page_row.get("standard") == "Yes" and role_ok
    ok = files_ok and page_ok and has_shortcut
    return {
        "ok": ok,
        "files": present,
        "page": {
            "registered": bool(page_row),
            "standard": page_row.get("standard") if page_row else None,
            "title": page_row.get("title") if page_row else None,
            "roles_gated": role_ok,
        },
        "loan_mgmt_shortcut": has_shortcut,
        "hint": (
            None if ok
            else "Ensure lms_saas/lms_saas/lms_saas/page/lms_admin/ files exist, "
                 "the Page DocType row is registered (bench migrate), and the "
                 "Loan Management workspace has the Page shortcut (link_to=lms-admin)."
        ),
    }


def _check_investor_gl():
    result = test_investor_gl()
    if result.get("skipped"):
        return {"ok": True, "skipped": result["skipped"]}
    return {"ok": result.get("balanced"), **result}


def _check_loan_product():
    import frappe

    company = frappe.db.get_single_value("Global Defaults", "default_company")
    name = frappe.db.get_value("Loan Product", {"company": company, "product_code": "LMS-STD"}, "name")
    return {"ok": bool(name), "product": name}


def _check_branches():
    import frappe

    company = frappe.db.get_single_value("Global Defaults", "default_company")
    count = frappe.db.count("Cost Center", {"company": company, "is_group": 0})
    return {"ok": count >= 2, "branch_count": count}


def fix_investor_accounts():
    import frappe

    for inv in frappe.get_all("LMS Investor", pluck="name"):
        frappe.db.set_value(
            "LMS Investor",
            inv,
            "investor_liability_account",
            "Unsecured Loans - LMS",
        )
    frappe.db.commit()
    return "ok"


def test_investor_gl():
    import frappe

    inv = frappe.db.get_value("LMS Investor", {}, "name")
    if not inv:
        return {"skipped": "no investor"}

    existing = frappe.db.get_value(
        "LMS Investor Transaction",
        {"investor": inv, "docstatus": 1, "amount": 100},
        "name",
    )
    if existing:
        je = frappe.db.get_value("LMS Investor Transaction", existing, "reference_journal_entry")
        if je:
            je_doc = frappe.get_doc("Journal Entry", je)
            total_debit = sum(a.debit for a in je_doc.accounts)
            total_credit = sum(a.credit for a in je_doc.accounts)
            return {
                "transaction": existing,
                "journal_entry": je,
                "balanced": total_debit == total_credit,
                "debit": total_debit,
                "credit": total_credit,
            }

    doc = frappe.get_doc(
        {
            "doctype": "LMS Investor Transaction",
            "investor": inv,
            "transaction_type": "Credit",
            "amount": 100,
            "posting_date": frappe.utils.today(),
        }
    )
    doc.insert()
    doc.submit()
    frappe.db.commit()

    je = frappe.get_doc("Journal Entry", doc.reference_journal_entry)
    total_debit = sum(a.debit for a in je.accounts)
    total_credit = sum(a.credit for a in je.accounts)

    return {
        "transaction": doc.name,
        "journal_entry": je.name,
        "balanced": total_debit == total_credit,
        "debit": total_debit,
        "credit": total_credit,
    }
