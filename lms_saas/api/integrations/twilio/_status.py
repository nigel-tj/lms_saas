"""Twilio status callback handler.

Twilio POSTs the delivery receipt here when a status-callback URL is
configured. Each receipt carries:
    MessageSid, MessageStatus, ErrorCode, ErrorMessage, Price, ...

We map the status back to the LMS SMS Send Log row via ``twilio_sid``.
The mutation is allowed by the controller via a dedicated flag.
"""

from __future__ import annotations

from typing import Any

import frappe


# Twilio's MessageStatus values mapped to our enum.
_STATUS_MAP = {
	"accepted": "Sent",
	"queued": "Sent",
	"sending": "Sent",
	"sent": "Sent",
	"failed": "Failed",
	"undelivered": "Undelivered",
	"delivered": "Delivered",
	"read": "Delivered",
	"canceled": "Failed",
}

# Twilio error codes that mean "recipient opted out / blocked our number".
# Only those — not generic delivery errors — flip the row to Opted-out.
_OPTOUT_ERROR_CODES = frozenset({"21610", "30003"})


def _map_status(message_status: str | None, error_code: str | None) -> str:
	# Special-case: opt-out is a domain concept, not a Twilio status, so
	# it must beat the generic mapping.
	if error_code in _OPTOUT_ERROR_CODES:
		return "Opted-out"
	if (message_status or "").lower() == "delivered":
		return "Delivered"
	return _STATUS_MAP.get((message_status or "").lower(), "Sent")


def _safe_int(value, default=None):
	try:
		return int(value)
	except (TypeError, ValueError):
		return default


def handle_status_callback(payload: dict[str, Any]) -> dict[str, Any]:
	"""Apply a Twilio status callback to the matching LMS SMS Send Log.

	Returns ``{matched: bool, send_log: name|None, status: status|None}``.
	"""
	sid = (payload.get("MessageSid") or "").strip()
	if not sid:
		return {"matched": False, "send_log": None, "status": None}

	message_status = payload.get("MessageStatus")
	error_code = payload.get("ErrorCode")
	new_status = _map_status(message_status, error_code)

	# Guard: DocType not yet migrated (cold install) — never crash the
	# webhook receiver with a noisy MySQL traceback.
	if not frappe.db.table_exists("LMS SMS Send Log"):
		return {"matched": False, "send_log": None, "status": new_status}

	if not frappe.db.exists("LMS SMS Send Log", {"twilio_sid": sid}):
		return {"matched": False, "send_log": None, "status": new_status}

	name = frappe.db.get_value(
		"LMS SMS Send Log", {"twilio_sid": sid}, "name"
	)

	update = {
		"status": new_status,
	}
	now = frappe.utils.now_datetime()
	if new_status == "Delivered":
		update["delivered_at"] = now
	elif new_status in ("Failed", "Undelivered", "Opted-out"):
		update["failed_at"] = now
	if error_code:
		update["error_code"] = str(error_code)
	if payload.get("Price") not in (None, "", "0", "0.0"):
		update["cost"] = payload["Price"]

	# Use the controller-bypass flag so the append-only guard accepts the
	# callback-driven transition.
	frappe.db.set_value(
		"LMS SMS Send Log",
		name,
		update,
		update_modified=False,
	)
	# Reload + db_update with flag for safety on unusual cases.
	doc = frappe.get_doc("LMS SMS Send Log", name)
	doc.flags.lms_sms_callback_update = True
	for k, v in update.items():
		doc.set(k, v)
	doc.db_update()

	return {"matched": True, "send_log": name, "status": new_status}
