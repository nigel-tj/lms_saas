# Copyright (c) 2026, lms_saas and contributors
# License: MIT

"""LMS SMS Send Log — append-only per-send audit row.

Mirrors the R22 / R20-H1 immutability posture of
``LMS Notification Log`` and ``LMS Incident Log``: writes are append-only.
Edits after insert raise ``frappe.ValidationError``; deletes are blocked
for privileged roles (System Manager / LMS Admin), and LMS Portal Staff
deletions are recorded in ``LMS Audit Event`` so a regulator can detect a
pattern of "convenient deletions" of regulatory-period delivery evidence.

Each row carries the Twilio Message SID (assigned on send), an SHA256 of
the rendered body (used for dedupe *together with* the to_number), and a
PII-safe JSON excerpt of the provider response (only ``status``, ``sid``,
``error_code``, ``price``, ``num_segments`` are kept — never the body or
the recipient).
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

LOCKED_OWNER_ROLES = frozenset({"System Manager", "LMS Admin"})


class LMSSMSSendLog(Document):
	"""Immutable per-send audit row."""

	def on_update(self):
		if not self.flags.in_insert:
			# Allow status-only mutations triggered by the status callback
			# (Delivered / Failed / Undelivered / Opted-out). The status
			# callback sets a dedicated flag we look for.
			if getattr(self.flags, "lms_sms_callback_update", False):
				return
			frappe.throw(
				"LMS SMS Send Log records are immutable. "
				"Append a new row with status='AUDIT_RETRACTED' instead."
			)

	def on_trash(self):
		# As with LMS Notification Log: privileged owner rows cannot be
		# deleted; LMS Portal Staff rows are deleted but audited.
		owner = self.owner or ""
		owner_roles = set(frappe.get_roles(owner)) if owner else set()
		if owner_roles & LOCKED_OWNER_ROLES:
			frappe.throw(
				"LMS SMS Send Log records owned by privileged roles "
				"(System Manager / LMS Admin) are immutable and cannot be "
				"deleted. Append a new row with status='AUDIT_RETRACTED'."
			)
		try:
			from lms_saas.api.compliance import write_audit_event

			write_audit_event(
				event_type="SMSSendLog:Deleted",
				reference_doctype="LMS SMS Send Log",
				reference_name=self.name,
				details=(
					f"owner={owner} to={self.to_number} status={self.status} "
					f"purpose={self.purpose} twilio_sid={self.twilio_sid or ''}"
				),
			)
		except Exception:  # noqa: BLE001
			frappe.log_error(
				title="LMS audit event failed (sms send log delete)",
				message=frappe.get_traceback(),
			)
