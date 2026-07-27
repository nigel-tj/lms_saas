"""Health-check / ping endpoints for the LMS portal.

R18-7: the field-collection PWA used to rely on ``navigator.onLine`` to
show an "Online — changes sync immediately" pill. On a 1-bar GPRS link
that flag is true but every API call hangs. This module exposes a real
heartbeat endpoint the PWA can poll to decide whether the network path
to the LMS server is actually usable.
"""

from __future__ import annotations

import time

import frappe
from frappe.utils import now_datetime


@frappe.whitelist(allow_guest=True)
def ping():
	"""Cheap heartbeat endpoint. Returns the current server time.

	Used by the field-collection PWA to decide whether the network path to
	the LMS server is actually usable (versus ``navigator.onLine`` which
	only reflects the OS link state). The endpoint is intentionally
	allow_guest so a logged-out collector can still get a quick answer
	when troubleshooting; it leaks no PII.
	"""
	return {
		"ok": True,
		"server_time": now_datetime().isoformat(),
		"epoch_ms": int(time.time() * 1000),
	}


@frappe.whitelist()
def authed_ping():
	"""Same as ``ping`` but requires a logged-in session.

	Used when the PWA wants to verify the user's session is still alive
	before submitting a repayment. The body is identical to ``ping``; the
	session check is the value.
	"""
	if frappe.session.user == "Guest":
		frappe.throw("Not authenticated", frappe.PermissionError)
	return {
		"ok": True,
		"user": frappe.session.user,
		"server_time": now_datetime().isoformat(),
		"epoch_ms": int(time.time() * 1000),
	}
