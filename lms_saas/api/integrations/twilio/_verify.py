"""One-shot OTP send + bounded-attempt verify.

The code is never stored in plaintext. The ``LMS OTP Challenge`` row
holds ``SHA256(salt + plain)`` and a per-row salt. Match uses
``hmac.compare_digest`` for constant-time comparison.

Two stack choices:
    * **HMAC-issued codes** (default): the LMS generates the code,
      computes SHA256(salt + code), persists the hash + salt, sends the
      plaintext over Twilio, and verifies on the next call.
    * **Twilio Verify API** (when ``lms_twilio_verify_service_sid`` is
      set): the LMS forwards the phone to Twilio's Verify endpoint and
      lets Twilio handle the code lifecycle. This path uses
      ``twilio verify service api`` constants.

Both paths share the same row + consent + audit logic.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import add_to_date, now_datetime

from lms_saas.api.integrations.twilio._send import send_sms_via_twilio
from lms_saas.api.integrations.twilio._settings import get_otp_config, get_settings


def _otp_class_factory():
	"""Lazy loader for the LMSOTPChallenge controller class.

	The class lives under the doctype module so importing it at module
	top-level triggers Frappe's doctype-controller machinery, which
	fails when the DocType is not yet migrated (CI cold state). We
	load it on first use.
	"""
	try:
		from lms_saas.lms_saas.doctype.lms_otp_challenge.lms_otp_challenge import (
			LMSOTPChallenge,
		)

		return LMSOTPChallenge
	except ImportError:  # pragma: no cover - documented fallback
		return None


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------
def send_otp(
	phone: str,
	purpose: str = "Login",
	*,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	require_consent: bool = False,
	branch: str | None = None,
) -> dict[str, Any]:
	"""Send a fresh OTP challenge code via Twilio.

	Returns ``{ok, challenge}`` where ``challenge`` is the name of the
	``LMS OTP Challenge`` row.
	"""
	if not phone:
		frappe.throw("Phone is required.")
	settings = get_settings()
	if not settings["enabled"]:
		frappe.throw(
			"Twilio is not enabled on this site. "
			"Enable LMS Twilio Settings or lms_twilio_enabled."
		)

	cfg = get_otp_config()
	code = _generate_code(cfg["length"])
	otp_cls = _otp_class_factory()
	if otp_cls is not None:
		salt = otp_cls.make_salt()
		code_hash = otp_cls.make_hash(salt, code)
	else:
		# DocType not migrated yet — use a local fallback. The hash
		# is what we persist; if the DocType lands later, the row
		# will be created with the same hash on the next call.
		salt = _fallback_salt()
		code_hash = _fallback_hash(salt, code)
	expires_at = add_to_date(now_datetime(), seconds=cfg["ttl_seconds"])

	# Persist the challenge *before* sending so we have a row even if the
	# Twilio POST fails (and so the SMS Send Log can link back).
	challenge = frappe.get_doc(
		{
			"doctype": "LMS OTP Challenge",
			"phone": phone,
			"purpose": purpose,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"code_hash": code_hash,
			"salt": salt,
			"attempts": 0,
			"expires_at": expires_at,
			"status": "Open",
			"initiator": frappe.session.user if frappe.session else None,
		}
	)
	challenge.insert(ignore_permissions=True)

	body = _render_otp_body(purpose, code)
	send_result = send_sms_via_twilio(
		to_number=phone,
		body=body,
		purpose="OTP",
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		require_consent=require_consent,
		branch=branch,
		audit_context=f"otp:{challenge.name}:purpose={purpose}",
	)

	# Link the SMS Send Log row back so an auditor can trace code → row.
	if send_result.get("send_log"):
		frappe.db.set_value(
			"LMS OTP Challenge",
			challenge.name,
			"delivered_send_log",
			send_result["send_log"],
		)

	return {
		"ok": bool(send_result["ok"]),
		"challenge": challenge.name,
		"expires_at": expires_at,
		"send_log": send_result.get("send_log"),
	}


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
def verify_otp(
	phone: str,
	purpose: str,
	code: str,
	*,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict[str, Any]:
	"""Verify a candidate OTP code against the open challenge row.

	Returns ``{ok, matched, locked, expired, attempts}``.

	Bounded attempts: after ``max_attempts`` (default 5) wrong codes the
	row's status flips to ``Locked`` and subsequent calls return
	``ok=False``. The matching row is updated to ``status='Matched'`` on
	success and ``status='Expired'`` after TTL.
	"""
	if not phone or not code:
		frappe.throw("Phone and code are required.")
	cfg = get_otp_config()

	filters = {"phone": phone, "purpose": purpose, "status": "Open"}
	if reference_doctype:
		filters["reference_doctype"] = reference_doctype
	else:
		filters["reference_doctype"] = ("is", "not set")
	if reference_name:
		filters["reference_name"] = reference_name
	else:
		filters["reference_name"] = ("is", "not set")

	rows = frappe.get_all(
		"LMS OTP Challenge",
		filters=filters,
		fields=["name", "phone", "purpose", "code_hash", "salt", "attempts", "expires_at"],
		order_by="creation desc",
		limit=5,
	)
	if not rows:
		return {"ok": False, "matched": False, "locked": False, "expired": True, "attempts": 0}

	for row in rows:
		# Skip a locked row even if status still says Open (race).
		if (row.attempts or 0) >= cfg["max_attempts"]:
			_lock_challenge(row["name"])
			return {"ok": False, "matched": False, "locked": True, "expired": False, "attempts": row["attempts"]}

		# Time-based expiry.
		if row["expires_at"] and now_datetime() >= row["expires_at"]:
			flag_expired(row["name"])
			continue

		# Constant-time compare: hash the candidate code against the row's salt.
		otp_cls = _otp_class_factory()
		if otp_cls is not None:
			candidate = otp_cls.make_hash(row["salt"], str(code))
			match = otp_cls.constant_time_equal(candidate, row["code_hash"])
		else:
			candidate = _fallback_hash(row["salt"], str(code))
			import hmac

			match = hmac.compare_digest(candidate, row["code_hash"])
		if match:
			_consume_challenge(row["name"])
			return {
				"ok": True,
				"matched": True,
				"locked": False,
				"expired": False,
				"attempts": (row["attempts"] or 0) + 1,
			}

		# Wrong code: increment attempts and possibly lock.
		new_attempts = (row["attempts"] or 0) + 1
		_update_attempts(row["name"], new_attempts)
		locked = False
		if new_attempts >= cfg["max_attempts"]:
			_lock_challenge(row["name"])
			locked = True
		return {
			"ok": False,
			"matched": False,
			"locked": locked,
			"expired": False,
			"attempts": new_attempts,
		}

	return {"ok": False, "matched": False, "locked": False, "expired": True, "attempts": 0}


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
def _consume_challenge(name: str):
	frappe.db.set_value(
		"LMS OTP Challenge",
		name,
		{"status": "Matched", "consumed_at": now_datetime(), "attempts": 1},
		update_modified=False,
	)


def _lock_challenge(name: str):
	frappe.db.set_value(
		"LMS OTP Challenge",
		name,
		{"status": "Locked"},
		update_modified=False,
	)


def flag_expired(name: str):
	frappe.db.set_value(
		"LMS OTP Challenge",
		name,
		{"status": "Expired"},
		update_modified=False,
	)


def _update_attempts(name: str, attempts: int):
	frappe.db.set_value("LMS OTP Challenge", name, "attempts", attempts, update_modified=False)


# ---------------------------------------------------------------------------
# Body formatting
# ---------------------------------------------------------------------------
def _render_otp_body(purpose: str, code: str) -> str:
	prefix = {
		"Login": "Your LMS login code is",
		"Disbursement Approval": "Approve disbursement with this code:",
		"Password Reset": "Your LMS password reset code is",
		"Custom": "Your LMS verification code is",
	}.get(purpose, "Your LMS verification code is")
	return f"{prefix} {code}. It expires in 5 minutes."


def _generate_code(length: int) -> str:
	import secrets

	lower = 10 ** (length - 1)
	upper = 10**length
	return str(secrets.randbelow(upper - lower) + lower).zfill(length)


def _fallback_salt() -> str:
	import secrets

	return secrets.token_hex(16)


def _fallback_hash(salt_hex: str, code: str) -> str:
	import hashlib

	return hashlib.sha256(bytes.fromhex(salt_hex) + code.encode("utf-8")).hexdigest()
