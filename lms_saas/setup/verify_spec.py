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
    check("desk_lockdown", _check_desk_lockdown)
    check("dashboard_api", _check_dashboard_api)
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

    return results


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
    import frappe

    roles = ["LMS Admin", "LMS Branch Manager", "LMS Loan Officer", "LMS Collector"]
    found = [r for r in roles if frappe.db.exists("Role", r)]
    return {"ok": len(found) == len(roles), "found": found}


def _check_workspace():
    """LMS compliance workspaces (top-level under Lms Saas); legacy landing hidden."""
    import frappe

    from lms_saas.install import LMS_LEGACY_LANDING_WORKSPACE
    from lms_saas.utils.frappe_version import is_v16_or_later

    children = [
        "Applications",
        "Loans & Disbursements",
        "Collections",
        "Borrowers & Collateral",
        "Reports",
        "Compliance & Risk",
        "Investors",
    ]

    legacy = bool(frappe.db.exists("Workspace", "LMS Operations"))
    landing_hidden = True
    if frappe.db.exists("Workspace", LMS_LEGACY_LANDING_WORKSPACE):
        landing_doc = frappe.get_doc("Workspace", LMS_LEGACY_LANDING_WORKSPACE)
        landing_hidden = bool(landing_doc.is_hidden)

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

    return {
        "ok": bool(landing_hidden and all_children_ok and not legacy),
        "legacy_landing_hidden": landing_hidden,
        "children": child_status,
        "legacy_workspace_present": legacy,
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


def _check_desk_lockdown():
    """Module Profile allows Lending + Lms Saas; other modules blocked; logo set."""
    import frappe

    from lms_saas.install import ALLOWED_MODULES, CRM_MODULE, LENDING_MODULE, MODULE_PROFILE_NAME

    profile_ok = bool(frappe.db.exists("Module Profile", MODULE_PROFILE_NAME))
    blocked_count = 0
    allowed_present = False
    if profile_ok:
        profile = frappe.get_doc("Module Profile", MODULE_PROFILE_NAME)
        blocked = {d.module for d in profile.block_modules}
        blocked_count = len(blocked)
        profile_ok = ALLOWED_MODULES.isdisjoint(blocked) and blocked_count > 0
        allowed_present = LENDING_MODULE not in blocked and CRM_MODULE not in blocked

    # At least one LMS staff (non System Manager) should be on the profile.
    staff_on_profile = frappe.db.count("User", {"module_profile": MODULE_PROFILE_NAME})

    logo = None
    if frappe.db.exists("DocType", "Navbar Settings"):
        logo = frappe.db.get_single_value("Navbar Settings", "app_logo")
    logo_ok = bool(logo and "lms" in (logo or "").lower())

    return {
        "ok": bool(profile_ok and logo_ok and allowed_present),
        "module_profile": MODULE_PROFILE_NAME if profile_ok else None,
        "allowed_modules": sorted(ALLOWED_MODULES),
        "lending_module_visible": allowed_present,
        "blocked_modules": blocked_count,
        "staff_on_profile": staff_on_profile,
        "navbar_logo": logo,
    }


def _check_print_formats():
    import frappe

    names = ["LMS Loan Statement", "LMS Loan Agreement"]
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
        branded = "lms-email" in html.lower() or "0f4c5c" in html.lower()
    return {
        "ok": len(found) == len(templates) and branded,
        "templates": found,
        "branded_html": branded,
    }


def _check_crm():
    import frappe

    from lms_saas.install import CRM_MODULE
    from lms_saas.setup.verify_access import audit_crm_role_permissions

    crm_prospects_hidden = not frappe.db.exists("Workspace", "CRM & Prospects")
    if frappe.db.exists("Workspace", "CRM & Prospects"):
        crm_prospects_hidden = bool(frappe.get_doc("Workspace", "CRM & Prospects").is_hidden)
    native_crm = bool(frappe.db.exists("Workspace", "CRM"))
    lead_field = frappe.db.exists("Custom Field", "Lead-custom_consent_given")
    role_perms = audit_crm_role_permissions()
    collector_no_lead = role_perms.get("roles", {}).get("LMS Collector", {}).get("checks", {}).get("Lead", {}).get("ok")
    return {
        "ok": bool(native_crm and crm_prospects_hidden and lead_field and role_perms.get("ok") and collector_no_lead),
        "crm_module": CRM_MODULE,
        "native_crm_workspace": native_crm,
        "crm_prospects_hidden": crm_prospects_hidden,
        "lead_consent_field": bool(lead_field),
        "role_permissions": role_perms,
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
    return {
        "ok": bool(fns_ok and source_ok and charts_ok and cards_ok),
        "required": required,
        "source": bool(source_ok),
        "charts": bool(charts_ok),
        "number_cards": bool(cards_ok),
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
