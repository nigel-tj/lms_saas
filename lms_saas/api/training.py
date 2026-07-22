"""Training addon API — programs, events, registration, feedback, results.

Reuses HRMS doctypes: Training Program, Training Event, Training Feedback,
Training Result, Employee.
Branch-scoped via Employee → Branch / Cost Center.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today, getdate, now_datetime

from lms_saas.utils.addons import require_addon_persona


def _require_training():
    require_addon_persona("training")


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


def _has_table(doctype: str) -> bool:
    """True if a Frappe table exists for the DocType.

    ``frappe.db.table_exists`` expects the DocType name (it prefixes ``tab``
    itself). Passing ``tabTraining Program`` incorrectly looks for
    ``tabtabTraining Program`` and always returns False.
    """
    try:
        name = (doctype or "").strip()
        if name.startswith("tab"):
            name = name[3:]
        return bool(name and frappe.db.table_exists(name))
    except Exception:
        return False


def _missing_doctype_response(doctype: str) -> dict:
    """Empty-but-valid response for a missing doctype so the front-end can
    render an empty state instead of an infinite loading spinner."""
    return {
        "_missing": True,
        "_missing_doctype": doctype,
        "message": _(
            "The {0} module is not ready on this site "
            "(DocType exists but database tables are missing, or HRMS Training is not synced). "
            "Ask a System Manager to run a standard bench migrate after installing HRMS."
        ).format(doctype),
        "programs": [],
        "events": [],
    }


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_training_programs(limit=50):
    """List available training programs."""
    _require_training()

    if not _has_table("Training Program"):
        return _missing_doctype_response("Training Program")

    meta = frappe.get_meta("Training Program")
    wanted = ["name", "creation", "owner"]
    for field in ("program_name", "training_program", "description", "status"):
        if meta.has_field(field):
            wanted.append(field)

    try:
        programs = frappe.get_all(
            "Training Program",
            filters={"docstatus": ["!=", 2]} if meta.has_field("docstatus") else {},
            fields=wanted,
            order_by="creation desc",
            limit_page_length=int(limit),
        )
    except Exception:
        frappe.log_error(title="LMS training programs query failed", message=frappe.get_traceback())
        return _missing_doctype_response("Training Program")

    for p in programs:
        if not p.get("program_name"):
            p["program_name"] = p.get("training_program") or p.get("name")
    return {"programs": programs}


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_training_events(upcoming=True, limit=50):
    """Return upcoming (or all) training events."""
    _require_training()

    if not _has_table("Training Event"):
        return _missing_doctype_response("Training Event")

    emeta = frappe.get_meta("Training Event")
    filters = {}
    if emeta.has_field("docstatus"):
        filters["docstatus"] = ["!=", 2]
    if upcoming and emeta.has_field("start_time"):
        filters["start_time"] = [">=", today()]

    wanted = ["name", "creation"]
    for field in (
        "event_name",
        "training_program",
        "start_time",
        "end_time",
        "location",
        "event_status",
        "status",
        "introduction",
        "trainer_name",
        "trainer_email",
    ):
        if emeta.has_field(field):
            wanted.append(field)

    order = "start_time asc" if emeta.has_field("start_time") else "creation desc"
    try:
        events = frappe.get_all(
            "Training Event",
            filters=filters,
            fields=wanted,
            order_by=order,
            limit_page_length=int(limit),
        )
    except Exception:
        frappe.log_error(title="LMS training events query failed", message=frappe.get_traceback())
        return _missing_doctype_response("Training Event")

    for ev in events:
        if not ev.get("event_status") and ev.get("status"):
            ev["event_status"] = ev.get("status")
        if not ev.get("status") and ev.get("event_status"):
            ev["status"] = ev.get("event_status")

    # Attach registration counts (only if the child table exists)
    if events and _has_table("Training Event Employee"):
        for ev in events:
            ev["registered_count"] = frappe.db.count("Training Event Employee", {
                "parent": ev["name"],
            })
    else:
        for ev in events:
            ev["registered_count"] = 0

    return {"events": events}


@frappe.whitelist()
def register_for_event(event_name):
    """Register the current employee for a training event."""
    _require_training()

    employee = _current_employee()
    if not employee:
        frappe.throw(_("No active employee linked to your account."), frappe.PermissionError)

    doc = frappe.get_doc("Training Event", event_name)
    if doc.docstatus == 2:
        frappe.throw(_("This training event is cancelled."))

    # Check if already registered
    for row in (doc.employees or []):
        if row.employee == employee:
            return {"ok": True, "already_registered": True}

    doc.append("employees", {
        "employee": employee,
        "status": "Open",
        "attendance": "Mandatory",
    })
    doc.flags.ignore_permissions = True
    doc.save()
    return {"ok": True, "event": event_name}


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_training_feedback(event_name):
    """Submit or retrieve training feedback for the current employee."""
    _require_training()

    employee = _current_employee()
    if not employee:
        frappe.throw(_("No active employee linked to your account."), frappe.PermissionError)

    # Check if feedback already exists
    existing = frappe.get_all(
        "Training Feedback",
        filters={"training_event": event_name, "employee": employee},
        fields=["name", "feedback", "rating", "date"],
        limit=1,
    )
    if existing:
        return {"feedback": existing[0], "already_submitted": True}

    return {"feedback": None, "already_submitted": False}


@frappe.whitelist()
def submit_training_feedback(event_name, feedback, rating=3):
    """Submit training feedback for the current employee."""
    _require_training()

    employee = _current_employee()
    if not employee:
        frappe.throw(_("No active employee linked to your account."), frappe.PermissionError)

    # Check if already submitted
    existing = frappe.db.exists("Training Feedback", {
        "training_event": event_name,
        "employee": employee,
    })
    if existing:
        frappe.throw(_("You have already submitted feedback for this event."))

    doc = frappe.new_doc("Training Feedback")
    doc.training_event = event_name
    doc.employee = employee
    doc.feedback = feedback
    doc.rating = int(rating)
    doc.date = today()
    doc.flags.ignore_permissions = True
    doc.insert()
    return {"ok": True, "name": doc.name}


# ---------------------------------------------------------------------------
# My Training Results
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_my_training_results():
    """View training results for the current employee."""
    _require_training()

    if not _has_table("Training Result"):
        return _missing_doctype_response("Training Result")

    employee = _current_employee()
    if not employee:
        return {"results": []}

    results = frappe.get_all(
        "Training Result",
        filters={"employee": employee},
        fields=["name", "training_event", "employee", "employee_name",
                "status", "result", "score", "posting_date"],
        order_by="posting_date desc",
        limit=50,
    )
    return {"results": results}