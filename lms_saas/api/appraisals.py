"""Appraisals addon API — cycles, appraisals, goals, KRA scoring.

Reuses HRMS doctypes: Appraisal, Appraisal Cycle, Appraisal Goal, Appraisal KRA.
Branch-scoped via Employee → Branch / Cost Center.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today, getdate, now_datetime

from lms_saas.utils.addons import require_addon_persona


def _require_appraisals():
    require_addon_persona("appraisals")


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


def _current_employee():
    user = frappe.session.user
    return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_appraisal_cycles(limit=20):
    """Return active appraisal cycles with completion rates."""
    _require_appraisals()

    employees = _branch_employees()
    emp_filter = ("in", employees) if employees else ("is", "not set")

    cycles = frappe.get_all(
        "Appraisal Cycle",
        filters={"docstatus": ["!=", 2]},
        fields=["name", "cycle_name", "start_date", "end_date", "status",
                "company", "description"],
        order_by="start_date desc",
        limit_page_length=int(limit),
    )

    for cycle in cycles:
        # Count appraisals in this cycle for branch employees
        total = frappe.db.count("Appraisal", {
            "appraisal_cycle": cycle["name"],
            "employee": emp_filter,
        })
        completed = frappe.db.count("Appraisal", {
            "appraisal_cycle": cycle["name"],
            "employee": emp_filter,
            "docstatus": 1,
        })
        cycle["total_appraisals"] = total
        cycle["completed"] = completed
        cycle["completion_rate"] = round((completed / total * 100), 1) if total else 0

    return {"cycles": cycles}


# ---------------------------------------------------------------------------
# Appraisals
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_appraisals(cycle=None, limit=100):
    """List appraisals for branch employees."""
    _require_appraisals()

    employees = _branch_employees()
    if not employees:
        return {"appraisals": []}

    filters = {"employee": ("in", employees)}
    if cycle:
        filters["appraisal_cycle"] = cycle

    appraisals = frappe.get_all(
        "Appraisal",
        filters=filters,
        fields=["name", "employee", "employee_name", "appraisal_cycle",
                "status", "final_score", "goal_score_percentage", "posting_date",
                "docstatus"],
        order_by="posting_date desc",
        limit_page_length=int(limit),
    )
    return {"appraisals": appraisals}


@frappe.whitelist()
def get_appraisal_detail(appraisal_name):
    """Return a single appraisal with goals and KRA scores."""
    _require_appraisals()

    doc = frappe.get_doc("Appraisal", appraisal_name)

    # Goals (stored in appraisal_kra child table)
    goals = []
    if hasattr(doc, "appraisal_kra"):
        for row in (doc.appraisal_kra or []):
            goals.append({
                "name": row.name,
                "goal": getattr(row, "goal", None) or getattr(row, "goal_title", None) or "",
                "kra": getattr(row, "kra", None) or "",
                "per_weightage": getattr(row, "per_weightage", 0) or 0,
                "score": getattr(row, "score", 0) or 0,
                "score_earned": getattr(row, "score_earned", 0) or 0,
            })

    # KRA scores (if the child table exists)
    kras = []
    if hasattr(doc, "appraisal_kra"):
        for row in (doc.appraisal_kra or []):
            kras.append({
                "name": row.name,
                "kra": getattr(row, "kra", None) or "",
                "per_weightage": getattr(row, "per_weightage", 0) or 0,
                "score": getattr(row, "score", 0) or 0,
                "score_earned": getattr(row, "score_earned", 0) or 0,
            })

    return {
        "appraisal": {
            "name": doc.name,
            "employee": doc.employee,
            "employee_name": doc.employee_name,
            "appraisal_cycle": doc.appraisal_cycle,
            "status": doc.status,
            "final_score": getattr(doc, "final_score", 0) or 0,
            "goal_score_percentage": getattr(doc, "goal_score_percentage", 0) or 0,
            "posting_date": doc.posting_date,
            "docstatus": doc.docstatus,
        },
        "goals": goals,
        "kras": kras,
    }


# ---------------------------------------------------------------------------
# Goal management
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_goal(appraisal_name, goal_title, kra=None, per_weightage=0):
    """Officer sets a goal on an appraisal."""
    _require_appraisals()

    doc = frappe.get_doc("Appraisal", appraisal_name)
    if doc.docstatus != 0:
        frappe.throw(_("Cannot add goals to a submitted appraisal."))

    if not hasattr(doc, "appraisal_kra"):
        frappe.throw(_("This appraisal does not support goals."))

    doc.append("appraisal_kra", {
        "goal": goal_title,
        "kra": kra,
        "per_weightage": float(per_weightage or 0),
    })
    doc.flags.ignore_permissions = True
    doc.save()
    return {"ok": True, "appraisal": appraisal_name}


@frappe.whitelist()
def score_kra(appraisal_name, kra_row_name, score):
    """Manager scores a KRA on an appraisal."""
    _require_appraisals()

    doc = frappe.get_doc("Appraisal", appraisal_name)
    if doc.docstatus != 0:
        frappe.throw(_("Cannot score a submitted appraisal."))

    # Find the KRA row in appraisal_kra or goals child table
    scored = False
    for table_attr in ("appraisal_kra", "goals"):
        if not hasattr(doc, table_attr):
            continue
        for row in (getattr(doc, table_attr) or []):
            if row.name == kra_row_name:
                row.score = float(score)
                # Recalculate score_earned if per_weightage exists
                if hasattr(row, "per_weightage"):
                    row.score_earned = (float(score) * float(row.per_weightage or 0)) / 100
                scored = True
                break
        if scored:
            break

    if not scored:
        frappe.throw(_("KRA row not found in this appraisal."))

    doc.flags.ignore_permissions = True
    doc.save()
    return {"ok": True, "score": float(score)}