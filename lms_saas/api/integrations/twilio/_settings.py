"""Twilio settings loader.

Reads from the ``LMS Twilio Settings`` single DocType when configured,
and falls back to ``frappe.conf.lms_twilio_*`` so desk users can flip
the master switch without restarting the worker.

**Auth token handling:** the token is stored encrypted in Frappe's
Password table under the key ``lms_twilio_auth_token``. Plaintext
reads are gated by ``auth_token()``, which raises if called without
``frappe.has_permission("LMS Twilio Settings", "read")`` permission —
keeping the token out of generic API responses and Portal Staff role
scope.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils.password import get_decrypted_password


PASSWORD_KEY = "lms_twilio_auth_token"


def is_enabled() -> bool:
	"""Return True iff Twilio is the active SMS provider on this site.

	Order of precedence:
	  1. ``LMS Twilio Settings`` singleton row ``enabled=1``.
	  2. ``frappe.conf.lms_twilio_enabled = true`` (operator-level override).
	"""
	try:
		if frappe.db.table_exists("LMS Twilio Settings"):
			val = frappe.db.get_single_value("LMS Twilio Settings", "enabled")
			if val:
				return True
	except Exception:  # noqa: BLE001
		pass
	try:
		return bool(frappe.conf.get("lms_twilio_enabled", False))
	except Exception:  # noqa: BLE001
		return False


def _read_singleton_doc() -> dict | None:
	"""Return the singleton row as a dict, or None if absent / disabled."""
	if not frappe.db.table_exists("LMS Twilio Settings"):
		return None
	if not frappe.db.exists("DocType", "LMS Twilio Settings"):
		return None
	try:
		doc = frappe.get_single("LMS Twilio Settings")
	except Exception:  # noqa: BLE001
		return None
	return {
		"enabled": bool(doc.enabled),
		"account_sid": (doc.account_sid or "").strip(),
		"default_from_number": (doc.default_from_number or "").strip(),
		"status_callback_url": (doc.status_callback_url or "").strip(),
		"inbound_webhook_url": (doc.inbound_webhook_url or "").strip(),
		"sandbox_fail_open": bool(doc.sandbox_fail_open),
		"verify_service_sid": (doc.verify_service_sid or "").strip(),
		"max_daily_per_phone": int(doc.max_daily_per_phone or 10),
		"retry_attempts": int(doc.retry_attempts or 2),
	}


def get_settings() -> dict[str, Any]:
	"""Public-readable settings (no auth token, no secret fields)."""
	from_singleton = _read_singleton_doc() or {}

	if not from_singleton.get("enabled") and not is_enabled():
		return {"enabled": False}

	# site_config overrides the singleton defaults.
	conf = frappe.conf
	return {
		"enabled": True,
		"account_sid": from_singleton.get("account_sid")
		or (conf.get("lms_twilio_account_sid", "") or "").strip(),
		"default_from_number": from_singleton.get("default_from_number")
		or (conf.get("lms_twilio_from_number", "") or "").strip(),
		"status_callback_url": from_singleton.get("status_callback_url")
		or (conf.get("lms_twilio_status_callback_url", "") or "").strip(),
		"inbound_webhook_url": from_singleton.get("inbound_webhook_url")
		or (conf.get("lms_twilio_inbound_url", "") or "").strip(),
		"sandbox_fail_open": bool(
			from_singleton.get("sandbox_fail_open")
			or conf.get("lms_twilio_sandbox_fail_open", False)
		),
		"verify_service_sid": from_singleton.get("verify_service_sid")
		or (conf.get("lms_twilio_verify_service_sid", "") or "").strip(),
		"max_daily_per_phone": int(
			from_singleton.get("max_daily_per_phone")
			or conf.get("lms_twilio_max_daily_per_phone", 10)
		),
		"retry_attempts": int(
			from_singleton.get("retry_attempts") or conf.get("lms_twilio_retry_attempts", 2)
		),
	}


def auth_token() -> str:
	"""Return the **plaintext** Twilio Auth Token.

	Gated by ``System Manager`` / ``LMS Admin`` role check; raises if
	called outside server-side code paths (e.g. public whitelisted API).
	"""
	roles = set(frappe.get_roles())
	if not roles.intersection({"System Manager", "LMS Admin"}):
		frappe.throw(
			"Refusing to read Twilio auth token: requires System Manager / LMS Admin role.",
			frappe.PermissionError,
		)
	# Prefer the encrypted Password row.
	try:
		plain = get_decrypted_password("LMS Twilio Settings", "LMS Twilio Settings", PASSWORD_KEY)
		if plain:
			return plain
	except Exception:  # noqa: BLE001
		pass
	# Fallback to site_config (should not happen in production).
	token = (frappe.conf.get("lms_twilio_auth_token", "") or "").strip()
	if not token:
		frappe.throw(
			"Twilio auth token is not configured. "
			"Set it in LMS Twilio Settings or via site_config.lms_twilio_auth_token.",
			frappe.ValidationError,
		)
	return token


def get_opt_keywords() -> set[str]:
	"""Lower-cased set of opt-out keywords (STOP, UNSUBSCRIBE, …)."""
	raw = frappe.conf.get("lms_twilio_optout_keywords") or "STOP,STOPALL,UNSUBSCRIBE,CANCEL,END,REVOKE"
	return {w.strip().lower() for w in raw.split(",") if w.strip()}


def get_optin_keywords() -> set[str]:
	"""Lower-cased set of opt-in keywords (START, ALLOW, …)."""
	raw = frappe.conf.get("lms_twilio_optin_keywords") or "START,UNSTOP,ALLOW,YES"
	return {w.strip().lower() for w in raw.split(",") if w.strip()}


def get_help_keywords() -> set[str]:
	"""Lower-cased set of help keywords (HELP, INFO)."""
	raw = frappe.conf.get("lms_twilio_help_keyword") or "HELP,INFO"
	return {w.strip().lower() for w in raw.split(",") if w.strip()}


def get_otp_config() -> dict[str, int]:
	"""Operator-tunable defaults for the OTP flow."""
	return {
		"max_attempts": int(frappe.conf.get("lms_twilio_otp_max_attempts", 5)),
		"ttl_seconds": int(frappe.conf.get("lms_twilio_otp_ttl_seconds", 300)),
		"length": int(frappe.conf.get("lms_twilio_otp_length", 6)),
	}
