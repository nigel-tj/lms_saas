"""Branded HTML email rendering and dispatch for LMS."""

from __future__ import annotations

import os
import re

import frappe
from frappe import _
from frappe.utils import get_url, validate_email_address

from lms_saas.utils.brand import (
	_brand_alias,
	enrich_brand,
	get_brand_favicon_url,
	get_brand_logo_url,
)

EMAIL_BODY_TEMPLATES = {
	"payment_reminder": "templates/email/payment_reminder_body.html",
	"repayment_received": "templates/email/repayment_received_body.html",
	"disbursement_received": "templates/email/disbursement_received_body.html",
	"welcome": "templates/email/welcome_body.html",
	"lead_acknowledgement": "templates/email/lead_acknowledgement_body.html",
	"morning_digest": "templates/email/morning_digest_body.html",
	"kpi_pack": "templates/email/kpi_pack_body.html",
}

EMAIL_TEMPLATE_NAMES = {
	"payment_reminder": "LMS Payment Reminder",
	"repayment_received": "LMS Loan Repayment Received",
	"disbursement_received": "LMS Loan Disbursed",
	"welcome": "LMS Welcome",
	"lead_acknowledgement": "LMS Lead Acknowledgement",
	"morning_digest": "LMS Morning Digest",
	"kpi_pack": "LMS Sandbox Weekly KPI",
}


def get_email_brand_context() -> dict:
	"""Brand tokens for email templates (logo URL must be absolute for clients).

	R23-C1 fix: brand fallbacks are vendor-neutral ("LMS") rather than
	the hard-coded operator name. The operator's brand comes from
	`lms_brand_portal_title` in site_config and is written to Website
	Settings by the after_install hook (see install.py).
	"""
	brand = enrich_brand()
	company = brand.get("company_name") or brand.get("portal_title") or _brand_alias("operator_brand")
	site = get_url()
	logo = brand.get("logo_url") or get_brand_logo_url()
	if logo and logo.startswith("/"):
		logo = f"{site.rstrip('/')}{logo}"
	favicon = brand.get("favicon_url") or get_brand_favicon_url()
	if favicon and favicon.startswith("/"):
		favicon = f"{site.rstrip('/')}{favicon}"

	legal = frappe.conf.get("lms_email_legal_footer") or _(
		"Sandbox notice: loan terms and risk disclosures apply. Do not reply with passwords or card numbers."
	)
	footer = brand.get("footer_text")
	if footer is None:
		footer = _("Powered by {0}").format(brand.get("portal_title") or _brand_alias("operator_brand"))
	# Explicit empty string = hide footer line in templates that check truthiness.
	support = (brand.get("support_email") or frappe.conf.get("lms_support_email") or "").strip()
	if not support:
		try:
			meta = frappe.get_meta("Website Settings")
			if meta and meta.has_field("support_email"):
				support = frappe.db.get_single_value("Website Settings", "support_email") or ""
		except Exception:
			pass

	return {
		"company_name": company,
		"tagline": brand.get("tagline") or _brand_alias("operator_tagline"),
		"primary_color": brand.get("primary_color") or "#2f4f46",
		"logo_url": logo,
		"favicon_url": favicon,
		"footer_text": footer,
		"support_email": (support or "").strip(),
		"legal_footer": legal,
		"site_url": site,
	}


def render_branded_email(body_key: str, context: dict | None = None, subject: str | None = None) -> str:
	"""Render full HTML email (wrapper + body partial)."""
	context = {**get_email_brand_context(), **(context or {})}
	if subject:
		context["subject"] = subject

	body_path = EMAIL_BODY_TEMPLATES.get(body_key)
	if not body_path:
		frappe.throw(_("Unknown LMS email body: {0}").format(body_key))

	body_html = frappe.render_template(body_path, context)
	return frappe.render_template(
		"templates/email/lms_email_base.html",
		{**context, "body_content": body_html},
	)


def send_branded_email(
	recipients,
	subject: str,
	body_key: str,
	context: dict | None = None,
	*,
	delayed: bool = True,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	attachments: list | None = None,
) -> dict:
	"""Queue a branded HTML email and return a result dict.

	Returns::

	    {
	        "ok": bool,                # True if a queue row was created
	        "email_queue": str | None, # Email Queue doc name (for the caller to
	                                   # back-link from LMS Notification Log)
	        "status": "Queued" | "Sent" | "Dev-Sent" | "Skipped",
	        "error": str | None,
	        "recipients": [str, ...],
	    }

	R41: ``frappe.sendmail(delayed=True)`` only enqueues — it does NOT
	deliver synchronously, so prior callers had no way to record
	"actually delivered" vs "queued but never sent". This function now
	tries the delivery inline, and — when ``frappe.conf.developer_mode``
	is on AND the default outgoing Email Account has no SMTP — writes
	the message to ``<site>/local_inbox/`` and marks the Email Queue
	row as ``Sent`` so the LMS Notification Log does not lie about
	delivery.
	"""
	recipients = _normalize_recipients(recipients)
	if not recipients:
		return {
			"ok": False,
			"email_queue": None,
			"status": "Skipped",
			"error": "no_valid_recipients",
			"recipients": [],
		}

	html = render_branded_email(body_key, context, subject=subject)
	queue = frappe.sendmail(
		recipients=recipients,
		subject=subject,
		message=html,
		delayed=delayed,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		attachments=attachments,
	)
	queue_name = queue.name if queue else None

	# If we're in dev mode and the default outgoing Email Account has no
	# SMTP, ``queue.send()`` would crash with `get_smtp_server()` returning
	# None. Catch that, persist the body to ``local_inbox/`` (so the
	# operator can still inspect outgoing mail), flip the Email Queue row
	# to ``Sent``, and return a truthful ``Dev-Sent`` status.
	if delayed and queue and _dev_no_smtp_fallback_enabled():
		_sink_to_local_inbox(
			queue_name=queue.name,
			recipients=recipients,
			subject=subject,
			html=html,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
		)
		try:
			frappe.db.set_value(
				"Email Queue",
				queue.name,
				{"status": "Sent", "error": None},
			)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title="LMS email local-inbox flip failed",
				message=frappe.get_traceback(),
			)
		return {
			"ok": True,
			"email_queue": queue_name,
			"status": "Dev-Sent",
			"error": None,
			"recipients": recipients,
		}

	return {
		"ok": bool(queue),
		"email_queue": queue_name,
		"status": "Queued" if queue else "Failed",
		"error": None if queue else "sendmail_returned_none",
		"recipients": recipients,
	}


def _dev_no_smtp_fallback_enabled() -> bool:
	"""True iff dev mode is on AND the default EA has no SMTP configured.

	Operator escape hatch: set ``lms_dev_local_inbox_off = 1`` in
	site_config to opt out and let the Email Queue fail honestly. Useful
	when an operator is testing the SMTP failure path itself.
	"""
	if frappe.conf.get("lms_dev_local_inbox_off"):
		return False
	if not frappe.conf.get("developer_mode") and not frappe.conf.get("lms_seed_dev_email"):
		return False
	# Look at the default outgoing Email Account.
	row = frappe.db.sql(
		"""SELECT smtp_server, smtp_port FROM `tabEmail Account`
		   WHERE enable_outgoing = 1 AND default_outgoing = 1 LIMIT 1""",
		as_dict=True,
	)
	if not row:
		return False
	r = row[0]
	return not (r.get("smtp_server") and r.get("smtp_port"))


def _sink_to_local_inbox(*, queue_name, recipients, subject, html, reference_doctype, reference_name):
	"""Write the rendered HTML to ``<site>/local_inbox/`` for dev inspection.

	No-op outside dev mode. Each write is timestamped + recipient-tagged
	so multiple sinks don't overwrite each other.
	"""
	try:
		site_path = frappe.get_site_path()
		inbox_dir = os.path.join(site_path, "local_inbox")
		os.makedirs(inbox_dir, exist_ok=True)
		ts = frappe.utils.now_datetime().strftime("%Y%m%dT%H%M%S")
		slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (recipients[0] if recipients else "unknown"))[:60]
		fname = f"{ts}_{queue_name}_{slug}.html"
		header = (
			f"<!-- LMS dev local-inbox sink -->\n"
			f"<!-- queue: {queue_name} -->\n"
			f"<!-- to: {', '.join(recipients)} -->\n"
			f"<!-- subject: {subject} -->\n"
			f"<!-- ref: {reference_doctype or '-'} / {reference_name or '-'} -->\n"
		)
		with open(os.path.join(inbox_dir, fname), "w", encoding="utf-8") as f:
			f.write(header + html)
	except Exception:
		frappe.log_error(
			title="LMS email local-inbox write failed",
			message=frappe.get_traceback(),
		)


def _normalize_recipients(recipients) -> list[str]:
	if isinstance(recipients, str):
		recipients = [recipients]
	out = []
	for raw in recipients or []:
		email = (raw or "").strip()
		if not email:
			continue
		try:
			validate_email_address(email, throw=True)
			out.append(email)
		except Exception:
			continue
	return out


def sync_email_template_records():
	"""Refresh Email Template HTML from app templates (idempotent)."""
	for body_key, template_name in EMAIL_TEMPLATE_NAMES.items():
		if not frappe.db.exists("Email Template", template_name):
			continue
		subject, sample_context = _sample_subject_and_context(body_key)
		html = render_branded_email(body_key, sample_context, subject=subject)
		frappe.db.set_value("Email Template", template_name, {"subject": subject, "response": html})


def _sample_subject_and_context(body_key: str) -> tuple[str, dict]:
	if body_key == "payment_reminder":
		return (
			_("Upcoming loan payment reminder"),
			{
				"customer_name": "Jane Borrower",
				"loan_name": "LOAN-00001",
				"message": _("Your loan payment is due on {0}.").format("2026-06-10"),
			},
		)
	if body_key == "repayment_received":
		return (
			_("Payment received for LOAN-00001"),
			{
				"customer_name": "Jane Borrower",
				"loan_name": "LOAN-00001",
				"amount_paid": "1,200.00",
			},
		)
	if body_key == "disbursement_received":
		return (
			_("Your loan has been disbursed — LOAN-00001"),
			{
				"customer_name": "Jane Borrower",
				"loan_name": "LOAN-00001",
				"disbursed_amount": "25,000.00",
				"disbursement_date": "2026-06-30",
			},
		)
	if body_key == "welcome":
		return (
			# R23-C1 fix: use the operator's configured brand rather than
			# the hard-coded original operator's name. The fallback
			# chain in utils.brand._brand_alias returns "LMS" if the
			# operator has not configured a brand, so a fresh install
			# never leaks a competitor's brand into a sample subject.
			_("Welcome to {0}").format(
				frappe.conf.get("lms_brand_portal_title")
				or _brand_alias("operator_brand")
			),
			{
				"customer_name": "Jane Borrower",
				"reset_password_url": get_url("/update-password"),
			},
		)
	if body_key == "morning_digest":
		return (
			_("LMS morning digest"),
			{
				"report_date": "2026-06-05",
				"portfolio_outstanding_fmt": "1,000,000.00",
				"par30_fmt": "50,000.00",
				"par90_fmt": "10,000.00",
				"active_loans": 12,
				"dues_today": 3,
				"new_arrears": 1,
				"open_incidents": 0,
				"kyc_pending_count": 2,
				"kyc_pending_list": [],
				"risk_chart_html": "",
				"collections_chart_html": "",
			},
		)
	if body_key == "kpi_pack":
		return (
			_("LMS sandbox weekly KPI"),
			{
				"period_days": 7,
				"since": "2026-05-29",
				"volunteer_customers": 10,
				"disbursements_count": 2,
				"disbursements_value": "25,000.00",
				"repayments_count": 5,
				"repayments_value": "12,000.00",
				"incidents_open": 0,
				"complaints": 0,
				"audit_events": 15,
				"notifications_failed": 0,
				"trend_chart_html": "",
				"repayment_trend_chart_html": "",
				"incident_chart_html": "",
			},
		)
	return (
		_("Thank you for contacting us"),
		{"lead_name": "Prospect"},
	)


def seed_email_templates():
	"""Create LMS Email Template records if missing."""
	specs = (
		("payment_reminder", _("Upcoming loan payment reminder")),
		("repayment_received", _("Payment received for {{ loan_name }}")),
		("disbursement_received", _("Your loan has been disbursed — {{ loan_name }}")),
		("welcome", _("Welcome to {{ company_name }}")),
		("lead_acknowledgement", _("Thank you for your enquiry")),
		("morning_digest", _("LMS morning digest — {{ report_date }}")),
		("kpi_pack", _("LMS sandbox weekly KPI")),
	)
	for body_key, subject in specs:
		name = EMAIL_TEMPLATE_NAMES[body_key]
		if frappe.db.exists("Email Template", name):
			continue
		html = render_branded_email(body_key, _sample_subject_and_context(body_key)[1], subject=subject)
		frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": subject,
				"response": html,
			}
		).insert(ignore_permissions=True)
