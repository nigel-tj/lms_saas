"""HR Management addon API — leave, attendance, expenses, shifts, directory.

Reuses HRMS doctypes: Leave Application, Attendance, Expense Claim,
Shift Assignment, Shift Request, Employee.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today, getdate, now_datetime

from lms_saas.utils.addons import require_addon_persona


def _require_hr():
    require_addon_persona("hr_management")


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
# Dashboard
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_hr_dashboard():
    """Branch-scoped HR overview for the manager."""
    _require_hr()

    employees = _branch_employees()
    emp_filter = {"employee": ("in", employees)} if employees else {"employee": ("is", "not set")}

    # Leave applications pending approval
    pending_leaves = frappe.db.count("Leave Application", {
        "docstatus": 0,
        "employee": ("in", employees) if employees else ("is", "not set"),
    })

    # Today's attendance
    present = frappe.db.count("Attendance", {
        "attendance_date": today(),
        "status": "Present",
        "employee": ("in", employees) if employees else ("is", "not set"),
    })
    absent = frappe.db.count("Attendance", {
        "attendance_date": today(),
        "status": "Absent",
        "employee": ("in", employees) if employees else ("is", "not set"),
    })

    # Pending expense claims
    pending_expenses = frappe.db.count("Expense Claim", {
        "docstatus": 0,
        "employee": ("in", employees) if employees else ("is", "not set"),
    })

    # Pending shift requests
    pending_shifts = frappe.db.count("Shift Request", {
        "docstatus": 0,
        "employee": ("in", employees) if employees else ("is", "not set"),
    })

    return {
        "team_count": len(employees),
        "pending_leaves": pending_leaves,
        "present_today": present,
        "absent_today": absent,
        "pending_expenses": pending_expenses,
        "pending_shift_requests": pending_shifts,
    }


# ---------------------------------------------------------------------------
# Leave Applications
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_pending_leaves(limit=50):
    """Return leave applications pending approval for the branch."""
    _require_hr()

    employees = _branch_employees()
    if not employees:
        return {"leaves": []}

    leaves = frappe.get_all(
        "Leave Application",
        filters={"docstatus": 0, "employee": ("in", employees)},
        fields=["name", "employee", "employee_name", "leave_type",
                "from_date", "to_date", "total_leave_days", "description",
                "leave_approver", "posting_date"],
        order_by="posting_date desc",
        limit_page_length=int(limit),
    )
    return {"leaves": leaves}


@frappe.whitelist()
def approve_leave(leave_name, status="Approved", reason=None):
    """Manager: approve or reject a leave application."""
    _require_hr()

    doc = frappe.get_doc("Leave Application", leave_name)
    if doc.docstatus != 0:
        frappe.throw(_("Leave application is already processed."))

    doc.status = status
    if reason:
        doc.description = (doc.description or "") + f"\n\nManager note: {reason}"
    doc.flags.ignore_permissions = True
    doc.submit()
    return {"ok": True, "status": status}


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_attendance_today():
    """Return today's attendance for the branch."""
    _require_hr()

    employees = _branch_employees()
    if not employees:
        return {"records": []}

    records = frappe.get_all(
        "Attendance",
        filters={"attendance_date": today(), "employee": ("in", employees)},
        fields=["name", "employee", "employee_name", "status",
                "attendance_date", "in_time", "out_time", "shift"],
        order_by="employee_name asc",
    )

    # Find absentees (employees with no attendance record today)
    attended = {r["employee"] for r in records}
    absentees = [emp for emp in employees if emp not in attended]
    absentee_details = []
    for emp in absentees:
        name = frappe.db.get_value("Employee", emp, "employee_name")
        absentee_details.append({"employee": emp, "employee_name": name, "status": "No Record"})

    return {"records": records, "absentees": absentee_details}


# ---------------------------------------------------------------------------
# Expense Claims
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_pending_expenses(limit=50):
    """Return expense claims pending approval for the branch."""
    _require_hr()

    employees = _branch_employees()
    if not employees:
        return {"claims": []}

    claims = frappe.get_all(
        "Expense Claim",
        filters={"docstatus": 0, "employee": ("in", employees)},
        fields=["name", "employee", "employee_name", "grand_total",
                "total_sanctioned_amount", "posting_date", "remark"],
        order_by="posting_date desc",
        limit_page_length=int(limit),
    )
    return {"claims": claims}


@frappe.whitelist()
def approve_expense(claim_name, status="Approved", reason=None):
    """Manager: approve or reject an expense claim."""
    _require_hr()

    doc = frappe.get_doc("Expense Claim", claim_name)
    if doc.docstatus != 0:
        frappe.throw(_("Expense claim is already processed."))

    doc.approval_status = status
    if reason:
        doc.remark = reason
    doc.flags.ignore_permissions = True
    doc.submit()
    return {"ok": True, "status": status}


# ---------------------------------------------------------------------------
# Shift Requests
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_pending_shift_requests(limit=50):
    """Return shift requests pending approval."""
    _require_hr()

    employees = _branch_employees()
    if not employees:
        return {"requests": []}

    requests = frappe.get_all(
        "Shift Request",
        filters={"docstatus": 0, "employee": ("in", employees)},
        fields=["name", "employee", "employee_name", "shift_type",
                "from_date", "to_date", "approver"],
        order_by="from_date desc",
        limit_page_length=int(limit),
    )
    return {"requests": requests}


@frappe.whitelist()
def approve_shift_request(request_name, status="Approved"):
    """Manager: approve or reject a shift request."""
    _require_hr()

    doc = frappe.get_doc("Shift Request", request_name)
    if doc.docstatus != 0:
        frappe.throw(_("Shift request is already processed."))

    doc.status = status
    doc.flags.ignore_permissions = True
    doc.submit()
    return {"ok": True, "status": status}


# ---------------------------------------------------------------------------
# Team Directory
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_team_directory():
    """Return the branch team directory."""
    _require_hr()

    employees = _branch_employees()
    if not employees:
        return {"staff": []}

    staff = frappe.get_all(
        "Employee",
        filters={"name": ("in", employees)},
        fields=["name", "employee_name", "designation", "department",
                "cell_number", "personal_email", "user_id",
                "custom_lms_persona", "status"],
        order_by="employee_name asc",
    )
    return {"staff": staff}