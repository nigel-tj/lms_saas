"""Integration API authentication."""

from __future__ import annotations

import frappe
from frappe import _


def validate_api_key():
	"""Validate X-LMS-API-Key and X-LMS-API-Secret headers; set session user."""
	api_key = frappe.get_request_header("X-LMS-API-Key")
	api_secret = frappe.get_request_header("X-LMS-API-Secret")
	if not api_key:
		return False

	row = frappe.db.get_value(
		"LMS API Key",
		{"api_key": api_key, "enabled": 1},
		["name", "user", "api_secret", "allowed_ips"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Invalid API key"), frappe.AuthenticationError)

	stored = frappe.utils.password.get_decrypted_password("LMS API Key", row.name, "api_secret")
	if stored and api_secret != stored:
		frappe.throw(_("Invalid API secret"), frappe.AuthenticationError)

	# IP allowlist check (if configured on the key)
	if row.get("allowed_ips"):
		client_ip = frappe.request.environ.get("HTTP_X_FORWARDED_FOR") or frappe.request.environ.get(
			"REMOTE_ADDR", ""
		)
		client_ip = client_ip.split(",")[0].strip() if client_ip else ""
		allowed = [ip.strip() for ip in row.allowed_ips.split(",") if ip.strip()]
		if allowed and client_ip not in allowed:
			_log_blocked_api_attempt(api_key, client_ip)
			frappe.throw(
				_("IP address {0} is not allowed for this API key").format(client_ip),
				frappe.AuthenticationError,
			)

	if row.user:
		frappe.set_user(row.user)
	return True


def _log_blocked_api_attempt(api_key, client_ip):
	"""Log blocked API attempts to the audit trail."""
	try:
		from lms_saas.api.compliance import write_audit_event

		write_audit_event(
			event_type="API:BlockedIP",
			reference_doctype="LMS API Key",
			reference_name=api_key,
			details=f"ip={client_ip}",
		)
	except Exception:
		pass
