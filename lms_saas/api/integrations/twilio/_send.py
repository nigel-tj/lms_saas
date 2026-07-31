"""Outbound SMS via Twilio.

POST to
``https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json``
with HTTP Basic Auth (``account_sid:auth_token``) and a
``application/x-www-form-urlencoded`` body containing ``To``, ``From``,
``Body`` (and optionally ``StatusCallback``).

The function returns ``(ok: bool, sid: str | None)``. All side-effects
(LMS SMS Send Log row, audit event, failure incident, sandbox audit)
happen in this single function so callers don't need to coordinate.

Failure modes and reporting:
    * **sandbox_fail_open**: the HTTP call is skipped and the row is
      written with ``status='Sandbox'``. A mandatory audit event is
      written so the regulator trace shows every dev-mode send.
    * **HTTP failure**: row written with ``status='Failed'`` plus
      ``error_code``, and a ``LMS Incident Log`` is opened.
    * **Consent gate**: passed in as ``require_consent=True`` (default
      for borrower sends); when missing, row is written with
      ``status='Blocked-NoConsent'`` and False is returned. No HTTP
      call is attempted.
    * **Dedupe**: rows are deduped on ``(to_number, body_sha256)``.
      Re-sends within the same minute re-use the existing log row.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
import requests

from lms_saas.api.integrations.twilio._settings import (
    auth_token,
    get_settings,
)


TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def send_sms_via_twilio(
    to_number: str,
    body: str,
    *,
    purpose: str = "Custom",
    template: str | None = None,
    reference_doctype: str | None = None,
    reference_name: str | None = None,
    from_number: str | None = None,
    require_consent: bool = False,
    branch: str | None = None,
    variables: dict | None = None,
    max_length: int | None = None,
    audit_context: str | None = None,
) -> dict[str, Any]:
	"""Send one SMS through Twilio and persist a Send Log row.

	Returns a dict ``{ok, sid, status, send_log}`` where ``send_log`` is
	the name of the LMS SMS Send Log row (a hash), and ``ok`` is the
	binary "did Twilio accept it?" answer.
	"""
	settings = get_settings()
	if not settings["enabled"]:
		return {"ok": False, "sid": None, "status": "Disabled", "send_log": None}

	if not to_number or not body:
		frappe.throw("To and Body are required.")

	if max_length and len(body) > max_length:
		frappe.throw(f"SMS body exceeds max_length ({max_length}).")

	# Consent gate.
	consent_given = True
	if require_consent:
		consent_given = _borrower_has_consent_for_phone(to_number, reference_doctype, reference_name)
		if not consent_given:
			send_log = _write_send_log(
				to_number=to_number,
				from_number=from_number or settings["default_from_number"],
				body=body,
				template=template,
				purpose=purpose,
				branch=branch,
				reference_doctype=reference_doctype,
				reference_name=reference_name,
				consent_given=False,
				status="Blocked-NoConsent",
				twilio_sid=None,
				provider_response=None,
			)
			return {
				"ok": False,
				"sid": None,
				"status": "Blocked-NoConsent",
				"send_log": send_log,
			}

	# Dedupe on (to_number, body_sha256).
	body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
	existing = _find_dedupe_row(to_number, body_sha256)
	if existing:
		return {
			"ok": existing.status in ("Sent", "Delivered", "Sandbox"),
			"sid": existing.twilio_sid,
			"status": existing.status,
			"send_log": existing.name,
		}

	# Render template if applicable.
	rendered_body = body
	if template:
		rendered_body = _render_template(template, body, variables or {})
		body_sha256 = hashlib.sha256(rendered_body.encode("utf-8")).hexdigest()
		existing = _find_dedupe_row(to_number, body_sha256)
		if existing:
			return {
				"ok": existing.status in ("Sent", "Delivered", "Sandbox"),
				"sid": existing.twilio_sid,
				"status": existing.status,
				"send_log": existing.name,
			}

	# Sandbox fail-open short-circuits the network call.
	if settings["sandbox_fail_open"]:
		_audit_sandbox_send(to_number, purpose, audit_context)
		send_log = _write_send_log(
			to_number=to_number,
			from_number=from_number or settings["default_from_number"],
			body=rendered_body,
			template=template,
			purpose=purpose,
			branch=branch,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			consent_given=consent_given,
			status="Sandbox",
			twilio_sid=None,
			provider_response={"sandbox": True},
		)
		return {"ok": True, "sid": None, "status": "Sandbox", "send_log": send_log}

	# Real Twilio send.
	try:
		from_number = from_number or settings["default_from_number"]
		if not from_number:
			frappe.throw("No From number configured on LMS Twilio Settings.")

		token = auth_token()
		url = f"{TWILIO_API_BASE}/Accounts/{settings['account_sid']}/Messages.json"
		payload = {"To": to_number, "From": from_number, "Body": rendered_body}
		if settings["status_callback_url"]:
			payload["StatusCallback"] = settings["status_callback_url"]

		resp = requests.post(
			url,
			auth=(settings["account_sid"], token),
			data=payload,
			timeout=15,
		)
	except requests.exceptions.RequestException as exc:
		_log_send_failure(to_number, str(exc), purpose=purpose)
		send_log = _write_send_log(
			to_number=to_number,
			from_number=from_number or settings["default_from_number"],
			body=rendered_body,
			template=template,
			purpose=purpose,
			branch=branch,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			consent_given=consent_given,
			status="Failed",
			twilio_sid=None,
			provider_response={"error": str(exc)},
		)
		return {"ok": False, "sid": None, "status": "Failed", "send_log": send_log}

	data, error = _safe_json(resp)
	sid = (data or {}).get("sid") if data else None
	twilio_status = (data or {}).get("status") if data else None
	error_code = (data or {}).get("code") if data else None
	provider_response = _redact_response(data or {})
	# Treat 2xx + status='queued' / 'accepted' as success.
	ok = 200 <= resp.status_code < 300 and not error_code
	status = "Sent" if ok else "Failed"
	if not ok and error:
		provider_response["http_error"] = error

	send_log = _write_send_log(
		to_number=to_number,
		from_number=from_number,
		body=rendered_body,
		template=template,
		purpose=purpose,
		branch=branch,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		consent_given=consent_given,
		status=status,
		twilio_sid=sid,
		provider_response=provider_response,
		segment_count=(data or {}).get("num_segments") if data else None,
		cost=(data or {}).get("price") if data else None,
		sent_at=frappe.utils.now_datetime() if ok else None,
		failed_at=None if ok else frappe.utils.now_datetime(),
		error_code=str(error_code) if error_code else None,
	)

	# Surface low-level Twilio status for the From/To pair to the log row
	# so we can debug carrier issues without re-creating the message.
	if twilio_status and not ok:
		frappe.db.set_value(
			"LMS SMS Send Log", send_log, "error_code", f"{error_code}:{twilio_status}"
		)

	return {"ok": ok, "sid": sid, "status": status, "send_log": send_log}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _find_dedupe_row(to_number, body_sha256):
	return frappe.db.get_value(
		"LMS SMS Send Log",
		{"to_number": to_number, "body_sha256": body_sha256},
		["name", "status", "twilio_sid"],
		as_dict=True,
	)


def _write_send_log(
	*,
	to_number,
	from_number,
	body,
	template,
	purpose,
	branch,
	reference_doctype,
	reference_name,
	consent_given,
	status,
	twilio_sid,
	provider_response,
	segment_count=None,
	cost=None,
	sent_at=None,
	failed_at=None,
	error_code=None,
) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "LMS SMS Send Log",
			"to_number": to_number,
			"from_number": from_number,
			"twilio_sid": twilio_sid or None,
			"status": status,
			"branch": branch,
			"body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
			"body_preview": (body or "")[:200],
			"template": template,
			"purpose": purpose,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"consent_given": 1 if consent_given else 0,
			"segment_count": segment_count or None,
			"cost": cost if cost not in (None, "", "0", "0.0") else None,
			"error_code": error_code,
			"provider_response": json.dumps(provider_response)
			if provider_response
			else None,
			"sent_at": sent_at,
			"failed_at": failed_at,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _audit_sandbox_send(to_number: str, purpose: str, audit_context: str | None):
	try:
		from lms_saas.api.compliance import write_audit_event

		write_audit_event(
			event_type="Twilio:SandboxFailOpen",
			reference_doctype=None,
			reference_name=None,
			details=(
				f"to={to_number} purpose={purpose} "
				f"audit_context={audit_context or ''}"
			),
		)
	except Exception:  # noqa: BLE001
		frappe.log_error(
			title="LMS Twilio sandbox audit failed",
			message=frappe.get_traceback(),
		)


def _log_send_failure(to_number: str, error: str, *, purpose: str = "Custom"):
	"""Open an LMS Incident Log row (Technical, Medium) for a Twilio
	transport-level failure. Re-uses an existing Open/Investigating row
	if one is already open."""
	try:
		if frappe.db.exists(
			"LMS Incident Log",
			{
				"title": "LMS Twilio Provider Transport Failure",
				"reference_doctype": "LMS Twilio Settings",
				"reference_name": "LMS Twilio Settings",
				"status": ("in", ["Open", "Investigating"]),
			},
		):
			return
		frappe.get_doc(
			{
				"doctype": "LMS Incident Log",
				"title": "LMS Twilio Provider Transport Failure",
				"incident_type": "Technical",
				"severity": "Medium",
				"status": "Open",
				"reported_on": frappe.utils.now_datetime(),
				"reference_doctype": "LMS Twilio Settings",
				"reference_name": "LMS Twilio Settings",
				"description": (
					f"Twilio transport-level failure for {to_number} "
					f"(purpose={purpose}): {error[:500]}"
				),
			}
		).insert(ignore_permissions=True)
	except Exception:  # noqa: BLE001
		frappe.log_error(title="LMS Twilio incident log failed", message=frappe.get_traceback())


def _borrower_has_consent_for_phone(
	to_number: str,
	reference_doctype: str | None,
	reference_name: str | None,
) -> bool:
	"""Look up the borrower for the supplied reference and check consent.

	Currently this only checks ``Loan`` linkages (the majority of LMS
	SMS send sites). For ``Loan Application`` we look up the linked
	Customer via the loan application document.
	"""
	try:
		if reference_doctype == "Loan" and reference_name:
			customer = frappe.db.get_value("Loan", reference_name, "applicant")
			if not customer:
				return False
			val = frappe.db.get_value(
				"LMS Borrower Compliance", {"customer": customer}, "consent_given"
			)
			opted_out = bool(
				frappe.db.get_value(
					"LMS Borrower Compliance", {"customer": customer}, "opted_out_sms"
				)
			)
			return bool(val) and not opted_out
		if reference_doctype == "Customer" and reference_name:
			val = frappe.db.get_value(
				"LMS Borrower Compliance",
				{"customer": reference_name},
				["consent_given", "opted_out_sms"],
				as_dict=True,
			)
			return bool(val and val.consent_given and not val.opted_out_sms)
	except Exception:  # noqa: BLE001
		return False
	return False


def _render_template(template_name: str, default_body: str, variables: dict) -> str:
	try:
		tpl = frappe.get_doc("LMS SMS Template", template_name)
	except frappe.DoesNotExistError:
		return default_body
	return tpl.render(variables)


def _redact_response(data: dict) -> dict:
	"""Strip PII from a Twilio response before storing it on the log."""
	return {
		"status": data.get("status"),
		"sid": data.get("sid"),
		"code": data.get("code"),
		"message": data.get("message"),
		"num_segments": data.get("num_segments"),
		"price": data.get("price"),
		"price_unit": data.get("price_unit"),
		"error_code": data.get("error_code"),
		"error_message": data.get("error_message"),
	}


def _safe_json(resp: requests.Response) -> tuple[dict | None, str | None]:
	try:
		body = resp.json() if resp.content else {}
	except ValueError:
		return None, "invalid JSON response"
	if 200 <= resp.status_code < 300:
		return body, None
	return body, f"HTTP {resp.status_code}"
