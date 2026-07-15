"""Budgeting addon API — branch budgets, budget vs actual, forecasting, variance.

Reuses ERPNext ``Budget`` doctype and ``GL Entry`` for actuals.
Also leverages LMS dashboard metrics for portfolio growth forecasting.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today, getdate, get_first_day, get_last_day, add_months, flt

from lms_saas.utils.addons import require_addon_persona


def _require_budgeting():
    require_addon_persona("budgeting")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _branch():
    from lms_saas.api.staff import get_current_user_branch
    return get_current_user_branch()


def _branch_cost_center():
    """Return the Cost Center for the current user's branch."""
    branch = _branch()
    return branch  # In this project, branch == Cost Center


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_branch_budgets(limit=50):
    """Return ERPNext Budget records for the branch Cost Center."""
    _require_budgeting()

    filters = {}
    if not _is_admin():
        cost_center = _branch_cost_center()
        if cost_center:
            # Budgets can be scoped to a Cost Center
            budget_meta = frappe.get_meta("Budget")
            if budget_meta.has_field("cost_center"):
                filters["cost_center"] = cost_center

    budgets = frappe.get_all(
        "Budget",
        filters=filters,
        fields=["name", "budget_against", "cost_center", "from_fiscal_year",
                "to_fiscal_year", "company"],
        order_by="from_fiscal_year desc",
        limit_page_length=int(limit),
    )

    # Enrich with budget amounts
    for b in budgets:
        doc = frappe.get_doc("Budget", b["name"])
        total = 0
        for row in (doc.accounts or []):
            total += flt(row.budget_amount or 0)
        b["total_budget"] = total
        b["account_count"] = len(doc.accounts or [])

    return {"budgets": budgets}


@frappe.whitelist()
def get_budget_vs_actual(budget_name=None, fiscal_year=None):
    """Compare budgeted vs actual spending from GL Entry."""
    _require_budgeting()

    if budget_name:
        budget = frappe.get_doc("Budget", budget_name)
        fiscal_year = budget.from_fiscal_year
        cost_center = budget.cost_center
    else:
        cost_center = _branch_cost_center() if not _is_admin() else None
        if not fiscal_year:
            # Default to current fiscal year
            fy = frappe.db.get_value("Fiscal Year", {"disabled": 0}, "name", order_by="year_start_date desc")
            fiscal_year = fy

    # Get budget accounts
    budget_accounts = []
    if budget_name:
        for row in (frappe.get_doc("Budget", budget_name).accounts or []):
            budget_accounts.append({
                "account": row.account,
                "budget_amount": row.budget_amount or 0,
            })
    else:
        # Aggregate all budgets for the fiscal year / cost center
        budget_filters = {"from_fiscal_year": fiscal_year}
        if cost_center:
            budget_filters["cost_center"] = cost_center
        for b in frappe.get_all("Budget", filters=budget_filters, pluck="name"):
            for row in (frappe.get_doc("Budget", b).accounts or []):
                budget_accounts.append({
                    "account": row.account,
                    "budget_amount": row.budget_amount or 0,
                })

    # Get actuals from GL Entry
    fy_doc = frappe.db.get_value("Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"], as_dict=True)
    if not fy_doc:
        return {"comparisons": []}

    result = []
    for ba in budget_accounts:
        gl_filters = {
            "account": ba["account"],
            "posting_date": ("between", [fy_doc["year_start_date"], fy_doc["year_end_date"]]),
            "is_cancelled": 0,
        }
        if cost_center:
            gl_filters["cost_center"] = cost_center

        actual = flt(frappe.db.get_value(
            "GL Entry",
            filters=gl_filters,
            fieldname="sum(debit) - sum(credit)",
        ) or 0)

        variance = ba["budget_amount"] - actual
        result.append({
            "account": ba["account"],
            "budgeted": ba["budget_amount"],
            "actual": actual,
            "variance": variance,
            "utilization_pct": round((actual / ba["budget_amount"] * 100), 1) if ba["budget_amount"] else 0,
        })

    return {"comparisons": result, "fiscal_year": fiscal_year}


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_forecast(months=12):
    """Project portfolio growth based on historical disbursement trends."""
    _require_budgeting()

    months = int(months)
    cost_center = _branch_cost_center() if not _is_admin() else None

    # Get historical disbursement data from Loan doctype
    loan_filters = {"docstatus": 1}
    if cost_center:
        loan_meta = frappe.get_meta("Loan")
        if loan_meta.has_field("custom_lms_branch"):
            loan_filters["custom_lms_branch"] = cost_center

    # Get last 12 months of disbursement amounts
    historical = []
    for i in range(months, 0, -1):
        month_start = get_first_day(add_months(today(), -i))
        month_end = get_last_day(add_months(today(), -i))
        filters = dict(loan_filters)
        filters["disbursement_date"] = ("between", [month_start, month_end])
        total = flt(frappe.db.get_value(
            "Loan",
            filters=filters,
            fieldname="sum(disbursed_amount)",
        ) or 0)
        historical.append({
            "month": month_start.strftime("%Y-%m"),
            "amount": total,
        })

    # Simple linear projection: average growth rate
    growth_rates = []
    for i in range(1, len(historical)):
        prev = historical[i - 1]["amount"]
        curr = historical[i]["amount"]
        if prev > 0:
            growth_rates.append((curr - prev) / prev)

    avg_growth = sum(growth_rates) / len(growth_rates) if growth_rates else 0
    last_amount = historical[-1]["amount"] if historical else 0

    forecast = []
    for i in range(1, months + 1):
        projected = last_amount * ((1 + avg_growth) ** i)
        forecast.append({
            "month": add_months(today(), i).strftime("%Y-%m"),
            "projected": round(projected, 2),
        })

    return {
        "historical": historical,
        "forecast": forecast,
        "avg_growth_rate": round(avg_growth * 100, 2) if avg_growth else 0,
    }


# ---------------------------------------------------------------------------
# Variance Analysis
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_variance_analysis(threshold=10):
    """Return branches/categories exceeding the variance threshold (%)."""
    _require_budgeting()

    threshold = float(threshold)
    cost_center = _branch_cost_center() if not _is_admin() else None

    # Get all budgets
    budget_filters = {}
    if cost_center:
        budget_filters["cost_center"] = cost_center

    budgets = frappe.get_all("Budget", filters=budget_filters, pluck="name")

    variances = []
    for b_name in budgets:
        budget = frappe.get_doc("Budget", b_name)
        fy = budget.from_fiscal_year
        fy_doc = frappe.db.get_value("Fiscal Year", fy, ["year_start_date", "year_end_date"], as_dict=True)
        if not fy_doc:
            continue

        for row in (budget.accounts or []):
            gl_filters = {
                "account": row.account,
                "posting_date": ("between", [fy_doc["year_start_date"], fy_doc["year_end_date"]]),
                "is_cancelled": 0,
            }
            if budget.cost_center:
                gl_filters["cost_center"] = budget.cost_center

            actual = flt(frappe.db.get_value(
                "GL Entry",
                filters=gl_filters,
                fieldname="sum(debit) - sum(credit)",
            ) or 0)

            budgeted = row.budget_amount or 0
            if not budgeted:
                continue

            variance_pct = ((actual - budgeted) / budgeted) * 100
            if abs(variance_pct) >= threshold:
                variances.append({
                    "budget": b_name,
                    "cost_center": budget.cost_center,
                    "account": row.account,
                    "budgeted": budgeted,
                    "actual": actual,
                    "variance": actual - budgeted,
                    "variance_pct": round(variance_pct, 1),
                })

    variances.sort(key=lambda v: abs(v["variance_pct"]), reverse=True)
    return {"variances": variances, "threshold": threshold}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_budgeting_stats():
    """Overview stats for the budgeting dashboard."""
    _require_budgeting()

    total_budgets = frappe.db.count("Budget")
    active_fy = frappe.db.count("Fiscal Year", {"disabled": 0})

    # Total budgeted across all budgets
    total_budgeted = 0
    for b in frappe.get_all("Budget", pluck="name"):
        doc = frappe.get_doc("Budget", b)
        for row in (doc.accounts or []):
            total_budgeted += flt(row.budget_amount or 0)

    # Count accounts over budget (simplified)
    over_budget = 0
    for b in frappe.get_all("Budget", pluck="name"):
        doc = frappe.get_doc("Budget", b)
        fy_doc = frappe.db.get_value("Fiscal Year", doc.from_fiscal_year, ["year_start_date", "year_end_date"], as_dict=True)
        if not fy_doc:
            continue
        for row in (doc.accounts or []):
            actual = flt(frappe.db.get_value(
                "GL Entry",
                filters={
                    "account": row.account,
                    "posting_date": ("between", [fy_doc["year_start_date"], fy_doc["year_end_date"]]),
                    "is_cancelled": 0,
                },
                fieldname="sum(debit) - sum(credit)",
            ) or 0)
            if actual > flt(row.budget_amount or 0):
                over_budget += 1

    return {
        "total_budgets": total_budgets,
        "active_fiscal_years": active_fy,
        "total_budgeted": total_budgeted,
        "accounts_over_budget": over_budget,
    }