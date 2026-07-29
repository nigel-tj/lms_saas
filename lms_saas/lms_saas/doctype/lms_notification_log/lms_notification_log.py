# Copyright (c) 2026, lms_saas and contributors
# License: MIT

"""LMS Notification Log controller.

R22-High: hardened to append-only for the regulator-facing surface.
Notification logs are an internal audit trail ("what did this collector
get notified of?") rather than regulator evidence per se, so the
immutability posture is slightly softer than the audit / PII / incident
logs: System Manager can still delete LMS Portal Staff rows for routine
data hygiene, but the controller's on_trash records the deletion in
``LMS Audit Event`` so the operator can detect a pattern of
"convenient deletions" of regulatory-period notification evidence.

For rows owned by privileged roles (System Manager, LMS Admin), the
controller hard-throws on delete — the regulator-facing evidence is
truly append-only.
"""

import frappe
from frappe.model.document import Document

# Roles whose notification log rows are regulator-facing. Deleting rows
# owned by these roles is forbidden so the regulator can request "show me
# every notification the compliance officer received in Q3" with
# confidence the rows still exist.
LOCKED_OWNER_ROLES = frozenset({"System Manager", "LMS Admin"})


class LMSNotificationLog(Document):
	"""Notification delivery audit row.

	Use the standard Frappe notification runner. Never edit rows in place
	(``on_update`` will throw after insert). Deletion of rows owned by
	privileged roles is forbidden; deletion of LMS Portal Staff rows is
	allowed but audited.
	"""

	def on_update(self):
		if not self.flags.in_insert:
			frappe.throw(
				"LMS Notification Log records are immutable. "
				"Append a new row with status='AUDIT_RETRACTED' instead."
			)

	def on_trash(self):
		# R22-High: forbid deletion of rows owned by privileged roles.
		# LMS Portal Staff rows may be deleted for routine hygiene, but
		# the deletion is itself logged as an audit event so a regulator
		# can detect patterns of convenient deletions.
		owner = self.owner or ""
		owner_roles = set(frappe.get_roles(owner)) if owner else set()
		if owner_roles & LOCKED_OWNER_ROLES:
			frappe.throw(
				"LMS Notification Log records owned by privileged roles "
				"(System Manager / LMS Admin) are immutable and cannot be "
				"deleted. If a row must be retracted, append a new "
				"LMS Notification Log with status='AUDIT_RETRACTED' instead."
			)
		# LMS Portal Staff row: log the deletion but allow it.
		try:
			from lms_saas.api.compliance import write_audit_event

			write_audit_event(
				event_type="NotificationLog:Deleted",
				reference_doctype="LMS Notification Log",
				reference_name=self.name,
				details=(
					f"owner={owner} reminder_type={self.reminder_type} "
					f"reference_doctype={self.reference_doctype} "
					f"reference_name={self.reference_name}"
				),
			)
		except Exception:
			frappe.log_error(
				title="LMS audit event failed (notification log delete)",
				message=frappe.get_traceback(),
			)
