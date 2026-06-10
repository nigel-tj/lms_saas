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
		["name", "user", "api_secret"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Invalid API key"), frappe.AuthenticationError)

	stored = frappe.utils.password.get_decrypted_password("LMS API Key", row.name, "api_secret")
	if stored and api_secret != stored:
		frappe.throw(_("Invalid API secret"), frappe.AuthenticationError)

	if row.user:
		frappe.set_user(row.user)
	return True
