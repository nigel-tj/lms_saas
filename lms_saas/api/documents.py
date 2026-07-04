import os

import frappe
from docxtpl import DocxTemplate


@frappe.whitelist()
def generate_loan_agreement_pdf(loan_id):
    """Generate agreement via Print Format PDF (preferred) or fallback DOCX template."""
    if frappe.db.exists("Print Format", "LMS Loan Agreement"):
        return download_loan_agreement_pdf(loan_id)

    loan_doc = frappe.get_doc("Loan", loan_id)
    template_path = frappe.get_site_path("public", "files", "loan_template.docx")
    output_docx = frappe.get_site_path("public", "files", f"agreement_{loan_id}.docx")

    if not os.path.exists(template_path):
        frappe.throw(
            "Base template contract agreement layout file not found in public site attachments folder."
        )

    doc = DocxTemplate(template_path)
    context = {
        "loan_id": loan_doc.name,
        "borrower": loan_doc.applicant,
        "principal": loan_doc.loan_amount,
        "rate": loan_doc.rate_of_interest,
    }

    doc.render(context)
    doc.save(output_docx)

    return f"/files/agreement_{loan_id}.docx"


@frappe.whitelist()
def download_loan_agreement_pdf(loan_id):
    _check_loan_access(loan_id)
    pdf = frappe.get_print("Loan", loan_id, print_format="LMS Loan Agreement", as_pdf=True)
    frappe.local.response.filename = f"agreement_{loan_id}.pdf"
    frappe.local.response.filecontent = pdf
    frappe.local.response.type = "download"


@frappe.whitelist()
def download_loan_statement_pdf(loan_id):
    _check_loan_access(loan_id)
    pdf = frappe.get_print("Loan", loan_id, print_format="LMS Loan Statement", as_pdf=True)
    frappe.local.response.filename = f"statement_{loan_id}.pdf"
    frappe.local.response.filecontent = pdf
    frappe.local.response.type = "download"


def _check_loan_access(loan_id):
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)

    if "System Manager" in frappe.get_roles(frappe.session.user):
        return

    from lms_saas.permissions import _portal_customer

    customer = _portal_customer(frappe.session.user)
    if not customer:
        frappe.throw("Not permitted", frappe.PermissionError)

    loan = frappe.db.get_value("Loan", loan_id, ["applicant_type", "applicant"], as_dict=True)
    if not loan or loan.applicant_type != "Customer" or loan.applicant != customer:
        frappe.throw("Not permitted", frappe.PermissionError)
