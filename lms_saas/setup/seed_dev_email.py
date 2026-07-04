"""Dev outgoing Email Account for desk CRM compose and LMS notifications.

Run (safe, idempotent):
  bench --site lms.localhost execute lms_saas.setup.seed_dev_email.run

Optional site_config.json:
  "lms_seed_dev_email": 1,
  "lms_dev_email_id": "noreply@yourcompany.local",
  "lms_dev_smtp_server": "127.0.0.1",
  "lms_dev_smtp_port": 1025

Port 1025 is the default for Mailpit/MailHog. Without a local SMTP catcher, messages
still queue in Email Queue; SMTP send may fail until you start Mailpit or point
smtp_server at real SMTP credentials in Desk → Email Account.
"""

from __future__ import annotations

import frappe
from frappe import _

DEV_EMAIL_ACCOUNT_TITLE = "LMS Dev Outgoing"


def run():
	"""bench execute entry — always seeds when no default outgoing account exists."""
	return ensure_dev_email_account(allow_without_dev_flag=True)


def ensure_dev_email_account(*, allow_without_dev_flag: bool = False) -> dict:
	"""Create a default outgoing Email Account when the site has none."""
	existing = frappe.db.get_value(
		"Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, "name"
	)
	if existing:
		return {"ok": True, "skipped": True, "email_account": existing}

	if not allow_without_dev_flag and not _dev_seed_enabled():
		return {
			"ok": False,
			"skipped": True,
			"reason": "Set developer_mode, lms_seed_dev_email in site_config, or run seed_dev_email.run",
		}

	email_id = (frappe.conf.get("lms_dev_email_id") or "noreply@lms.localhost").strip()
	smtp_server = frappe.conf.get("lms_dev_smtp_server") or "127.0.0.1"
	smtp_port = int(frappe.conf.get("lms_dev_smtp_port") or 1025)

	doc = frappe.get_doc(
		{
			"doctype": "Email Account",
			"email_account_name": DEV_EMAIL_ACCOUNT_TITLE,
			"email_id": email_id,
			"enable_outgoing": 1,
			"default_outgoing": 1,
			"enable_incoming": 0,
			"no_smtp_authentication": 1,
			"use_tls": 0,
			"use_ssl_for_outgoing": 0,
			"smtp_server": smtp_server,
			"smtp_port": smtp_port,
			"always_use_account_email_id_as_sender": 1,
			"track_email_status": 0,
			"add_signature": 0,
		}
	)
	# Skip SMTP connect test on save (Mailpit may not be running yet).
	frappe.local.flags.in_install = True
	try:
		doc.insert(ignore_permissions=True)
	finally:
		frappe.local.flags.in_install = False
	frappe.db.commit()

	return {
		"ok": True,
		"created": doc.name,
		"email_id": email_id,
		"smtp": f"{smtp_server}:{smtp_port}",
		"hint": _(
			"Start Mailpit on port {0} or edit this Email Account in Desk for real SMTP."
		).format(smtp_port),
	}


def _dev_seed_enabled() -> bool:
	return bool(frappe.conf.get("lms_seed_dev_email") or frappe.conf.developer_mode)


def verify_default_outgoing() -> dict:
	"""Quick check for scripts and verify_spec."""
	name = frappe.db.get_value(
		"Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, "name"
	)
	return {"ok": bool(name), "email_account": name}


def _ensure_dev_test_lead() -> str | None:
	"""Minimal Lead for officer email compose tests."""
	name = frappe.db.get_value("Lead", {"lead_name": "LMS Dev Test Lead"}, "name")
	if name:
		return name
	if not frappe.db.exists("DocType", "Lead"):
		return None
	doc = frappe.get_doc(
		{
			"doctype": "Lead",
			"lead_name": "LMS Dev Test Lead",
			"email_id": "dev-lead-test@example.com",
			"company_name": "Dev Test Co",
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def run_tests() -> dict:
	"""Exercise desk email prerequisites as demo users (bench execute)."""
	from frappe.core.doctype.communication.email import make

	_ensure_dev_test_lead()
	users = {
		"officer": "demo.lms.officer@example.com",
		"collector": "demo.lms.collector@example.com",
	}
	out = {"ok": True, "default_outgoing": verify_default_outgoing(), "users": {}}

	for key, email in users.items():
		if not frappe.db.exists("User", email):
			out["users"][key] = {"ok": False, "error": "user missing"}
			out["ok"] = False
			continue

		checks = {}
		frappe.set_user(email)
		try:
			default = frappe.db.get_value(
				"Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, "name"
			)
			checks["default_outgoing"] = default
			checks["email_account_read"] = frappe.has_permission("Email Account", ptype="read")
			checks["collector_no_lead"] = (
				not frappe.has_permission("Lead", ptype="read")
				if key == "collector"
				else frappe.has_permission("Lead", ptype="read")
			)

			lead = frappe.db.get_value("Lead", {}, "name")
			if lead and key == "officer":
				frappe.has_permission("Lead", doc=lead, ptype="email", throw=True)
				comm = make(
					doctype="Lead",
					name=lead,
					subject="LMS dev email test",
					content="<p>Dev compose test</p>",
					send_email=False,
				)
				checks["lead_communication"] = comm.get("name")
			elif key == "officer":
				checks["lead_communication"] = "skipped (no Lead)"

			customer = frappe.db.get_value("Customer", {}, "name")
			if customer:
				frappe.has_permission("Customer", doc=customer, ptype="email", throw=True)
		except Exception as exc:
			checks["error"] = str(exc)[:300]
			out["ok"] = False
		finally:
			frappe.set_user("Administrator")

		checks["ok"] = "error" not in checks and checks.get("email_account_read") and checks.get(
			"default_outgoing"
		) and checks.get("collector_no_lead", True)
		out["users"][key] = checks
		if not checks.get("ok"):
			out["ok"] = False

	return out
