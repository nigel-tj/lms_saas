"""Task Management addon API — Kanban board, loan-linked tasks, projects.

Reuses ERPNext ``Task`` and ``Project`` doctypes. Tasks are branch-scoped
via Cost Center on the linked Project or via custom_lms_branch on the task
reference (Loan / Customer).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime, today, getdate

from lms_saas.utils.addons import require_addon_persona


def _require_tasks():
    require_addon_persona("task_management")


def _current_employee():
    user = frappe.session.user
    return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def _branch():
    from lms_saas.api.staff import get_current_user_branch
    return get_current_user_branch()


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_task_board(project=None):
    """Return tasks grouped by status (Kanban columns)."""
    _require_tasks()

    filters = {}
    if project:
        filters["project"] = project

    # Branch scoping: tasks linked to loans in the user's branch via project
    branch = _branch()
    if branch and not frappe.db.get_value("Has Role", {"parent": frappe.session.user, "role": "System Manager"}):
        # Filter by tasks whose project is in the branch, or all if no branch filter
        branch_projects = frappe.get_all("Project", filters={"cost_center": branch}, pluck="name")
        if branch_projects:
            filters["project"] = ("in", branch_projects)
        # If no branch projects, don't filter — show all tasks

    tasks = frappe.get_all(
        "Task",
        filters=filters,
        fields=["name", "subject", "status", "priority", "exp_start_date",
                "exp_end_date", "project", "issue", "_assign"],
        order_by="creation desc",
        limit_page_length=200,
    )

    columns = [
        {"key": "Open", "label": "To Do"},
        {"key": "Working", "label": "In Progress"},
        {"key": "Pending Review", "label": "Review"},
        {"key": "Completed", "label": "Done"},
        {"key": "Cancelled", "label": "Cancelled"},
    ]

    board = {col["key"]: [] for col in columns}
    today_date = getdate(today())
    for task in tasks:
        # Parse _assign (JSON array of users)
        assignee = task.get("_assign")
        if assignee:
            try:
                import json
                assigns = json.loads(assignee)
                task["assignee"] = assigns[0] if assigns else None
            except Exception:
                task["assignee"] = None
        else:
            task["assignee"] = None

        status = task.get("status") or "Open"
        # Overdue visual: keep column by status (To Do / Working) but flag the card
        # so the Overdue KPI matches what users see on the board (B-21).
        end = task.get("exp_end_date")
        task["is_overdue"] = bool(
            end
            and status not in ("Completed", "Cancelled")
            and getdate(end) < today_date
        )
        if status not in board:
            status = "Open"
        board[status].append(task)

    return {
        "columns": columns,
        "board": board,
        "total": len(tasks),
    }


def _empty_board():
    columns = [
        {"key": "Open", "label": "To Do"},
        {"key": "Working", "label": "In Progress"},
        {"key": "Pending Review", "label": "Review"},
        {"key": "Completed", "label": "Done"},
        {"key": "Cancelled", "label": "Cancelled"},
    ]
    return {"columns": columns, "board": {c["key"]: [] for c in columns}, "total": 0}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_task(subject, description=None, priority="Medium", project=None,
                 reference_type=None, reference_name=None, exp_end_date=None,
                 assigned_to=None):
    """Create a new task."""
    _require_tasks()

    task = frappe.new_doc("Task")
    task.subject = subject
    task.description = description or ""
    task.priority = priority
    task.project = project
    # Store reference as issue if reference_type is Loan (not native to Task)
    if reference_type == "Issue" and reference_name:
        task.issue = reference_name
    task.exp_start_date = today()
    if exp_end_date:
        task.exp_end_date = exp_end_date
    task.status = "Open"
    task.flags.ignore_permissions = True
    task.insert()

    if assigned_to:
        frappe.db.set_value("Task", task.name, "_assign", f'["{assigned_to}"]')

    return {"name": task.name, "subject": task.subject}


@frappe.whitelist()
def update_task_status(task_name, status):
    """Move a task to a new status (Kanban drag)."""
    _require_tasks()

    valid = {"Open", "Working", "Pending Review", "Completed", "Cancelled"}
    if status not in valid:
        frappe.throw(_("Invalid status: {0}").format(status))

    frappe.db.set_value("Task", task_name, "status", status)
    if status == "Completed":
        frappe.db.set_value("Task", task_name, "completed_on", now_datetime())

    return {"ok": True, "status": status}


@frappe.whitelist()
def get_task_detail(task_name):
    """Return a single task with comments."""
    _require_tasks()

    task = frappe.get_doc("Task", task_name)
    comments = frappe.get_all(
        "Comment",
        filters={"reference_doctype": "Task", "reference_name": task_name},
        fields=["name", "content", "comment_by", "creation"],
        order_by="creation desc",
        limit=50,
    )

    return {
        "task": {
            "name": task.name,
            "subject": task.subject,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "project": task.project,
            "issue": task.issue,
            "exp_start_date": task.exp_start_date,
            "exp_end_date": task.exp_end_date,
        },
        "comments": comments,
    }


@frappe.whitelist()
def add_comment(task_name, content):
    """Add a comment to a task."""
    _require_tasks()

    comment = frappe.new_doc("Comment")
    comment.comment_type = "Comment"
    comment.reference_doctype = "Task"
    comment.reference_name = task_name
    comment.content = content
    comment.comment_by = frappe.session.user
    comment.flags.ignore_permissions = True
    comment.insert()

    return {"ok": True, "comment_name": comment.name}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_projects():
    """Return all projects (for the project filter dropdown)."""
    _require_tasks()

    projects = frappe.get_all(
        "Project",
        filters={"status": "Open"},
        fields=["name", "project_name", "status"],
        order_by="project_name asc",
        limit=100,
    )
    return {"projects": projects}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_task_stats():
    """Overview stats for the task board header."""
    _require_tasks()

    total = frappe.db.count("Task")
    open_count = frappe.db.count("Task", {"status": "Open"})
    working = frappe.db.count("Task", {"status": "Working"})
    review = frappe.db.count("Task", {"status": "Pending Review"})
    done = frappe.db.count("Task", {"status": "Completed"})
    overdue = frappe.db.count("Task", {
        "status": ("not in", ["Completed", "Cancelled"]),
        "exp_end_date": ("<", today()),
    })

    return {
        "total": total,
        "open": open_count,
        "in_progress": working,
        "review": review,
        "completed": done,
        "overdue": overdue,
    }