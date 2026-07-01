"""Branded HTML email rendering and dispatch for LMS."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import get_url, validate_email_address

from lms_saas.utils.brand import enrich_brand, get_brand_favicon_url, get_brand_logo_url

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
	"""Brand tokens for email templates (logo URL must be absolute for clients)."""
	brand = enrich_brand()
	company = brand.get("company_name") or brand.get("portal_title") or "Kesari"
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
	footer = brand.get("footer_text") or _("Powered by Kesari")
	support = brand.get("support_email") or ""
	if not support:
		try:
			meta = frappe.get_meta("Website Settings")
			has_support_field = bool(meta and meta.has_field("support_email"))
		except Exception:
			has_support_field = False
		if has_support_field:
			try:
				support = frappe.db.get_single_value("Website Settings", "support_email") or ""
			except Exception:
				pass

	return {
		"company_name": company,
		"tagline": brand.get("tagline") or _("Stewardship in every repayment"),
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
):
	"""Queue a branded HTML email. Returns False when no valid recipients."""
	recipients = _normalize_recipients(recipients)
	if not recipients:
		return False

	html = render_branded_email(body_key, context, subject=subject)
	frappe.sendmail(
		recipients=recipients,
		subject=subject,
		message=html,
		delayed=delayed,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		attachments=attachments,
	)
	return True


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
			_("Welcome to {0}").format("Kesari"),
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
