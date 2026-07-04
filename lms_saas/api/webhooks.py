"""Outbound webhook delivery."""

from __future__ import annotations

import hashlib
import hmac
import json

import frappe
import requests


def dispatch_webhook_event(event: str, payload: dict):
	"""Enqueue delivery to all active subscriptions for an event."""
	if frappe.flags.in_install:
		return

	subscriptions = frappe.get_all(
		"LMS Webhook Subscription",
		filters={"enabled": 1, "event": event},
		fields=["name", "target_url", "secret"],
	)
	for sub in subscriptions:
		frappe.enqueue(
			"lms_saas.api.webhooks._deliver_webhook",
			subscription=sub.name,
			target_url=sub.target_url,
			secret=sub.secret,
			event=event,
			payload=payload,
			queue="short",
		)


def _deliver_webhook(subscription: str, target_url: str, secret: str, event: str, payload: dict):
	body = json.dumps({"event": event, "payload": payload, "site": frappe.local.site})
	headers = {"Content-Type": "application/json"}
	if secret:
		headers["X-LMS-Signature"] = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

	status = "Failed"
	error = None
	try:
		resp = requests.post(target_url, data=body, headers=headers, timeout=15)
		resp.raise_for_status()
		status = "Sent"
	except requests.exceptions.RequestException as exc:
		error = str(exc)
		frappe.log_error(message=error, title=f"LMS Webhook delivery failed: {subscription}")

	try:
		from lms_saas.api.collections import log_notification

		log_notification(
			loan_name=payload.get("loan") or "—",
			reminder_type=f"webhook:{event}",
			channel="Webhook",
			status=status,
			recipient=target_url,
			message_preview=body[:500],
		)
	except Exception:
		pass

	if error:
		frappe.db.set_value("LMS Webhook Subscription", subscription, "last_error", error)
	else:
		frappe.db.set_value(
			"LMS Webhook Subscription",
			subscription,
			{"last_delivered_at": frappe.utils.now_datetime(), "last_error": ""},
		)
