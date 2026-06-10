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


def _portfolio_metrics(company=None):
    """Single-pass aggregation over the live loan book shared by all widgets.

    Uses frappe.get_list so row-level User Permissions scope a branch manager to
    their own portfolio while System Manager / Administrator see everything.
    """
    loan_filters = {"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])}
    if company:
        loan_filters["company"] = company

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

    return {"kpis": kpis, "risk_buckets": risk_buckets, "branch_outstanding": branch_outstanding}


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


def _guard():
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)
