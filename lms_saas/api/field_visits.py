"""Field Visits addon API — scheduling, geo-tagged check-in, completion, stats.

Uses the new ``LMS Field Visit`` doctype. Officers and collectors manage
their visit schedules; managers oversee branch visits.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, today, now_datetime, getdate

from lms_saas.utils.addons import require_addon_persona


# ---------------------------------------------------------------------------
# Guards & helpers
# ---------------------------------------------------------------------------

def _require_visits():
    require_addon_persona("field_visits")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _branch():
    from lms_saas.api.staff import get_current_user_branch
    return get_current_user_branch()


def _current_employee():
    user = frappe.session.user
    return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def _current_persona():
    from lms_saas.utils.portal import resolve_portal_persona
    return resolve_portal_persona() or "Staff"


def _default_company():
    return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_default("company")


# ---------------------------------------------------------------------------
# Visit Schedule
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_visit_schedule(status=None, limit=100):
    """Return planned visits for the current officer/collector (or branch for managers)."""
    _require_visits()

    persona = _current_persona()
    is_admin = _is_admin()
    employee = _current_employee()

    filters = {}
    if status:
        filters["status"] = status

    if not is_admin:
        if persona in ("Loan Officer", "Collector"):
            # Officers/collectors see their own visits
            filters["officer"] = employee
        elif persona == "Branch Manager":
            # Managers see all visits in their branch
            branch = _branch()
            if branch:
                filters["branch"] = branch

    visits = frappe.get_all(
        "LMS Field Visit",
        filters=filters,
        fields=[
            "name", "visit_type", "loan", "customer", "officer",
            "planned_date", "check_in_time", "check_in_lat", "check_in_lon",
            "status", "branch", "company",
        ],
        order_by="planned_date desc",
        limit_page_length=int(limit),
    )

    # Enrich with names
    for v in visits:
        if v.get("customer"):
            v["customer_name"] = frappe.db.get_value("Customer", v["customer"], "customer_name") or ""
        if v.get("officer"):
            v["officer_name"] = frappe.db.get_value("Employee", v["officer"], "employee_name") or ""
        if v.get("loan"):
            v["loan_applicant"] = frappe.db.get_value("Loan", v["loan"], "applicant") or ""

    return {"visits": visits}


# ---------------------------------------------------------------------------
# Create Visit
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_visit(visit_type, planned_date, customer=None, loan=None, officer=None, branch=None, notes=None):
    """Schedule a new field visit."""
    _require_visits()

    if not visit_type:
        frappe.throw(_("Visit type is required."))

    if not officer:
        officer = _current_employee()

    if not branch:
        branch = _branch()

    company = _default_company()

    doc = frappe.new_doc("LMS Field Visit")
    doc.visit_type = visit_type
    doc.customer = customer
    doc.loan = loan
    doc.officer = officer
    doc.planned_date = planned_date
    doc.branch = branch
    doc.company = company
    doc.status = "Planned"
    doc.notes = notes
    doc.flags.ignore_permissions = True
    doc.insert()

    return {"name": doc.name, "status": doc.status}


# ---------------------------------------------------------------------------
# Check-In
# ---------------------------------------------------------------------------

@frappe.whitelist()
def check_in(visit_name, latitude, longitude):
    """Geo-tagged check-in: record time and coordinates, set status to In Progress."""
    _require_visits()

    if not frappe.db.exists("LMS Field Visit", visit_name):
        frappe.throw(_("Field visit {0} not found.").format(visit_name))

    visit = frappe.get_doc("LMS Field Visit", visit_name)

    # Only the assigned officer can check in (or admin)
    if not _is_admin():
        employee = _current_employee()
        if visit.officer and visit.officer != employee:
            frappe.throw(_("Only the assigned officer can check in."), frappe.PermissionError)

    if visit.status not in ("Planned",):
        frappe.throw(_("Can only check in to a planned visit."))

    visit.check_in_time = now_datetime()
    visit.check_in_lat = str(latitude)
    visit.check_in_lon = str(longitude)
    visit.status = "In Progress"
    visit.flags.ignore_permissions = True
    visit.save()

    return {
        "name": visit.name,
        "check_in_time": str(visit.check_in_time),
        "status": visit.status,
    }


# ---------------------------------------------------------------------------
# Visit Detail & Completion
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_visit_detail(visit_name):
    """Return a single visit with checklist and notes."""
    _require_visits()

    if not frappe.db.exists("LMS Field Visit", visit_name):
        frappe.throw(_("Field visit {0} not found.").format(visit_name))

    visit = frappe.get_doc("LMS Field Visit", visit_name)

    # Branch scoping for non-admins
    if not _is_admin():
        persona = _current_persona()
        employee = _current_employee()
        if persona in ("Loan Officer", "Collector") and visit.officer and visit.officer != employee:
            frappe.throw(_("Not permitted"), frappe.PermissionError)
        elif persona == "Branch Manager" and _branch() and visit.branch and visit.branch != _branch():
            frappe.throw(_("Not permitted"), frappe.PermissionError)

    result = {
        "name": visit.name,
        "visit_type": visit.visit_type,
        "loan": visit.loan,
        "customer": visit.customer,
        "customer_name": frappe.db.get_value("Customer", visit.customer, "customer_name") if visit.customer else "",
        "officer": visit.officer,
        "officer_name": frappe.db.get_value("Employee", visit.officer, "employee_name") if visit.officer else "",
        "planned_date": str(visit.planned_date) if visit.planned_date else "",
        "check_in_time": str(visit.check_in_time) if visit.check_in_time else "",
        "check_in_lat": visit.check_in_lat,
        "check_in_lon": visit.check_in_lon,
        "status": visit.status,
        "notes": visit.notes,
        "photos": visit.photos,
        "branch": visit.branch,
        "company": visit.company,
    }

    return result


@frappe.whitelist()
def complete_visit(visit_name, notes=None, photos=None):
    """Mark a visit as completed with notes."""
    _require_visits()

    if not frappe.db.exists("LMS Field Visit", visit_name):
        frappe.throw(_("Field visit {0} not found.").format(visit_name))

    visit = frappe.get_doc("LMS Field Visit", visit_name)

    # Only the assigned officer can complete (or admin)
    if not _is_admin():
        employee = _current_employee()
        if visit.officer and visit.officer != employee:
            frappe.throw(_("Only the assigned officer can complete this visit."), frappe.PermissionError)

    if visit.status not in ("Planned", "In Progress"):
        frappe.throw(_("Can only complete a planned or in-progress visit."))

    visit.status = "Completed"
    if notes:
        visit.notes = notes
    if photos:
        visit.photos = photos
    visit.flags.ignore_permissions = True
    visit.save()

    return {"name": visit.name, "status": visit.status}


# ---------------------------------------------------------------------------
# Visit Stats
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_visit_stats():
    """Summary stats for the field visits dashboard."""
    _require_visits()

    persona = _current_persona()
    is_admin = _is_admin()
    employee = _current_employee()
    branch = _branch()

    filters = {}
    if not is_admin:
        if persona in ("Loan Officer", "Collector"):
            filters["officer"] = employee
        elif persona == "Branch Manager" and branch:
            filters["branch"] = branch

    total = frappe.db.count("LMS Field Visit", filters)
    planned = frappe.db.count("LMS Field Visit", {**filters, "status": "Planned"})
    in_progress = frappe.db.count("LMS Field Visit", {**filters, "status": "In Progress"})
    completed = frappe.db.count("LMS Field Visit", {**filters, "status": "Completed"})
    cancelled = frappe.db.count("LMS Field Visit", {**filters, "status": "Cancelled"})

    # Today's visits
    today_filters = {**filters, "planned_date": ("between", [today() + " 00:00:00", today() + " 23:59:59"])}
    today_visits = frappe.db.count("LMS Field Visit", today_filters)

    return {
        "total": total,
        "planned": planned,
        "in_progress": in_progress,
        "completed": completed,
        "cancelled": cancelled,
        "today": today_visits,
    }