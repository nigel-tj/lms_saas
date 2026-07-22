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
    """Resolve the Customer linked to a portal user.

    Resolution order (first hit wins):
    1. Contact.user → Dynamic Link → Customer (classic portal link)
    2. Contact.email_id (user name or User.email) → Dynamic Link → Customer
    3. Customer Portal User child table (ERPNext ``portal_users``) when present
    4. Customer.email_id matching the user's email (last-resort seed/demo path)
    """
    contact = frappe.db.get_value("Contact", {"user": user}, "name")
    if not contact:
        contact = frappe.db.get_value("Contact", {"email_id": user}, "name")
    email = frappe.db.get_value("User", user, "email")
    if not contact and email:
        contact = frappe.db.get_value("Contact", {"email_id": email}, "name")
    if contact:
        links = frappe.get_all(
            "Dynamic Link",
            filters={"parenttype": "Contact", "parent": contact, "link_doctype": "Customer"},
            pluck="link_name",
        )
        if links:
            return links[0]

    # ERPNext Customer → Portal Users child table (set via Desk "Portal User").
    # Linking a portal user here does not always create a Contact Dynamic Link,
    # so borrowers can end up with "No Customer linked" after a Desk link.
    if frappe.db.table_exists("Portal User"):
        portal_customer = frappe.db.get_value(
            "Portal User",
            {"user": user, "parenttype": "Customer"},
            "parent",
        )
        if portal_customer:
            return portal_customer

    # Last resort: Customer.email_id matches the portal user's email.
    if email and frappe.get_meta("Customer").has_field("email_id"):
        by_email = frappe.db.get_value("Customer", {"email_id": email}, "name")
        if by_email:
            return by_email

    return None
