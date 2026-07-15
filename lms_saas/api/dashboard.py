import frappe
from frappe.utils import flt, getdate, today
from frappe.utils.data import add_to_date, formatdate

from lms_saas.utils.calculations import principal_outstanding

RISK_LABELS = ["Current", "PAR 30+", "PAR 60+", "PAR 90+"]


@frappe.whitelist()
def get_desk_dashboard(company=None):
    """Return aggregate portfolio metrics for LMS desk dashboard widgets."""
    _guard()
    metrics = _portfolio_metrics(company)
    return {
        "kpis": metrics["kpis"],
        "risk_buckets": metrics["risk_buckets"],
        "collections_trend": _collections_trend(company=company),
        "branch_outstanding": _sorted_bars(metrics["branch_outstanding"], limit=6),
    }


@frappe.whitelist()
def get_chart_data(chart_name=None, filters=None, **kwargs):
    """Dashboard Chart Source endpoint for the native LMS Operations charts.

    Returns frappe-charts compatible {labels, datasets} for the requested metric.
    """
    _guard()
    filters = _parse_filters(filters)
    metric = filters.get("metric") or "risk_composition"
    company = filters.get("company")

    if metric == "collections_trend":
        rows = _collections_trend(company=company)
        return {
            "labels": [row["label"] for row in rows],
            "datasets": [{"name": "Collections", "values": [row["value"] for row in rows]}],
        }

    metrics = _portfolio_metrics(company)

    if metric == "branch_concentration":
        rows = _sorted_bars(metrics["branch_outstanding"], limit=6)
        return {
            "labels": [row["label"] for row in rows],
            "datasets": [{"name": "Outstanding", "values": [row["value"] for row in rows]}],
        }

    buckets = metrics["risk_buckets"]
    return {
        "labels": RISK_LABELS,
        "datasets": [
            {
                "name": "Outstanding",
                "values": [
                    flt(buckets["current"]),
                    flt(buckets["par30"]),
                    flt(buckets["par60"]),
                    flt(buckets["par90"]),
                ],
            }
        ],
    }


@frappe.whitelist()
def get_kpi_card(filters=None, **kwargs):
    """Number Card (type=Custom) endpoint returning a single KPI value."""
    _guard()
    filters = _parse_filters(filters)
    kpi = filters.get("kpi") or "portfolio_outstanding"
    company = filters.get("company")

    metrics = _portfolio_metrics(company)
    kpis = metrics["kpis"]

    currency_kpis = {"portfolio_outstanding", "par30_outstanding", "par90_outstanding"}
    value = flt(kpis.get(kpi, 0))

    # Return a display string (not {value, fieldtype}) so Frappe's custom Number Card
    # path skips shorten_number/format_currency, which would prefix counts with "R".
    if kpi in currency_kpis:
        return frappe.format_value(value, {"fieldtype": "Currency"})
    return frappe.format_value(int(value), {"fieldtype": "Int"})


def _portfolio_metrics(company=None, branch=None):
    """Single-pass aggregation over the live loan book shared by all widgets.

    Uses frappe.get_list so row-level User Permissions scope a branch manager to
    their own portfolio while System Manager / Administrator see everything.
    When ``branch`` is provided, loans are additionally filtered by
    ``custom_lms_branch`` so portal KPIs match the branch-scoped tab views.
    Results are cached for 5 minutes in Redis.
    """
    cache_key = f"lms_dashboard:{company or 'all'}:{branch or 'all'}:{frappe.session.user}"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    loan_filters = {"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])}
    if company:
        loan_filters["company"] = company
    if branch:
        loan_filters["custom_lms_branch"] = branch

    loans = frappe.get_list(
        "Loan",
        filters=loan_filters,
        fields=[
            "name",
            "company",
            "loan_amount",
            "total_principal_paid",
            "written_off_amount",
            "days_past_due",
            "custom_days_past_due",
            "custom_lms_branch",
        ],
        limit_page_length=0,
        ignore_permissions=False,
    )

    kpis = {
        "portfolio_outstanding": 0,
        "active_loans": 0,
        "par30_outstanding": 0,
        "par90_outstanding": 0,
        "npa_count": 0,
    }
    risk_buckets = {"current": 0, "par30": 0, "par60": 0, "par90": 0}
    branch_outstanding = {}

    for loan in loans:
        # Portfolio exposure = outstanding principal (loan_amount net of principal
        # repaid and write-offs). total_payment includes interest, so it must NOT
        # be subtracted from loan_amount here.
        outstanding = principal_outstanding(
            loan.loan_amount, loan.total_principal_paid, loan.written_off_amount
        )
        kpis["portfolio_outstanding"] += outstanding
        kpis["active_loans"] += 1
        dpd = flt(loan.custom_days_past_due or loan.days_past_due or 0)

        if dpd > 90:
            risk_buckets["par90"] += outstanding
            kpis["par90_outstanding"] += outstanding
            kpis["npa_count"] += 1
        elif dpd > 60:
            risk_buckets["par60"] += outstanding
        elif dpd > 30:
            risk_buckets["par30"] += outstanding
            kpis["par30_outstanding"] += outstanding
        else:
            risk_buckets["current"] += outstanding

        branch = loan.custom_lms_branch or "Unassigned"
        branch_outstanding[branch] = branch_outstanding.get(branch, 0) + outstanding

    result = {"kpis": kpis, "risk_buckets": risk_buckets, "branch_outstanding": branch_outstanding}
    # Cache for 5 minutes
    frappe.cache().set_value(cache_key, result, expires_in_sec=300)
    return result


def invalidate_dashboard_cache():
    """Clear dashboard cache (call on Loan submit/cancel)."""
    frappe.cache().delete_keys("lms_dashboard:*")


def _collections_trend(company=None, months=6):
    month_totals = {}
    today_date = getdate(today())
    for offset in range(months - 1, -1, -1):
        dt = add_to_date(today_date, months=-offset)
        month_totals[dt.strftime("%Y-%m")] = 0

    repayment_filters = {"docstatus": 1}
    if company:
        loan_names = frappe.get_all("Loan", filters={"company": company}, pluck="name")
        if not loan_names:
            return [{"label": formatdate(f"{month}-01", "MMM yyyy"), "value": 0} for month in month_totals]
        repayment_filters["against_loan"] = ("in", loan_names)

    repayments = frappe.get_all(
        "Loan Repayment",
        filters=repayment_filters,
        fields=["posting_date", "amount_paid"],
        limit_page_length=2000,
    )
    for repayment in repayments:
        if not repayment.get("posting_date"):
            continue
        month = getdate(repayment.posting_date).strftime("%Y-%m")
        if month in month_totals:
            month_totals[month] += flt(repayment.amount_paid)

    return [{"label": formatdate(f"{month}-01", "MMM yyyy"), "value": flt(value)} for month, value in month_totals.items()]


def _sorted_bars(raw_map, limit=6):
    sorted_rows = sorted(raw_map.items(), key=lambda row: row[1], reverse=True)[:limit]
    return [{"label": label, "value": flt(value)} for label, value in sorted_rows]


def _parse_filters(filters):
    if not filters:
        return {}
    if isinstance(filters, str):
        try:
            return frappe.parse_json(filters) or {}
        except Exception:
            return {}
    if isinstance(filters, dict):
        return filters
    return {}


@frappe.whitelist()
def get_application_pipeline(company=None):
    """Loan application pipeline counts by status + recent applications."""
    _guard()
    filters = {}
    if company:
        filters["company"] = company
    apps = frappe.get_all(
        "Loan Application",
        filters=filters,
        fields=["name", "applicant", "loan_amount", "status", "loan_product", "creation"],
        order_by="creation desc",
        limit_page_length=50,
    )
    counts = {"Draft": 0, "Submitted": 0, "Approved": 0, "Rejected": 0}
    for app in apps:
        status = app.status or "Draft"
        counts[status] = counts.get(status, 0) + 1
    return {"counts": counts, "applications": apps}


@frappe.whitelist()
def get_branch_overview(company=None):
    """Branch manager oversight: officer performance, branch comparison, exceptions."""
    _guard()
    metrics = _portfolio_metrics(company)
    # Officer performance
    officers = frappe.get_all(
        "Loan",
        filters={"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
        fields=["custom_loan_officer", "loan_amount", "total_principal_paid", "written_off_amount", "custom_days_past_due"],
    )
    officer_stats = {}
    for loan in officers:
        officer = loan.custom_loan_officer or "Unassigned"
        if officer not in officer_stats:
            officer_stats[officer] = {"loans": 0, "outstanding": 0, "par_count": 0}
        officer_stats[officer]["loans"] += 1
        officer_stats[officer]["outstanding"] += principal_outstanding(
            loan.loan_amount, loan.total_principal_paid, loan.written_off_amount
        )
        if flt(loan.custom_days_past_due or 0) > 30:
            officer_stats[officer]["par_count"] += 1

    # Exceptions: loans > 60 DPD
    exceptions = frappe.get_all(
        "Loan",
        filters={
            "docstatus": 1,
            "status": ("in", ["Disbursed", "Active"]),
            "custom_days_past_due": (">", 60),
        },
        fields=["name", "applicant", "custom_days_past_due", "custom_lms_branch", "custom_loan_officer"],
        order_by="custom_days_past_due desc",
        limit_page_length=20,
    )

    # Pending approvals (disbursements needing four-eyes)
    pending_approvals = frappe.get_all(
        "Loan Disbursement",
        filters={"docstatus": 0},
        fields=["name", "against_loan", "disbursed_amount", "owner", "creation"],
        order_by="creation desc",
        limit_page_length=10,
    )

    return {
        "officer_performance": [
            {"officer": k, **v} for k, v in sorted(officer_stats.items(), key=lambda x: x[1]["outstanding"], reverse=True)
        ],
        "exceptions": exceptions,
        "pending_approvals": pending_approvals,
        "branch_outstanding": _sorted_bars(metrics["branch_outstanding"], limit=6),
    }


@frappe.whitelist()
def get_collections_overview(company=None):
    """Collections workspace: today's collections, collector leaderboard, arrears summary."""
    _guard()
    today_str = today()

    # Today's collections
    today_repayments = frappe.get_all(
        "Loan Repayment",
        filters={"docstatus": 1, "posting_date": today_str},
        fields=["name", "amount_paid", "owner"],
    )
    today_total = sum(flt(r.amount_paid) for r in today_repayments)
    today_count = len(today_repayments)

    # Collector leaderboard
    collector_totals = {}
    for r in today_repayments:
        collector_totals[r.owner] = collector_totals.get(r.owner, 0) + flt(r.amount_paid)
    leaderboard = sorted(collector_totals.items(), key=lambda x: x[1], reverse=True)[:5]

    # Arrears summary by bucket
    loans = frappe.get_all(
        "Loan",
        filters={"docstatus": 1, "status": ("in", ["Disbursed", "Active"])},
        fields=["custom_days_past_due", "loan_amount", "total_principal_paid", "written_off_amount"],
    )
    arrears = {"current": 0, "par30": 0, "par60": 0, "par90": 0}
    for loan in loans:
        dpd = flt(loan.custom_days_past_due or 0)
        outstanding = principal_outstanding(loan.loan_amount, loan.total_principal_paid, loan.written_off_amount)
        if dpd > 90:
            arrears["par90"] += outstanding
        elif dpd > 60:
            arrears["par60"] += outstanding
        elif dpd > 30:
            arrears["par30"] += outstanding
        else:
            arrears["current"] += outstanding

    return {
        "today_total": today_total,
        "today_count": today_count,
        "leaderboard": [{"collector": c, "amount": a} for c, a in leaderboard],
        "arrears": arrears,
    }


@frappe.whitelist()
def get_system_health():
    """Admin system health: scheduler, integrations, errors, backup."""
    _guard()
    import json

    # Scheduler status
    scheduler_enabled = bool(frappe.db.get_single_value("System Settings", "enable_scheduler"))

    # Integration status
    integrations = {
        "aml": bool(frappe.conf.get("lms_aml_enabled", False)),
        "credit_bureau": bool(frappe.conf.get("lms_credit_bureau_enabled", False)),
        "sms": bool(frappe.db.get_single_value("SMS Settings", "sms_gateway_url")),
        "payments": bool(frappe.conf.get("lms_payments_enabled", False)),
    }

    # Recent errors (last 24h)
    from frappe.utils import add_days

    since = add_days(today(), -1)
    error_count = frappe.db.count("Error Log", {"creation": (">=", since)})

    # Last backup (check file existence)
    import os

    backup_dir = frappe.get_site_path("private", "backups")
    last_backup = None
    if os.path.isdir(backup_dir):
        files = sorted(
            [f for f in os.listdir(backup_dir) if f.endswith(".sql.gz")],
            reverse=True,
        )
        if files:
            last_backup = files[0]

    return {
        "scheduler_enabled": scheduler_enabled,
        "integrations": integrations,
        "error_count_24h": error_count,
        "last_backup_file": last_backup,
    }


def _guard():
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)
