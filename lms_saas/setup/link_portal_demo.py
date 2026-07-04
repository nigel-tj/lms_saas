"""Link Administrator contact to demo customer for portal preview."""

import frappe


def run(customer="Test Borrower One", user="Administrator"):
	contact = frappe.db.get_value("Contact", {"user": user}, "name")
	if not contact:
		email = frappe.db.get_value("User", user, "email")
		contact = frappe.db.get_value("Contact", {"email_id": email}) if email else None
	if not contact:
		contact = frappe.db.get_value("Contact", {"name": user})
	if not contact:
		frappe.throw(f"No Contact for user {user}")
	doc = frappe.get_doc("Contact", contact)
	if not any(l.link_doctype == "Customer" and l.link_name == customer for l in doc.links):
		doc.append("links", {"link_doctype": "Customer", "link_name": customer})
		doc.save(ignore_permissions=True)
		frappe.db.commit()
	print(f"Linked {contact} -> {customer}")
