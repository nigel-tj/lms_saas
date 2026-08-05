"""R41: widen LMS Notification Log status + channel options.

The 2026-08-05 review surfaced that the LMS Notification Log had a
binary ``Sent | Failed | Skipped`` status that did not match the real
delivery states of the underlying Frappe Email Queue. As a result the
log lied: every row said ``Sent`` even when the Email Queue ended in
``Error``, and the portal bell hid every row that wasn't ``Sent``.

This patch:

1. Extends the ``status`` Select to ``Sent | Failed | Skipped |
   Dev-Sent | Queued``. ``Dev-Sent`` is a development-sandbox
   delivery state (the local_inbox sink). ``Queued`` is the
   post-enqueue / pre-delivery state.
2. Extends the ``channel`` Select to also accept ``Bell`` (used by the
   new ``backfill_portal_notifications`` API to seed a per-loan
   notification row).

Idempotent: re-running is a no-op once the column options include the
new values.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.exists("DocType", "LMS Notification Log"):
		return
	meta = frappe.get_meta("LMS Notification Log")

	# 1. Status options
	status_field = meta.get_field("status")
	desired_status = "Sent\nFailed\nSkipped\nDev-Sent\nQueued"
	if status_field and status_field.options != desired_status:
		frappe.db.set_value(
			"Custom Field",
			{"dt": "LMS Notification Log", "fieldname": "status"},
			"options",
			desired_status,
		)
		frappe.db.sql(
			"""UPDATE `tabDocField`
			   SET options=%s
			   WHERE parent='LMS Notification Log' AND fieldname='status'""",
			desired_status,
		)
		frappe.db.sql(
			"""UPDATE `tabCustom Field`
			   SET options=%s
			   WHERE dt='LMS Notification Log' AND fieldname='status'""",
			desired_status,
		)

	# 2. Channel options
	channel_field = meta.get_field("channel")
	desired_channel = "SMS\nEmail\nToDo\nBell"
	if channel_field and channel_field.options != desired_channel:
		frappe.db.sql(
			"""UPDATE `tabDocField`
			   SET options=%s
			   WHERE parent='LMS Notification Log' AND fieldname='channel'""",
			desired_channel,
		)
		frappe.db.sql(
			"""UPDATE `tabCustom Field`
			   SET options=%s
			   WHERE dt='LMS Notification Log' AND fieldname='channel'""",
			desired_channel,
		)

	frappe.db.commit()
