import frappe
from frappe.model.document import Document


class LMSAuditEvent(Document):
	"""Append-only audit event. Records are immutable once created.

	R20-H1: System Manager can no longer edit or delete audit rows. The
	DocType permission block has been tightened to read + create + export
	only; this controller hardens the server-side by throwing even if a
	permission regression accidentally grants write/delete again. The audit
	trail is the regulator's first ask — there is no business case for
	mutating it.
	"""

	def on_update(self):
		if not self.flags.in_insert:
			frappe.throw("LMS Audit Event records are immutable and cannot be modified.")

	def on_trash(self):
		# Hard fail even for System Manager — see R20-H1.
		frappe.throw(
			"LMS Audit Event records are immutable and cannot be deleted. "
			"If a row must be retracted for legal reasons, append a "
			"LMS Audit Event with event_type='AUDIT_RET RACTED' instead."
		)

	def before_insert(self):
		# Re-hash to defend against a tamper attempt that bypassed on_update.
		# The hash is recomputed here from the canonical payload fields, so
		# an attacker who managed to flip custom_event_hash pre-commit gets
		# overwritten on insert.
		import hashlib

		op_mode = (self.custom_operator_mode or "")
		licence = (self.custom_operator_licence_number or "")
		canonical = (
			f"{self.event_type}|{self.reference_doctype or ''}|{self.reference_name or ''}|"
			f"{self.amount or ''}|{self.company or ''}|{self.owner or frappe.session.user}|{licence}"
		)
		self.custom_event_hash = hashlib.sha256(canonical.encode()).hexdigest()
