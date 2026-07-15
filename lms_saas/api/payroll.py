"""Payroll addon API — payroll runs, payslips, loan deduction tracking.

Reuses HRMS doctypes: Payroll Entry, Salary Slip, Salary Structure.
Branch-scoped via Employee → Branch / Cost Center.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today, getdate, now_datetime

from lms_saas.utils.addons import require_addon_persona


def _require_payroll():
    require_addon_persona("payroll")


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


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_payroll_overview():
    """Branch-scoped payroll overview for the current period."""
    _require_payroll()

    employees = _branch_employees()
    emp_filter = ("in", employees) if employees else ("is", "not set")

    # Current period Payroll Entries
    current_month = getdate(today()).strftime("%Y-%m-%d")
    payroll_entries = frappe.get_all(
        "Payroll Entry",
        filters={"start_date": [">=", current_month]},
        fields=["name", "status", "start_date", "end_date", "posting_date",
                "company", "number_of_employees"],
        order_by="posting_date desc",
        limit=10,
    )

    # Salary slips for branch employees (current month)
    slips = frappe.get_all(
        "Salary Slip",
        filters={"employee": emp_filter, "start_date": [">=", current_month]},
        fields=["name", "employee", "employee_name", "status", "net_pay",
                "gross_pay", "total_deduction", "posting_date"],
        order_by="posting_date desc",
        limit=100,
    )

    # Stats
    total_slips = len(slips)
    submitted = sum(1 for s in slips if s.get("status") == "Submitted")
    draft = sum(1 for s in slips if s.get("status") == "Draft")
    cancelled = sum(1 for s in slips if s.get("status") == "Cancelled")

    total_gross = sum((s.get("gross_pay") or 0) for s in slips)
    total_net = sum((s.get("net_pay") or 0) for s in slips)
    total_deductions = sum((s.get("total_deduction") or 0) for s in slips)

    # Loan deductions (component-level)
    loan_deduction_total = 0.0
    for slip in slips:
        loan_deduction_total += _get_loan_deduction_for_slip(slip["name"])

    return {
        "payroll_entries": payroll_entries,
        "slip_count": total_slips,
        "submitted": submitted,
        "draft": draft,
        "cancelled": cancelled,
        "total_gross": total_gross,
        "total_net": total_net,
        "total_deductions": total_deductions,
        "loan_deductions": loan_deduction_total,
        "team_count": len(employees),
    }


# ---------------------------------------------------------------------------
# Salary Slips
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_salary_slips(limit=100):
    """List salary slips for branch employees."""
    _require_payroll()

    employees = _branch_employees()
    if not employees:
        return {"slips": []}

    slips = frappe.get_all(
        "Salary Slip",
        filters={"employee": ("in", employees)},
        fields=["name", "employee", "employee_name", "status", "net_pay",
                "gross_pay", "total_deduction", "posting_date",
                "start_date", "end_date", "currency"],
        order_by="posting_date desc",
        limit_page_length=int(limit),
    )
    return {"slips": slips}


@frappe.whitelist()
def get_payslip_detail(slip_name):
    """Return a single payslip with earnings and deductions breakdown."""
    _require_payroll()

    slip = frappe.get_doc("Salary Slip", slip_name)

    earnings = []
    for row in (slip.earnings or []):
        earnings.append({
            "component": row.salary_component,
            "amount": row.amount,
            "formula": row.formula if hasattr(row, "formula") else None,
        })

    deductions = []
    for row in (slip.deductions or []):
        deductions.append({
            "component": row.salary_component,
            "amount": row.amount,
            "formula": row.formula if hasattr(row, "formula") else None,
        })

    # Identify loan-related deductions
    loan_deductions = [d for d in deductions if "loan" in d["component"].lower()]

    return {
        "slip": {
            "name": slip.name,
            "employee": slip.employee,
            "employee_name": slip.employee_name,
            "status": slip.status,
            "posting_date": slip.posting_date,
            "start_date": slip.start_date,
            "end_date": slip.end_date,
            "gross_pay": slip.gross_pay,
            "total_deduction": slip.total_deduction,
            "net_pay": slip.net_pay,
            "currency": slip.currency,
            "total_earnings": getattr(slip, "gross_pay", 0),
        },
        "earnings": earnings,
        "deductions": deductions,
        "loan_deductions": loan_deductions,
    }


# ---------------------------------------------------------------------------
# Distribute payslips
# ---------------------------------------------------------------------------

@frappe.whitelist()
def distribute_payslips(slip_names=None):
    """Email payslips to branch staff. Accepts a JSON array or comma-separated list."""
    _require_payroll()

    if not _is_admin():
        # Branch managers can also distribute
        pass

    import json

    if not slip_names:
        frappe.throw(_("No payslips selected for distribution."))

    if isinstance(slip_names, str):
        try:
            slip_names = json.loads(slip_names)
        except (json.JSONDecodeError, ValueError):
            slip_names = [s.strip() for s in slip_names.split(",") if s.strip()]

    if not isinstance(slip_names, list):
        slip_names = [slip_names]

    sent = 0
    errors = []
    for name in slip_names:
        try:
            slip = frappe.get_doc("Salary Slip", name)
            if slip.status != "Submitted":
                errors.append({"slip": name, "error": "Not submitted"})
                continue
            # Trigger the standard HRMS email action
            slip.flags.ignore_permissions = True
            if hasattr(slip, "send_email_to_employee"):
                slip.send_email_to_employee()
            else:
                # Fallback: use the standard print format email
                frappe.sendmail(
                    recipients=[slip.employee_email or slip.employee_id],
                    subject=_("Salary Slip - {0}").format(slip.name),
                    message=_("Your salary slip for period {0} to {1} is ready.").format(
                        slip.start_date, slip.end_date
                    ),
                    reference_doctype="Salary Slip",
                    reference_name=slip.name,
                )
            sent += 1
        except Exception as e:
            errors.append({"slip": name, "error": str(e)})

    return {"sent": sent, "errors": errors, "total": len(slip_names)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_loan_deduction_for_slip(slip_name):
    """Sum loan-related deduction amounts for a single salary slip."""
    try:
        slip = frappe.get_doc("Salary Slip", slip_name)
        total = 0.0
        for row in (slip.deductions or []):
            if "loan" in (row.salary_component or "").lower():
                total += row.amount or 0
        return total
    except Exception:
        return 0.0