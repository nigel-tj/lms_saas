"""Public whitelisted surface for the Twilio integration.

Split into two groups:

1. **Authenticated (Bearer-key or session)**:
   - ``send_sms``
   - ``send_otp``
   - ``verify_otp``
   - ``get_send_log``
   - ``get_templates``
   - ``get_settings``     (PII-stripped)

2. **Public, Twilio-signed only (allow_guest=True)**:
   - ``status``           — Twilio delivery callback
   - ``inbound``          — Twilio inbound keyword webhook

The webhook receivers do NOT require an Frappe login; they enforce a
shared signing secret via ``X-Twilio-Signature`` when configured, and
otherwise fall back to per-IP rate-limiting with a strong
``lms_twilio_webhook_open`` audit warning (mirroring the payment-provider
callback pattern in ``lms_saas/api/payments/service.py``).
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from lms_saas.api.integrations.twilio import (
    get_settings as _twilio_get_settings,
)
from lms_saas.api.integrations.twilio import (
    is_enabled,
    parse_inbound_keyword,
)
from lms_saas.api.integrations.twilio._send import send_sms_via_twilio
from lms_saas.api.integrations.twilio._status import handle_status_callback
from lms_saas.api.integrations.twilio._verify import send_otp, verify_otp
from lms_saas.utils.api_auth import validate_api_key


# ---------------------------------------------------------------------------
# Authenticated
# ---------------------------------------------------------------------------
@frappe.whitelist()
def ping() -> dict[str, Any]:
	"""Health probe used by the desk Settings page and CI."""
	return {
		"enabled": is_enabled(),
		"settings": _twilio_get_settings() if is_enabled() else {"enabled": False},
	}


@frappe.whitelist()
@rate_limit(limit=30, seconds=60, methods=["POST"])
def send_sms(
	to_number: str,
	body: str,
	*,
	template: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	purpose: str = "Custom",
	require_consent: int = 0,
	max_length: int | None = None,
) -> dict[str, Any]:
	"""Whitelisted send. Sends via Twilio when enabled; otherwise raises."""
	if not is_enabled():
		frappe.throw(_("Twilio is not enabled on this site."))
	return send_sms_via_twilio(
		to_number=to_number,
		body=body,
		template=template,
		purpose=purpose,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		require_consent=bool(require_consent),
		max_length=max_length,
	)


@frappe.whitelist()
@rate_limit(limit=10, seconds=60, methods=["POST"])
def send_otp_api(
	phone: str,
	*,
	purpose: str = "Login",
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict[str, Any]:
	"""Whitelisted OTP send.

	Returns ``{ok, challenge_name, ttl}``.
	"""
	if not is_enabled():
		frappe.throw(_("Twilio is not enabled on this site."))
	out = send_otp(
		phone=phone,
		purpose=purpose,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		require_consent=False,
	)
	out["ttl"] = out.pop("expires_at", None)
	return out


@frappe.whitelist()
@rate_limit(limit=30, seconds=60, methods=["POST"])
def verify_otp_api(
	phone: str,
	purpose: str,
	code: str,
	*,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict[str, Any]:
	"""Whitelisted OTP verify."""
	return verify_otp(
		phone=phone,
		purpose=purpose,
		code=str(code),
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)


@frappe.whitelist()
def get_send_log(limit: int = 100, status: str | None = None) -> dict[str, Any]:
	"""Branch-scoped view of LMS SMS Send Log rows for the current desk user."""
	filters = {}
	if status:
		filters["status"] = status
	if not _is_admin():
		branch = _current_user_branch()
		if branch:
			filters["branch"] = branch
	rows = frappe.get_all(
		"LMS SMS Send Log",
		filters=filters,
		fields=[
			"name", "to_number", "from_number", "twilio_sid", "status",
			"purpose", "branch", "template", "body_preview", "error_code",
			"sent_at", "delivered_at", "failed_at", "creation",
		],
		order_by="creation desc",
		limit_page_length=int(limit),
	)
	return {"logs": rows, "count": len(rows)}


@frappe.whitelist()
def get_templates(limit: int = 100) -> dict[str, Any]:
	"""Approved LMS SMS Templates, in template_name order."""
	rows = frappe.get_all(
		"LMS SMS Template",
		filters={"is_approved": 1},
		fields=["name", "template_name", "category", "language", "body"],
		order_by="template_name asc",
		limit_page_length=int(limit),
	)
	return {"templates": rows}


@frappe.whitelist()
def get_settings_public() -> dict[str, Any]:
	"""Redacted settings for desk Settings page; never returns the auth token."""
	return _twilio_get_settings()


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True, methods=["POST", "GET"])
def status() -> str:
	"""Twilio delivery-receipt webhook.

	Method: Twilio POSTs URL-encoded form. Frappe auto-parses to
	``frappe.form_dict``. We accept GET too for dev curl probes but
	always bounce Twilio back to POST via the response code.
	"""
	payload = _form_dict()
	if not payload:
		frappe.local.response["http_status_code"] = 400
		frappe.local.response["type"] = "json"
		return json.dumps({"ok": False, "reason": "empty form"})
	_enforce_signature_or_audit(payload, scope="status")

	result = handle_status_callback(payload)
	frappe.local.response["http_status_code"] = 200 if result["matched"] else 404
	frappe.local.response["type"] = "json"
	return json.dumps(result)


@frappe.whitelist(allow_guest=True, methods=["POST", "GET"])
def inbound() -> str:
	"""Twilio inbound keyword webhook.

	Returns TwiML. Stop/Start/Help keywords are processed into borrower
	consent flips; everything else is logged and ignored.
	"""
	payload = _form_dict()
	if not payload:
		return _twiml("Sorry, we could not process your message.")
	_enforce_signature_or_audit(payload, scope="inbound")

	from_number = (payload.get("From") or "").strip()
	body = payload.get("Body") or ""
	parsed = parse_inbound_keyword(body, from_number)

	if parsed["keyword"] == "optout":
		_update_consent(from_number, opted_out=1)
		return _twipl(
			"You've been unsubscribed. Reply START to opt back in. Reply HELP for help."
		)
	if parsed["keyword"] == "optin":
		_update_consent(from_number, opted_out=0)
		return _twipl(
			"You're subscribed. Reply STOP to unsubscribe."
		)
	if parsed["keyword"] == "help":
		return _twipl(
			"Reply STOP to unsubscribe. For support contact your branch."
		)

	# Unknown: ack with minimal reply and log.
	frappe.logger().info("LMS Twilio inbound (no keyword) from %s: %s", from_number, body[:100])
	return _twipl("")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _form_dict() -> dict:
	"""Return a Frappe form-dict regardless of POST or GET (for dev probes)."""
	if getattr(frappe, "request", None) and frappe.request.method == "POST":
		return {k: v for k, v in (frappe.form_dict or {}).items()}
	return {k: v for k, v in (frappe.form_dict or {}).items()}


def _enforce_signature_or_audit(payload: dict, *, scope: str):
	"""If ``lms_twilio_webhook_secret`` is configured, verify the
	X-Twilio-Signature header (HMAC-SHA1 over the full URL + sorted
	POST params). Otherwise log an audit event so the operator can
	detect when signature enforcement is missing in production.
	"""
	secret = (frappe.conf.get("lms_twilio_webhook_secret", "") or "").strip()
	if not secret:
		try:
			from lms_saas.api.compliance import write_audit_event
			write_audit_event(
				event_type=f"Twilio:Webhook:Unprotected",
				reference_doctype=None,
				reference_name=None,
				details=f"scope={scope} from={(payload or {}).get('From') or ''} body={(payload or {}).get('Body') or ''}"[:500],
			)
		except Exception:  # noqa: BLE001
			pass
		return

	if not _verify_twilio_signature(payload, secret):
		frappe.throw(
			"Twilio signature verification failed.",
			frappe.AuthenticationError,
		)


def _verify_twilio_signature(payload: dict, secret: str) -> bool:
	"""Verify HMAC-SHA1 of ``url + sorted_alpha(k + v)`` matches
	``X-Twilio-Signature``.

	Reference: Twilio's webhook signature spec
	(https://www.twilio.com/docs/usage/webhooks/webhooks-security).
	Implemented in-house to avoid the optional ``twilio`` SDK dep.
	"""
	import hashlib
	import hmac

	if not frappe.request:
		return False
	url = (frappe.request.url or "").split("?")[0]
	signature = (frappe.request.headers.get("X-Twilio-Signature") or "").strip()
	if not signature:
		return False

	# Twilio sorts POST params lexicographically and appends ``key``
	# then ``value`` (already URL-decoded by Frappe).
	sorted_items = sorted((payload or {}).items())
	signed = url
	for key, value in sorted_items:
		signed += key + ("" if value is None else str(value))

	expected = hmac.new(
		secret.encode("utf-8"),
		signed.encode("utf-8"),
		hashlib.sha1,
	).hexdigest()
	return hmac.compare_digest(expected, signature)


def _update_consent(phone: str, *, opted_out: int):
	"""Flip ``opted_out_sms`` for the compliance row whose Customer record
	matches the supplied E.164 phone number."""
	if not phone:
		return
	customer = frappe.db.get_value("Customer", {"mobile_no": phone}, "name")
	if not customer:
		return
	if not frappe.db.exists("DocType", "LMS Twilio Settings"):
		return
	compliance = frappe.db.get_value(
		"LMS Borrower Compliance", {"customer": customer}, "name"
	)
	if not compliance:
		return
	frappe.db.set_value(
		"LMS Borrower Compliance",
		compliance,
		{
			"opted_out_sms": opted_out,
			"opted_out_at": frappe.utils.now_datetime() if opted_out else None,
		},
		update_modified=False,
	)


def _is_admin() -> bool:
	roles = set(frappe.get_roles())
	return bool(roles.intersection({"System Manager", "LMS Admin"}))


def _current_user_branch() -> str | None:
	try:
		from lms_saas.api.staff import get_current_user_branch
		return get_current_user_branch()
	except Exception:  # noqa: BLE001
		return None


def _twipl(message: str) -> str:
	"""Wrap a Twilio TwiML reply (no body = no reply)."""
	escaped = (
		message.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
	)
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		"<Response>"
		+ (f"<Message>{escaped}</Message>" if message else "")
		+ "</Response>"
	)
