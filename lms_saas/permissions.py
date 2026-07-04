import frappe


def has_loan_permission(doc, ptype, user):
    if frappe.session.user == "Administrator":
        return True
    customer = _portal_customer(user)
    if not customer:
        return False
    return doc.applicant_type == "Customer" and doc.applicant == customer


def has_loan_application_permission(doc, ptype, user):
    if frappe.session.user == "Administrator":
        return True
    customer = _portal_customer(user)
    if not customer:
        return False
    return doc.applicant_type == "Customer" and doc.applicant == customer


def has_loan_repayment_permission(doc, ptype, user):
    if frappe.session.user == "Administrator":
        return True
    customer = _portal_customer(user)
    if not customer:
        return False
    applicant_type, applicant = frappe.db.get_value(
        "Loan", doc.against_loan, ["applicant_type", "applicant"]
    ) or (None, None)
    return applicant_type == "Customer" and applicant == customer


def _portal_customer(user):
    contact = frappe.db.get_value("Contact", {"user": user}, "name")
    if not contact:
        contact = frappe.db.get_value("Contact", {"email_id": user}, "name")
    if not contact:
        email = frappe.db.get_value("User", user, "email")
        if email:
            contact = frappe.db.get_value("Contact", {"email_id": email}, "name")
    if not contact:
        return None
    links = frappe.get_all(
        "Dynamic Link",
        filters={"parenttype": "Contact", "parent": contact, "link_doctype": "Customer"},
        pluck="link_name",
    )
    return links[0] if links else None
