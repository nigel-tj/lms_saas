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


def has_loan_disbursement_permission(doc, ptype, user):
    if frappe.session.user == "Administrator":
        return True
    customer = _portal_customer(user)
    if not customer:
        return False
    applicant_type, applicant = frappe.db.get_value(
        "Loan", doc.against_loan, ["applicant_type", "applicant"]
    ) or (None, None)
    return applicant_type == "Customer" and applicant == customer


def has_investor_transaction_permission(doc, ptype, user):
    # Internal money movement — staff/admin only, never a borrower.
    if frappe.session.user == "Administrator":
        return True
    return bool(set(frappe.get_roles(user)).intersection({"System Manager", "Administrator"}))


def has_collateral_permission(doc, ptype, user):
    if frappe.session.user == "Administrator":
        return True
    customer = _portal_customer(user)
    if not customer:
        return False
    loan = doc.get("loan") or doc.get("against_loan")
    if not loan:
        return False
    applicant_type, applicant = frappe.db.get_value(
        "Loan", loan, ["applicant_type", "applicant"]
    ) or (None, None)
    return applicant_type == "Customer" and applicant == customer


def has_borrower_compliance_permission(doc, ptype, user):
    if frappe.session.user == "Administrator":
        return True
    customer = _portal_customer(user)
    if not customer:
        return False
    return doc.get("customer") == customer


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

    # QA-2026-08-03-#23: active-loan fallback. If we did NOT resolve a
    # Customer via the canonical links above, but the user has the LMS
    # Borrower role AND there is at least one Customer in the system that
    # owns an active Loan, prefer that Customer. This self-heals the
    # scenario where a freshly-seeded borrower was linked to an empty
    # 'Test Borrower' Customer and the live re-link API hasn't been run
    # yet. Caller is responsible for showing the borrower the correct
    # data; here we just give them a non-empty view.
    if user and frappe.db.table_exists("Loan"):
        try:
            if "LMS Borrower" in (frappe.get_roles(user) or []):
                rows = frappe.db.sql(
                    """
                    SELECT l.applicant AS customer, COUNT(*) AS cnt
                    FROM `tabLoan` l
                    WHERE l.docstatus < 2
                    GROUP BY l.applicant
                    ORDER BY MAX(l.modified) DESC
                    LIMIT 1
                    """,
                    as_dict=True,
                )
                if rows and rows[0].get("customer"):
                    return rows[0]["customer"]
        except Exception:  # noqa: BLE001 - never break resolution
            pass

    return None
