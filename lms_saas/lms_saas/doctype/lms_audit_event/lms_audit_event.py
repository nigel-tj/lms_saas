import frappe
from frappe.model.document import Document


class LMSAuditEvent(Document):
    """Append-only audit event. Records are immutable once created."""

    def on_update(self):
        if not self.flags.in_insert:
            frappe.throw("LMS Audit Event records are immutable and cannot be modified.")

    def on_trash(self):
        if "System Manager" not in frappe.get_roles(frappe.session.user):
            frappe.throw("LMS Audit Event records cannot be deleted.")
