"""CRM hooks — lead consent, conversion to borrower, branded follow-up."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

from lms_saas.utils.email import send_branded_email


def validate_lead(doc, method=None):
	"""Require marketing consent before outbound CRM email or conversion."""
	if doc.get("custom_consent_given") and not doc.get("custom_consent_date"):
		doc.custom_consent_date = now_datetime()

	if doc.get("custom_consent_date") and not doc.get("custom_consent_given"):
		frappe.throw(_("Enable Customer Consent Given when a consent date is recorded."))


def on_lead_created(doc, method=None):
	"""Desk alert + branded acknowledgement when consent is recorded."""
	if not doc.get("custom_consent_given"):
		return

	_notify_desk_new_lead(doc)

	if not doc.get("email_id"):
		return

	frappe.enqueue(
		"lms_saas.api.crm.send_lead_acknowledgement",
		lead_name=doc.name,
		queue="short",
	)


def _notify_desk_new_lead(doc):
	"""Alert origination roles on Desk (Notification Log) for consented leads."""
	subject = _("New lead with marketing consent: {0}").format(doc.lead_name or doc.name)
	for user in _origination_desk_users():
		try:
			frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification(
				{
					"type": "Alert",
					"document_type": "Lead",
					"document_name": doc.name,
					"subject": subject,
					"email_content": subject,
					"for_user": user,
				}
			)
		except Exception:
			frappe.log_error(title="LMS lead desk notification", message=frappe.get_traceback())


def _origination_desk_users():
	roles = ("LMS Loan Officer", "LMS Branch Manager", "LMS Admin")
	users = set()
	for role in roles:
		users.update(
			frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
		)
	return sorted(u for u in users if u not in ("Administrator", "Guest"))


def send_lead_acknowledgement(lead_name: str):
	lead = frappe.get_doc("Lead", lead_name)
	if not lead.email_id or not lead.custom_consent_given:
		return

	brand = frappe.get_attr("lms_saas.utils.email.get_email_brand_context")()
	send_branded_email(
		recipients=[lead.email_id],
		subject=_("Thank you for your enquiry — {0}").format(brand["company_name"]),
		body_key="lead_acknowledgement",
		context={"lead_name": lead.lead_name or lead.name},
		reference_doctype="Lead",
		reference_name=lead.name,
	)


@frappe.whitelist()
def convert_lead_to_borrower(lead_name: str):
	"""Convert a Lead to Customer (+ optional compliance stub) after consent."""
	lead = frappe.get_doc("Lead", lead_name)
	if not lead.custom_consent_given:
		frappe.throw(_("Record customer consent on the Lead before converting to a borrower."))

	customer_name = _create_customer_from_lead(lead)
	_ensure_borrower_compliance_stub(customer_name, lead)

	frappe.msgprint(
		_("Customer {0} created. Open LMS Borrower Compliance to complete KYC.").format(customer_name),
		indicator="green",
	)
	return {"customer": customer_name}


def _create_customer_from_lead(lead) -> str:
	"""Prefer ERPNext mapper; fall back to a minimal Customer."""
	try:
		from erpnext.crm.doctype.lead.lead import make_customer

		result = make_customer(lead.name)
		if isinstance(result, str):
			customer_name = result
		elif hasattr(result, "name"):
			customer_name = result.name
		else:
			customer_name = result.get("name") if isinstance(result, dict) else str(result)
	except Exception:
		customer_name = _manual_customer_from_lead(lead)

	if lead.get("custom_lms_branch"):
		frappe.db.set_value("Customer", customer_name, "custom_lms_branch", lead.custom_lms_branch)

	contact = frappe.db.get_value("Dynamic Link", {"link_doctype": "Customer", "link_name": customer_name, "parenttype": "Contact"}, "parent")
	if contact and lead.get("email_id"):
		frappe.db.set_value("Contact", contact, "email_id", lead.email_id)

	frappe.db.set_value("Lead", lead.name, "status", "Converted")
	return customer_name


def _manual_customer_from_lead(lead) -> str:
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": lead.lead_name or lead.company_name or lead.name,
			"customer_type": "Individual",
			"customer_group": frappe.db.get_single_value("Selling Settings", "customer_group") or "Individual",
			"territory": lead.territory or frappe.db.get_single_value("Selling Settings", "territory"),
			"email_id": lead.email_id,
			"mobile_no": lead.mobile_no,
			"custom_lms_branch": lead.get("custom_lms_branch"),
		}
	)
	customer.flags.ignore_permissions = True
	customer.insert(ignore_permissions=True)

	if lead.email_id:
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": lead.lead_name or lead.name,
				"email_id": lead.email_id,
				"mobile_no": lead.mobile_no,
				"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			}
		)
		contact.flags.ignore_permissions = True
		contact.insert(ignore_permissions=True)

	return customer.name


def _ensure_borrower_compliance_stub(customer_name: str, lead):
	"""Create a draft compliance row when national ID is known."""
	national_id = (lead.get("custom_national_id_number") or "").strip()
	if not national_id:
		return
	if frappe.db.exists("LMS Borrower Compliance", {"customer": customer_name}):
		return

	try:
		frappe.get_doc(
			{
				"doctype": "LMS Borrower Compliance",
				"customer": customer_name,
				"national_id_number": national_id,
				"kyc_status": "Pending",
				"consent_given": lead.custom_consent_given,
				"consent_date": lead.custom_consent_date,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="LMS CRM compliance stub", message=frappe.get_traceback())


def _format_repayment_amount(doc) -> str:
	company = doc.get("company") or frappe.db.get_value("Loan", doc.against_loan, "company")
	currency = frappe.db.get_value("Company", company, "default_currency") if company else None
	try:
		return frappe.utils.fmt_money(doc.amount_paid, currency=currency)
	except Exception:
		return str(doc.amount_paid)


def send_repayment_branded_email(doc, method=None):
	"""Branded thank-you email on Loan Repayment submit (Customer applicants)."""
	if doc.docstatus != 1 or doc.applicant_type != "Customer":
		return

	email = frappe.db.get_value("Customer", doc.applicant, "email_id")
	if not email:
		return

	customer_name = frappe.db.get_value("Customer", doc.applicant, "customer_name")
	send_branded_email(
		recipients=[email],
		subject=_("Payment received for {0}").format(doc.against_loan),
		body_key="repayment_received",
		context={
			"customer_name": customer_name,
			"loan_name": doc.against_loan,
			"amount_paid": _format_repayment_amount(doc),
		},
		reference_doctype=doc.doctype,
		reference_name=doc.name,
	)
