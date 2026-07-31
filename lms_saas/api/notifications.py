import frappe
import requests


def dispatch_sms_gateway(to_num, text, *,
                        require_consent: bool | None = None,
                        reference_doctype: str | None = None,
                        reference_name: str | None = None,
                        purpose: str = "Reminder",
                        branch: str | None = None):
	"""Send an SMS via the configured gateway.

	Routing precedence:
	  1. If Twilio is enabled and properly configured, dispatch via
	     ``lms_saas.api.integrations.twilio_api.send_sms`` (with consent
	     enforcement and a per-send audit trail).
	  2. Else fall back to Frappe's native ``SMS Settings`` URL gateway.

	Designed to run in a background job: failures are logged, never raised, so
	one undeliverable message cannot fail the worker or block the batch.
	Returns True on success, False otherwise.
	"""
	# --- Twilio routing (preferred) ---
	try:
		from lms_saas.api.integrations.twilio import is_enabled as _twilio_enabled

		if _twilio_enabled():
			from lms_saas.api.integrations.twilio_api import send_sms as _send

			result = _send(
				to_num,
				text,
				template=None,
				reference_doctype=reference_doctype,
				reference_name=reference_name,
				purpose=purpose,
				require_consent=1 if require_consent else 0,
				max_length=1600,  # Twilio's max single-message length
			)
			return bool(result and result.get("ok"))
	except Exception as e:  # noqa: BLE001
		frappe.log_error(
			title="LMS Twilio dispatch routing failed (fallback to SMS Settings)",
			message=f"{e}\ntraceback:\n{frappe.get_traceback()}",
		)
		# Fall through to the legacy gateway path.

	# --- Native SMS Settings fallback ---
	gateway_url = frappe.db.get_single_value("SMS Settings", "sms_gateway_url")

	if not gateway_url:
		_log_sms_incident(
			to_num,
			text,
			title="LMS SMS gateway not configured",
			description=f"No SMS gateway URL. Message for {to_num}: {text[:200]}",
		)
		frappe.log_error(
			message=f"SMS (no gateway configured) to {to_num}: {text}",
			title="LMS SMS Dispatch Logger",
		)
		return False

	try:
		requests.post(gateway_url, json={"to": to_num, "message": text}, timeout=10)
		return True
	except requests.exceptions.RequestException as e:
		_log_sms_incident(
			to_num,
			text,
			title="LMS SMS Gateway Failure",
			description=str(e),
		)
		frappe.log_error(message=str(e), title="LMS SMS Gateway Failure")
		return False


def _log_sms_incident(to_num, text, title, description):
	"""Auto-create LMS Incident Log (Technical) for SMS operational failures."""
	try:
		if frappe.db.exists(
			"LMS Incident Log",
			{
				"title": title,
				"reference_doctype": "SMS Settings",
				"status": ("in", ["Open", "Investigating"]),
			},
		):
			return
		frappe.get_doc(
			{
				"doctype": "LMS Incident Log",
				"title": title,
				"incident_type": "Technical",
				"severity": "Medium",
				"status": "Open",
				"reported_on": frappe.utils.now_datetime(),
				"reference_doctype": "SMS Settings",
				"reference_name": "SMS Settings",
				"description": (
					f"{description}\n\nRecipient: {to_num}\nPreview: {(text or '')[:300]}"
				),
			}
		).insert(ignore_permissions=True)
	except Exception:  # noqa: BLE001
		frappe.log_error(title="LMS SMS incident log failed", message=frappe.get_traceback())
