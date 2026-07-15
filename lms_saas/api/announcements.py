"""Announcements addon API — list, acknowledge, create (admin only)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime

from lms_saas.utils.addons import require_addon_persona


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def _require_announcements():
    require_addon_persona("announcements")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _current_persona():
    from lms_saas.utils.portal import resolve_portal_persona, is_portal_borrower
    if is_portal_borrower():
        return "Borrower"
    return resolve_portal_persona() or "All Staff"


def _branch_for_user(user=None):
    from lms_saas.api.staff import get_current_user_branch
    if user:
        # Temporarily resolve for a different user (admin context)
        employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
        if employee:
            meta = frappe.get_meta("Employee")
            for field in ("branch", "cost_center", "custom_lms_branch"):
                if meta.has_field(field):
                    val = frappe.db.get_value("Employee", employee, field)
                    if val:
                        return val
        return None
    return get_current_user_branch()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_announcements(limit=50):
    """Return published announcements visible to the current user."""
    _require_announcements()

    persona = _current_persona()
    user_branch = _branch_for_user()

    filters = {"status": "Published"}
    announcements = frappe.get_all(
        "LMS Announcement",
        filters=filters,
        fields=["name", "title", "body", "target_persona", "target_branch",
                "publish_date", "expiry_date", "requires_acknowledgement"],
        order_by="publish_date desc",
        limit_page_length=int(limit),
    )

    now = get_datetime()
    visible = []
    for ann in announcements:
        # Expiry check
        if ann.get("expiry_date") and get_datetime(ann["expiry_date"]) < now:
            continue

        # Persona targeting
        target = ann.get("target_persona") or "All Staff"
        if target != "All Staff" and target != persona:
            continue

        # Branch targeting
        if ann.get("target_branch") and ann["target_branch"] != user_branch:
            continue

        # Check if acknowledged
        ann["acknowledged"] = _is_acknowledged(ann["name"])
        visible.append(ann)

    return {"announcements": visible}


@frappe.whitelist()
def acknowledge_announcement(announcement_name):
    """Mark an announcement as acknowledged by the current user."""
    _require_announcements()

    doc = frappe.get_doc("LMS Announcement", announcement_name)
    if doc.status != "Published":
        frappe.throw(_("Cannot acknowledge an unpublished announcement."))

    user = frappe.session.user
    # Check if already acknowledged
    for row in (doc.acknowledged_by or []):
        if row.user == user:
            return {"ok": True, "already_acknowledged": True}

    doc.append("acknowledged_by", {
        "user": user,
        "acknowledged_on": now_datetime(),
    })
    doc.flags.ignore_permissions = True
    doc.save()
    return {"ok": True}


@frappe.whitelist()
def create_announcement(title, body, target_persona="All Staff", target_branch=None,
                         requires_acknowledgement=False, expiry_date=None):
    """Admin-only: create and publish a new announcement."""
    _require_announcements()
    if not _is_admin():
        frappe.throw(_("Only administrators can create announcements."), frappe.PermissionError)

    doc = frappe.new_doc("LMS Announcement")
    doc.title = title
    doc.body = body
    doc.target_persona = target_persona
    doc.target_branch = target_branch
    doc.requires_acknowledgement = bool(requires_acknowledgement)
    doc.expiry_date = expiry_date
    doc.status = "Published"
    doc.publish_date = now_datetime()
    doc.flags.ignore_permissions = True
    doc.insert()

    return {"name": doc.name, "title": doc.title}


@frappe.whitelist()
def archive_announcement(announcement_name):
    """Admin-only: archive an announcement."""
    _require_announcements()
    if not _is_admin():
        frappe.throw(_("Only administrators can archive announcements."), frappe.PermissionError)

    frappe.db.set_value("LMS Announcement", announcement_name, "status", "Archived")
    return {"ok": True}


@frappe.whitelist()
def get_announcement_stats():
    """Admin: overview of announcement activity."""
    _require_announcements()
    if not _is_admin():
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    total = frappe.db.count("LMS Announcement")
    published = frappe.db.count("LMS Announcement", {"status": "Published"})
    draft = frappe.db.count("LMS Announcement", {"status": "Draft"})
    archived = frappe.db.count("LMS Announcement", {"status": "Archived"})

    # Acknowledgement rate
    ack_count = frappe.db.count("LMS Announcement Acknowledgement")

    return {
        "total": total,
        "published": published,
        "draft": draft,
        "archived": archived,
        "total_acknowledgements": ack_count,
    }


def _is_acknowledged(announcement_name):
    user = frappe.session.user
    return bool(frappe.db.exists(
        "LMS Announcement Acknowledgement",
        {"parent": announcement_name, "parenttype": "LMS Announcement", "user": user},
    ))