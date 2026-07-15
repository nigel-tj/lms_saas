"""Branch Analytics addon API — cross-branch KPI comparison, officer leaderboard, trends.

Reuses ``_portfolio_metrics`` and ``_collections_trend`` from the dashboard
engine so all numbers are consistent with the desk dashboard widgets.
Admins see all branches; Branch Managers are scoped to their own branch.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, today, add_to_date, formatdate

from lms_saas.utils.addons import require_addon_persona


# ---------------------------------------------------------------------------
# Guards & helpers
# ---------------------------------------------------------------------------

def _require_analytics():
    require_addon_persona("branch_analytics")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _branch():
    from lms_saas.api.staff import get_current_user_branch
    return get_current_user_branch()


def _branch_employees(branch=None):
    """Return Employee names for the given branch (or current user's branch)."""
    branch = branch or _branch()
    if not branch:
        return []
    meta = frappe.get_meta("Employee")
    filters = {"status": "Active"}
    for field in ("branch", "cost_center", "custom_lms_branch"):
        if meta.has_field(field):
            filters[field] = branch
            break
    return frappe.get_all("Employee", filters=filters, pluck="name")


def _all_branches():
    """Return list of distinct branch Cost Centers from the loan book."""
    branches = frappe.get_all(
        "Loan",
        filters={"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
        pluck="custom_lms_branch",
    )
    return sorted(set(b for b in branches if b))


# ---------------------------------------------------------------------------
# Branch Comparison
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_branch_comparison():
    """KPI comparison across all branches (or just the manager's branch).

    Returns per-branch: portfolio_outstanding, active_loans, par30, par90,
    collections (last 30 days).
    """
    _require_analytics()

    is_admin = _is_admin()
    user_branch = _branch()

    # Determine which branches to show
    if is_admin:
        branches = _all_branches()
    else:
        branches = [user_branch] if user_branch else []

    if not branches:
        return {"branches": []}

    from lms_saas.api.dashboard import _portfolio_metrics, _collections_trend

    result = []
    for branch in branches:
        # Portfolio metrics scoped by company is not branch-scoped, so we
        # compute per-branch from the loan book directly.
        loans = frappe.get_all(
            "Loan",
            filters={
                "docstatus": 1,
                "status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
                "custom_lms_branch": branch,
            },
            fields=[
                "name", "loan_amount", "total_principal_paid",
                "written_off_amount", "custom_days_past_due", "days_past_due",
            ],
            limit_page_length=0,
        )

        outstanding = 0
        active_loans = 0
        par30 = 0
        par90 = 0

        for loan in loans:
            from lms_saas.utils.calculations import principal_outstanding
            bal = principal_outstanding(
                loan.loan_amount, loan.total_principal_paid, loan.written_off_amount
            )
            outstanding += bal
            active_loans += 1
            dpd = flt(loan.custom_days_past_due or loan.days_past_due or 0)
            if dpd > 90:
                par90 += bal
            elif dpd > 30:
                par30 += bal

        # Collections in last 30 days for this branch
        branch_loans = [l.name for l in loans]
        collections_30d = 0
        if branch_loans:
            since = formatdate(add_to_date(getdate(today()), days=-30), "yyyy-mm-dd")
            repayments = frappe.get_all(
                "Loan Repayment",
                filters={
                    "docstatus": 1,
                    "against_loan": ("in", branch_loans),
                    "posting_date": (">=", since),
                },
                fields=["amount_paid"],
                limit_page_length=0,
            )
            collections_30d = sum(flt(r.amount_paid) for r in repayments)

        result.append({
            "branch": branch,
            "portfolio_outstanding": flt(outstanding),
            "active_loans": active_loans,
            "par30": flt(par30),
            "par90": flt(par90),
            "collections": flt(collections_30d),
            "par30_ratio": flt(par30 / outstanding) if outstanding else 0,
            "par90_ratio": flt(par90 / outstanding) if outstanding else 0,
        })

    return {"branches": result}


# ---------------------------------------------------------------------------
# Officer Leaderboard
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_officer_leaderboard(metric="disbursements", period_days=30):
    """Rank officers by disbursements, collections, or PAR.

    metric: "disbursements" | "collections" | "par"
    """
    _require_analytics()

    is_admin = _is_admin()
    user_branch = _branch()

    since = formatdate(add_to_date(getdate(today()), days=-int(period_days)), "yyyy-mm-dd")

    # Branch scoping
    branch_filter = None
    if not is_admin:
        branch_filter = user_branch

    # Get all loan officers from the relevant branch(es)
    if branch_filter:
        employees = _branch_employees(branch_filter)
    else:
        employees = frappe.get_all(
            "Employee",
            filters={"status": "Active"},
            pluck="name",
        )

    if not employees:
        return {"officers": [], "metric": metric, "period_days": int(period_days)}

    # Build officer name map
    officer_names = {}
    for emp in employees:
        officer_names[emp] = frappe.db.get_value("Employee", emp, "employee_name") or emp

    leaderboard = {}

    if metric == "disbursements":
        disbursements = frappe.get_all(
            "Loan Disbursement",
            filters={"docstatus": 1, "posting_date": (">=", since)},
            fields=["against_loan", "disbursed_amount"],
            limit_page_length=0,
        )
        for d in disbursements:
            loan = frappe.db.get_value(
                "Loan", d.against_loan,
                ["custom_loan_officer", "custom_lms_branch"],
                as_dict=True,
            )
            if not loan:
                continue
            if branch_filter and loan.get("custom_lms_branch") != branch_filter:
                continue
            officer = loan.custom_loan_officer or "Unassigned"
            if officer not in leaderboard:
                leaderboard[officer] = {
                    "officer": officer,
                    "officer_name": officer_names.get(officer, officer),
                    "value": 0,
                    "count": 0,
                }
            leaderboard[officer]["value"] += flt(d.disbursed_amount)
            leaderboard[officer]["count"] += 1

    elif metric == "collections":
        repayments = frappe.get_all(
            "Loan Repayment",
            filters={"docstatus": 1, "posting_date": (">=", since)},
            fields=["against_loan", "amount_paid"],
            limit_page_length=0,
        )
        for r in repayments:
            loan = frappe.db.get_value(
                "Loan", r.against_loan,
                ["custom_loan_officer", "custom_lms_branch"],
                as_dict=True,
            )
            if not loan:
                continue
            if branch_filter and loan.get("custom_lms_branch") != branch_filter:
                continue
            officer = loan.custom_loan_officer or "Unassigned"
            if officer not in leaderboard:
                leaderboard[officer] = {
                    "officer": officer,
                    "officer_name": officer_names.get(officer, officer),
                    "value": 0,
                    "count": 0,
                }
            leaderboard[officer]["value"] += flt(r.amount_paid)
            leaderboard[officer]["count"] += 1

    elif metric == "par":
        # PAR: outstanding amount that is 30+ days past due per officer
        loan_filters = {
            "docstatus": 1,
            "status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
        }
        if branch_filter:
            loan_filters["custom_lms_branch"] = branch_filter

        loans = frappe.get_all(
            "Loan",
            filters=loan_filters,
            fields=[
                "name", "loan_amount", "total_principal_paid",
                "written_off_amount", "custom_days_past_due",
                "days_past_due", "custom_loan_officer",
            ],
            limit_page_length=0,
        )
        from lms_saas.utils.calculations import principal_outstanding
        for loan in loans:
            dpd = flt(loan.custom_days_past_due or loan.days_past_due or 0)
            if dpd <= 30:
                continue
            officer = loan.custom_loan_officer or "Unassigned"
            bal = principal_outstanding(
                loan.loan_amount, loan.total_principal_paid, loan.written_off_amount
            )
            if officer not in leaderboard:
                leaderboard[officer] = {
                    "officer": officer,
                    "officer_name": officer_names.get(officer, officer),
                    "value": 0,
                    "count": 0,
                }
            leaderboard[officer]["value"] += flt(bal)
            leaderboard[officer]["count"] += 1

    officers = sorted(leaderboard.values(), key=lambda x: x["value"], reverse=True)
    return {"officers": officers, "metric": metric, "period_days": int(period_days)}


# ---------------------------------------------------------------------------
# Branch Trends
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_branch_trends(months=6, metric="portfolio_outstanding"):
    """3/6/12 month trend per branch per metric.

    metric: "portfolio_outstanding" | "active_loans" | "par30" | "par90" | "collections"
    """
    _require_analytics()

    is_admin = _is_admin()
    user_branch = _branch()

    months = int(months)
    if months not in (3, 6, 12):
        months = 6

    if is_admin:
        branches = _all_branches()
    else:
        branches = [user_branch] if user_branch else []

    if not branches:
        return {"branches": [], "metric": metric, "months": months, "labels": []}

    today_date = getdate(today())
    labels = []
    for offset in range(months - 1, -1, -1):
        dt = add_to_date(today_date, months=-offset)
        labels.append(dt.strftime("%Y-%m"))

    result = []
    for branch in branches:
        trend = []
        for i, month_start in enumerate(labels):
            # For each month, compute the metric as of that month-end
            month_end = add_to_date(getdate(month_start + "-01"), months=1, days=-1)

            if metric == "collections":
                # Collections during that month
                month_loans = frappe.get_all(
                    "Loan",
                    filters={
                        "docstatus": 1,
                        "custom_lms_branch": branch,
                    },
                    pluck="name",
                )
                value = 0
                if month_loans:
                    repayments = frappe.get_all(
                        "Loan Repayment",
                        filters={
                            "docstatus": 1,
                            "against_loan": ("in", month_loans),
                            "posting_date": ("between", [month_start + "-01", formatdate(month_end, "yyyy-mm-dd")]),
                        },
                        fields=["amount_paid"],
                        limit_page_length=0,
                    )
                    value = sum(flt(r.amount_paid) for r in repayments)
                trend.append(flt(value))
            else:
                # Snapshot metrics: approximate from current loan book
                # (historical snapshots would require a periodic snapshot table)
                loans = frappe.get_all(
                    "Loan",
                    filters={
                        "docstatus": 1,
                        "status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
                        "custom_lms_branch": branch,
                    },
                    fields=[
                        "name", "loan_amount", "total_principal_paid",
                        "written_off_amount", "custom_days_past_due", "days_past_due",
                    ],
                    limit_page_length=0,
                )
                from lms_saas.utils.calculations import principal_outstanding
                value = 0
                for loan in loans:
                    bal = principal_outstanding(
                        loan.loan_amount, loan.total_principal_paid, loan.written_off_amount
                    )
                    dpd = flt(loan.custom_days_past_due or loan.days_past_due or 0)
                    if metric == "portfolio_outstanding":
                        value += bal
                    elif metric == "active_loans":
                        value += 1
                    elif metric == "par30" and dpd > 30:
                        value += bal
                    elif metric == "par90" and dpd > 90:
                        value += bal
                trend.append(flt(value))

        result.append({
            "branch": branch,
            "trend": trend,
        })

    return {
        "branches": result,
        "metric": metric,
        "months": months,
        "labels": [formatdate(m + "-01", "MMM yy") for m in labels],
    }


# ---------------------------------------------------------------------------
# Benchmark Alerts
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_benchmark_alerts():
    """Return branches where KPIs breach configurable thresholds.

    Default thresholds:
      - PAR30 ratio > 5%
      - PAR90 ratio > 2%
      - Collections (30d) < 50% of portfolio outstanding (proxy)
    """
    _require_analytics()

    is_admin = _is_admin()
    user_branch = _branch()

    if is_admin:
        branches = _all_branches()
    else:
        branches = [user_branch] if user_branch else []

    if not branches:
        return {"alerts": []}

    comparison = get_branch_comparison()
    branch_data = comparison.get("branches", [])

    alerts = []
    for bd in branch_data:
        branch = bd["branch"]

        # PAR30 ratio > 5%
        if bd["par30_ratio"] > 0.05:
            alerts.append({
                "branch": branch,
                "metric": "PAR30 Ratio",
                "value": f"{flt(bd['par30_ratio'] * 100, 2)}%",
                "threshold": "5%",
                "severity": "warning",
                "message": _("PAR30 ratio exceeds 5% threshold"),
            })

        # PAR90 ratio > 2%
        if bd["par90_ratio"] > 0.02:
            alerts.append({
                "branch": branch,
                "metric": "PAR90 Ratio",
                "value": f"{flt(bd['par90_ratio'] * 100, 2)}%",
                "threshold": "2%",
                "severity": "danger",
                "message": _("PAR90 ratio exceeds 2% threshold"),
            })

        # Collections < 50% of outstanding (monthly proxy)
        if bd["portfolio_outstanding"] > 0:
            collection_ratio = bd["collections"] / bd["portfolio_outstanding"]
            if collection_ratio < 0.02:  # less than 2% monthly collection rate
                alerts.append({
                    "branch": branch,
                    "metric": "Collection Rate",
                    "value": f"{flt(collection_ratio * 100, 2)}%",
                    "threshold": "2%",
                    "severity": "warning",
                    "message": _("Monthly collection rate below 2% of outstanding"),
                })

    return {"alerts": alerts}