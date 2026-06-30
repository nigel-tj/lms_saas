"""Loan disbursement hooks."""

import frappe
from frappe import _
from frappe.utils import formatdate, getdate


def notify_disbursed(doc, method=None):
	try:
		from lms_saas.api.webhooks import dispatch_webhook_event

		dispatch_webhook_event(
			"loan.disbursed",
			{
				"disbursement": doc.name,
				"loan": doc.against_loan,
				"amount": doc.disbursed_amount,
				"company": doc.company,
			},
		)
	except Exception:
		pass

	send_disbursement_branded_email(doc, method=method)


def send_disbursement_branded_email(doc, method=None):
	"""Branded disbursement confirmation email to the borrower (Customer applicants)."""
	if doc.docstatus != 1 or doc.applicant_type != "Customer":
		return

	email = frappe.db.get_value("Customer", doc.applicant, "email_id")
	if not email:
		return

	customer_name = frappe.db.get_value("Customer", doc.applicant, "customer_name")
	company = doc.get("company") or frappe.db.get_value("Loan", doc.against_loan, "company")
	currency = frappe.db.get_value("Company", company, "default_currency") if company else None
	try:
		disbursed_fmt = frappe.utils.fmt_money(doc.disbursed_amount, currency=currency)
	except Exception:
		disbursed_fmt = str(doc.disbursed_amount)

	disbursement_date = formatdate(getdate(doc.posting_date)) if doc.posting_date else ""

	from lms_saas.utils.email import send_branded_email

	send_branded_email(
		recipients=[email],
		subject=_("Your loan has been disbursed — {0}").format(doc.against_loan),
		body_key="disbursement_received",
		context={
			"customer_name": customer_name,
			"loan_name": doc.against_loan,
			"disbursed_amount": disbursed_fmt,
			"disbursement_date": disbursement_date,
		},
		reference_doctype=doc.doctype,
		reference_name=doc.name,
	)
