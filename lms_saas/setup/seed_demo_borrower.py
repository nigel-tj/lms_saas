"""Seed the demo portal users — KYC profile + Customer + branch linkage.

Idempotent: re-run any time and it tops up the demo borrower's
``LMS Borrower Compliance`` row, the ``Customer.email_id`` field, and
the demo Contact so the borrower can log in and apply for a loan.
Also ensures demo staff (officer, manager, collector) have a branch
assigned so their portal pages don't throw "No branch assigned".

Origin: R31 (manual user-simulation) surfaced that the demo borrower
``demo.lms.borrower@example.com`` could log in but had no KYC profile,
so the apply wizard's "Start KYC" button threw
``No KYC profile linked. Contact your loan officer to set one up.``
R32 surfaced that the demo collector/officer had no branch, so the
collector portal threw ``No branch assigned — cannot view run sheet.``

Run:
    bench --site lms.localhost execute lms_saas.setup.seed_demo_borrower.run
"""

from __future__ import annotations

import frappe


DEMO_EMAIL = "demo.lms.borrower@example.com"
DEMO_CUSTOMER_NAME = "Demo Borrower - 1"
DEMO_NATIONAL_ID = "DEMO-BORROWER-001"


def run() -> dict:
	frappe.set_user("Administrator")
	frappe.flags.ignore_permissions = True

	# 1. Resolve the demo user's customer.
	customer = _resolve_demo_customer()
	if not customer:
		return {"ok": False, "reason": "demo borrower Customer not found"}

	# 2. Populate the Customer's email_id so the resolver fallback
	#    (Customer.email_id matching the portal user's email) is robust.
	if not customer.email_id:
		customer.email_id = DEMO_EMAIL
		customer.flags.ignore_permissions = True
		customer.save(ignore_permissions=True)

	# 3. Ensure LMS Borrower Compliance exists.
	comp_name = frappe.db.get_value(
		"LMS Borrower Compliance", {"customer": customer.name}, "name"
	)
	if not comp_name:
		from frappe.utils import now_datetime
		doc = frappe.new_doc("LMS Borrower Compliance")
		doc.customer = customer.name
		doc.national_id_number = DEMO_NATIONAL_ID
		doc.kyc_status = "Approved"
		doc.credit_score = 720
		doc.consent_given = 1
		doc.consent_date = now_datetime()
		doc.aml_status = "Clear"
		doc.aml_screened_at = now_datetime()
		doc.aml_risk_level = "Low"
		# Use the same fixture file paths as seed_demo._demo_compliance_fields.
		doc.id_document_proof = "/files/demo_id_proof.txt"
		doc.proof_of_address = "/files/demo_proof_of_address.txt"
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		comp_name = doc.name

	# 4. Make sure the demo user has a Contact + Dynamic Link to the Customer.
	contact = frappe.db.get_value("Contact", {"user": DEMO_EMAIL}, "name")
	if not contact:
		contact = frappe.db.get_value("Contact", {"email_id": DEMO_EMAIL}, "name")
	if not contact:
		contact = frappe.new_doc("Contact")
		contact.first_name = "Demo"
		contact.last_name = "Borrower"
		contact.user = DEMO_EMAIL
		contact.is_primary_contact = 1
		contact.append("email_ids", {"email_id": DEMO_EMAIL, "is_primary": 1})
		contact.flags.ignore_permissions = True
		contact.insert(ignore_permissions=True)
	# Ensure the Dynamic Link points to the customer.
	if contact:
		has_link = frappe.db.exists(
			"Dynamic Link",
			{
				"parent": contact,
				"parenttype": "Contact",
				"link_doctype": "Customer",
				"link_name": customer.name,
			},
		)
		if not has_link:
			from frappe.contacts.doctype.contact.contact import add_contact
			add_contact(
				contact, "Customer", customer.name, link_is_primary=1
			)

	# 5. Ensure demo staff have a branch assigned so their portal pages
	#    don't throw "No branch assigned" (R32).
	_ensure_demo_staff_branches()

	frappe.db.commit()
	return {
		"ok": True,
		"customer": customer.name,
		"compliance": comp_name,
		"contact": contact,
	}


def _ensure_demo_staff_branches() -> None:
	"""R32: assign Main Branch to demo officer/manager/collector if missing."""
	branch = frappe.db.get_value("Cost Center", {"is_group": 0, "name": "Main Branch - LMS"}, "name")
	if not branch:
		branch = frappe.db.get_value("Cost Center", {"is_group": 0}, "name")
	if not branch:
		return

	branch_hr = "Main Branch"
	for email in ("demo.lms.officer@example.com", "demo.lms.branch@example.com", "demo.lms.collector@example.com"):
		emp_name = frappe.db.get_value("Employee", {"user_id": email}, "name")
		if not emp_name:
			continue
		emp = frappe.get_doc("Employee", emp_name)
		changed = False
		if not emp.branch:
			emp.branch = branch_hr
			changed = True
		if not emp.custom_lms_branch:
			emp.custom_lms_branch = branch
			changed = True
		if changed:
			emp.flags.ignore_permissions = True
			emp.save(ignore_permissions=True)


def _resolve_demo_customer() -> "frappe.model.document.Document | None":
	# 1. Direct lookup by name.
	if frappe.db.exists("Customer", DEMO_CUSTOMER_NAME):
		return frappe.get_doc("Customer", DEMO_CUSTOMER_NAME)
	# 2. Contact link.
	for c in frappe.get_all(
		"Dynamic Link",
		filters={
			"parenttype": "Contact",
			"link_doctype": "Customer",
			"link_name": ["is", "set"],
		},
		fields=["parent"],
		limit=200,
	):
		contact = frappe.get_doc("Contact", c.parent)
		if contact.user == DEMO_EMAIL or contact.email_id == DEMO_EMAIL:
			if contact.links:
				return frappe.get_doc("Customer", contact.links[0].link_name)
	# 3. Email-id fallback.
	by_email = frappe.db.get_value("Customer", {"email_id": DEMO_EMAIL}, "name")
	if by_email:
		return frappe.get_doc("Customer", by_email)
	return None
