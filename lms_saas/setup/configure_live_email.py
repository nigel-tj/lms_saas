"""Configure the live outgoing Email Account and flush the stuck queue.

Run (safe, idempotent):
  bench --site lms.localhost execute lms_saas.setup.configure_live_email.run

Reads SMTP credentials from site_config.json (lms_live_smtp_*) so secrets stay
out of source control. Falls back to the dev account name when re-pointing an
existing account so we don't orphan the queue's sender references.

site_config.json example:
  "lms_live_smtp_server": "kesari.africa",
  "lms_live_smtp_port": 465,
  "lms_live_email_id": "app@kesari.africa",
  "lms_live_smtp_password": "<secret>",
  "lms_live_smtp_use_ssl": 1
"""

from __future__ import annotations

import frappe
from frappe import _

DEV_EMAIL_ACCOUNT_TITLE = "LMS Dev Outgoing"
LIVE_EMAIL_ACCOUNT_TITLE = "Kesari Live Outgoing"


def run() -> dict:
	"""Idempotent: create/update the live outgoing account and retry the queue."""
	server = (frappe.conf.get("lms_live_smtp_server") or "").strip()
	port = int(frappe.conf.get("lms_live_smtp_port") or 465)
	email_id = (frappe.conf.get("lms_live_email_id") or "").strip()
	password = (frappe.conf.get("lms_live_smtp_password") or "").strip()
	use_ssl = int(bool(frappe.conf.get("lms_live_smtp_use_ssl", 1 if port == 465 else 0)))

	if not server or not email_id or not password:
		return {
			"ok": False,
			"reason": _(
				"Set lms_live_smtp_server, lms_live_email_id, lms_live_smtp_password "
				"and (optional) lms_live_smtp_port / lms_live_smtp_use_ssl in site_config.json."
			),
		}

	# Re-point the existing default outgoing account if present (keeps queue refs).
	existing = frappe.db.get_value(
		"Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, "name"
	)
	name = existing or LIVE_EMAIL_ACCOUNT_TITLE

	doc = frappe.get_doc("Email Account", name) if frappe.db.exists("Email Account", name) else None
	if doc is None:
		doc = frappe.get_doc({"doctype": "Email Account", "email_account_name": LIVE_EMAIL_ACCOUNT_TITLE})

	doc.update(
		{
			"email_id": email_id,
			"enable_outgoing": 1,
			"default_outgoing": 1,
			"enable_incoming": 0,
			"smtp_server": server,
			"smtp_port": port,
			"use_ssl_for_outgoing": use_ssl,
			"use_tls": 0 if use_ssl else 1,
			"no_smtp_authentication": 0,
			"always_use_account_email_id_as_sender": 1,
			"track_email_status": 0,
			"add_signature": 0,
		}
	)
	if password:
		doc.password = password

	frappe.local.flags.in_install = True  # skip live SMTP connect test on save
	try:
		if doc.get("__islocal") or not doc.name:
			doc.insert(ignore_permissions=True)
		else:
			doc.save(ignore_permissions=True)
	finally:
		frappe.local.flags.in_install = False
	frappe.db.commit()

	flushed = retry_stuck_queue()
	return {
		"ok": True,
		"email_account": doc.name,
		"smtp": f"{server}:{port} (ssl={use_ssl})",
		"flushed": flushed,
	}


def retry_stuck_queue() -> dict:
	"""Reset Error/Not Sent queue rows so the scheduler re-attempts delivery.

	Also rewrites the baked-in ``sender`` to the live authenticated address —
	the kesari.africa SMTP server rejects any From domain it doesn't own
	(550 "Your domain lms.localhost is not allowed in header From"), so old
	queue rows created with ``noreply@lms.localhost`` must be repointed.
	"""
	from frappe.email.doctype.email_queue.email_queue import EmailQueue

	stuck = frappe.get_all(
		"Email Queue",
		filters={"status": ("in", ["Not Sent", "Error"])},
		pluck="name",
	)
	if not stuck:
		return {"reset": 0, "note": "queue already clear"}

	live_sender = (frappe.conf.get("lms_live_email_id") or "").strip()
	rewritten = 0
	for name in stuck:
		try:
			frappe.db.set_value("Email Queue", name, "status", "Not Sent", update_modified=False)
			if live_sender:
				frappe.db.set_value("Email Queue", name, "sender", live_sender, update_modified=False)
				rewritten += 1
		except Exception:  # noqa: BLE001
			frappe.log_error(title=f"LMS email queue reset: {name}", message=frappe.get_traceback())
	frappe.db.commit()
	return {"reset": len(stuck), "senders_rewritten": rewritten}


def flush_queue() -> dict:
	"""Synchronously drain the queue now (bench execute entry point)."""
	from frappe.email.doctype.email_queue.email_queue import send_now

	stuck = frappe.get_all(
		"Email Queue",
		filters={"status": ("in", ["Not Sent", "Error"])},
		pluck="name",
	)
	sent = 0
	failed = 0
	for name in stuck:
		try:
			send_now(name, force_send=True)
			status = frappe.db.get_value("Email Queue", name, "status")
			if status == "Sent":
				sent += 1
			else:
				failed += 1
		except Exception:  # noqa: BLE001
			frappe.log_error(title=f"LMS email flush: {name}", message=frappe.get_traceback())
			failed += 1
	frappe.db.commit()
	return {"attempted": len(stuck), "sent": sent, "failed": failed}


def diagnose_queue() -> dict:
	"""Inspect stuck queue rows: sender, recipients, and error classification.

	Recipients live in the ``Email Queue Recipient`` child table (Frappe splits
	them so per-recipient status can be tracked independently).
	"""
	rows = frappe.db.sql(
		"""
		SELECT eq.name, eq.status, eq.sender, eq.error, eq.creation,
		       GROUP_CONCAT(eqr.recipient SEPARATOR ', ') AS recipients
		FROM `tabEmail Queue` eq
		LEFT JOIN `tabEmail Queue Recipient` eqr ON eqr.parent = eq.name
		WHERE eq.status IN ('Not Sent', 'Error')
		GROUP BY eq.name
		ORDER BY eq.creation DESC
		LIMIT 50
		""",
		as_dict=True,
	)
	undeliverable = 0
	other = 0
	for row in rows:
		err = (row.get("error") or "")
		recipients = row.get("recipients") or ""
		if "SMTPRecipientsRefused" in err or "example.com" in recipients:
			undeliverable += 1
		else:
			other += 1
	return {
		"stuck_total": len(rows),
		"undeliverable_demo_recipients": undeliverable,
		"other_errors": other,
		"sample": rows[:3],
	}


def clean_demo_queue() -> dict:
	"""Mark undeliverable demo-recipient queue rows as Ignored (not Sent).

	The kesari.africa SMTP server correctly 550-rejects @example.com demo
	addresses. These are seed-data artefacts, not real delivery failures —
	marking them Ignored stops the scheduler retrying them forever.
	"""
	rows = frappe.db.sql(
		"""
		SELECT eq.name, eq.error,
		       GROUP_CONCAT(eqr.recipient SEPARATOR ', ') AS recipients
		FROM `tabEmail Queue` eq
		LEFT JOIN `tabEmail Queue Recipient` eqr ON eqr.parent = eq.name
		WHERE eq.status IN ('Not Sent', 'Error')
		GROUP BY eq.name
		""",
		as_dict=True,
	)
	ignored = 0
	for row in rows:
		recipients = row.get("recipients") or ""
		err = row.get("error") or ""
		is_demo = "example.com" in recipients or "SMTPRecipientsRefused" in err
		if is_demo:
			frappe.db.set_value("Email Queue", row.name, "status", "Ignored", update_modified=False)
			ignored += 1
	frappe.db.commit()
	return {"ignored": ignored, "remaining_stuck": len(rows) - ignored}


def send_test_email(recipient: str | None = None) -> dict:
	"""Send a branded test email to verify the live SMTP path end-to-end."""
	recipient = recipient or (frappe.conf.get("lms_compliance_report_recipients") or "").split(",")[0].strip()
	if not recipient:
		return {"ok": False, "reason": "No recipient (set lms_compliance_report_recipients or pass recipient)."}

	from lms_saas.utils.email import send_branded_email

	sent = send_branded_email(
		recipients=[recipient],
		subject="LMS live SMTP test — kesari.africa",
		body_key="lead_acknowledgement",
		context={"lead_name": "SMTP Test"},
		delayed=False,
	)
	return {"ok": sent, "recipient": recipient}