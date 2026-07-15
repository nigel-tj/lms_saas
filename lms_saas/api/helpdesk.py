"""Helpdesk addon API — borrower ticket system using ERPNext Issue doctype.

Borrowers submit tickets; officers/collectors handle them; managers oversee.
Customer complaints auto-create LMS Incident Log entries for RBZ reporting.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime, today, getdate, add_days

from lms_saas.utils.addons import require_addon_persona


def _require_helpdesk():
    require_addon_persona("helpdesk")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _current_persona():
    from lms_saas.utils.portal import resolve_portal_persona, is_portal_borrower
    if is_portal_borrower():
        return "Borrower"
    return resolve_portal_persona() or "Staff"


def _customer_for_user():
    """Resolve the Customer linked to the current user (for borrower tickets)."""
    from lms_saas.permissions import _portal_customer
    return _portal_customer(frappe.session.user)


# ---------------------------------------------------------------------------
# Borrower endpoints
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_my_tickets(limit=50):
    """Borrower: return tickets submitted by this user."""
    _require_helpdesk()

    customer = _customer_for_user()
    if not customer:
        return {"tickets": []}

    tickets = frappe.get_all(
        "Issue",
        filters={"raised_by": frappe.session.user},
        fields=["name", "subject", "description", "status", "priority",
                "opening_date", "resolution_date", "response_by", "sla_resolution_by"],
        order_by="opening_date desc",
        limit_page_length=int(limit),
    )
    return {"tickets": tickets}


@frappe.whitelist()
def create_ticket(subject, description, priority="Medium", issue_type=None):
    """Borrower: submit a new support ticket."""
    _require_helpdesk()

    customer = _customer_for_user()
    if not customer:
        frappe.throw(_("No borrower profile linked to your account."), frappe.PermissionError)

    issue = frappe.new_doc("Issue")
    issue.subject = subject
    issue.description = description
    issue.raised_by = frappe.session.user
    issue.priority = priority
    issue.customer = customer
    if issue_type:
        issue.issue_type = issue_type
    issue.flags.ignore_permissions = True
    issue.insert()

    # Auto-create LMS Incident Log for complaints
    if issue_type and "complaint" in str(issue_type).lower():
        _create_complaint_incident(issue, customer)

    return {"name": issue.name, "subject": issue.subject}


# ---------------------------------------------------------------------------
# Staff endpoints
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_ticket_queue(status=None, limit=100):
    """Staff: return the ticket queue (branch-scoped for non-admins)."""
    _require_helpdesk()

    filters = {}
    if status:
        filters["status"] = status

    if not _is_admin():
        # Branch scoping via customer's custom_lms_branch
        from lms_saas.api.staff import get_current_user_branch
        branch = get_current_user_branch()
        if branch:
            branch_customers = frappe.get_all("Customer", filters={"custom_lms_branch": branch}, pluck="name")
            if branch_customers:
                filters["customer"] = ("in", branch_customers)

    tickets = frappe.get_all(
        "Issue",
        filters=filters,
        fields=["name", "subject", "status", "priority", "raised_by",
                "customer", "opening_date", "response_by", "sla_resolution_by",
                "issue_type"],
        order_by="priority desc, opening_date desc",
        limit_page_length=int(limit),
    )
    return {"tickets": tickets}


@frappe.whitelist()
def get_ticket_detail(ticket_name):
    """Staff: return a single ticket with communications."""
    _require_helpdesk()

    ticket = frappe.get_doc("Issue", ticket_name)
    communications = frappe.get_all(
        "Communication",
        filters={"reference_doctype": "Issue", "reference_name": ticket_name},
        fields=["name", "content", "sender", "creation", "communication_type"],
        order_by="creation asc",
        limit=100,
    )

    return {
        "ticket": {
            "name": ticket.name,
            "subject": ticket.subject,
            "description": ticket.description,
            "status": ticket.status,
            "priority": ticket.priority,
            "raised_by": ticket.raised_by,
            "customer": ticket.customer,
            "opening_date": ticket.opening_date,
            "resolution_date": ticket.resolution_date,
            "resolution_details": ticket.resolution_details,
            "issue_type": ticket.issue_type,
        },
        "communications": communications,
    }


@frappe.whitelist()
def update_ticket_status(ticket_name, status, resolution_details=None):
    """Staff: update ticket status."""
    _require_helpdesk()

    updates = {"status": status}
    if status == "Closed" and resolution_details:
        updates["resolution_details"] = resolution_details
        updates["resolution_date"] = now_datetime()

    frappe.db.set_value("Issue", ticket_name, updates)
    return {"ok": True, "status": status}


@frappe.whitelist()
def reply_to_ticket(ticket_name, content):
    """Staff: add a reply to a ticket."""
    _require_helpdesk()

    comm = frappe.new_doc("Communication")
    comm.communication_type = "Comment"
    comm.reference_doctype = "Issue"
    comm.reference_name = ticket_name
    comm.content = content
    comm.sender = frappe.session.user
    comm.flags.ignore_permissions = True
    comm.insert()

    return {"ok": True, "communication_name": comm.name}


@frappe.whitelist()
def get_ticket_stats():
    """Staff: overview stats."""
    _require_helpdesk()

    total = frappe.db.count("Issue")
    open_count = frappe.db.count("Issue", {"status": "Open"})
    replied = frappe.db.count("Issue", {"status": "Replied"})
    closed = frappe.db.count("Issue", {"status": "Closed"})
    complaints = frappe.db.count("Issue", {"issue_type": "Complaint"})

    return {
        "total": total,
        "open": open_count,
        "replied": replied,
        "closed": closed,
        "complaints": complaints,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_complaint_incident(issue, customer):
    """Auto-create an LMS Incident Log entry for customer complaints (RBZ 5.1)."""
    try:
        frappe.get_doc({
            "doctype": "LMS Incident Log",
            "title": f"Customer complaint: {issue.subject}",
            "incident_type": "Customer Complaint",
            "severity": "Medium",
            "status": "Open",
            "reported_on": now_datetime(),
            "reference_doctype": "Issue",
            "reference_name": issue.name,
            "description": issue.description or "",
        }).insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(title="LMS complaint incident creation failed", message=frappe.get_traceback())