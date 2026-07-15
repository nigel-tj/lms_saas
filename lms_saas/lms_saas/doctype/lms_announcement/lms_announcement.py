"""LMS Announcement doctype — internal communication for portal staff and borrowers."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, get_datetime


class LMSAnnouncement(Document):
	pass


def validate(doc, method=None):
    """Ensure published announcements have a publish date."""
    if doc.status == "Published" and not doc.publish_date:
        doc.publish_date = now_datetime()

    if doc.expiry_date and doc.publish_date:
        if get_datetime(doc.expiry_date) < get_datetime(doc.publish_date):
            frappe.throw(_("Expiry date cannot be before publish date."))


def on_update(doc, method=None):
    """Notify targeted users when an announcement is published."""
    if doc.status != "Published":
        return
    # Only notify on the Draft → Published transition.
    if doc.has_value_changed("status") and doc.get_doc_before_save() and doc.get_doc_before_save().status == "Published":
        return

    _notify_targeted_users(doc)


def _notify_targeted_users(doc):
    """Create Notification Log entries for users matching the target persona/branch."""
    from lms_saas.utils.portal import resolve_portal_persona, is_portal_borrower

    target = doc.target_persona or "All Staff"
    users = []

    # Gather candidate users
    if target == "Borrower":
        users = [
            u.name for u in frappe.get_all("User", filters={"enabled": 1}, pluck="name")
            if u not in ("Administrator", "Guest") and is_portal_borrower(u)
        ]
    else:
        # Staff users
        from lms_saas.install import PORTAL_STAFF_ROLE

        staff_users = frappe.get_all(
            "Has Role",
            filters={"role": PORTAL_STAFF_ROLE, "parenttype": "User"},
            pluck="parent",
        )
        admin_users = frappe.get_all(
            "Has Role",
            filters={"role": "System Manager", "parenttype": "User"},
            pluck="parent",
        )
        candidates = set(staff_users + admin_users) - {"Administrator", "Guest"}

        for user in candidates:
            if target == "All Staff":
                users.append(user)
            else:
                persona = resolve_portal_persona(user)
                if persona == target:
                    users.append(user)

    # Branch filter
    if doc.target_branch:
        from lms_saas.api.staff import get_current_user_branch
        users = [u for u in users if get_current_user_branch(u) == doc.target_branch]

    subject = _("New announcement: {0}").format(doc.title)
    for user in users[:200]:  # cap to avoid overload
        try:
            frappe.get_doc(
                {
                    "doctype": "Notification Log",
                    "type": "Alert",
                    "document_type": "LMS Announcement",
                    "document_name": doc.name,
                    "subject": subject,
                    "email_content": doc.title,
                    "for_user": user,
                }
            ).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(title="LMS announcement notification failed", message=frappe.get_traceback())