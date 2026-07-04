import frappe
from frappe.model.document import Document


class LMSInvestorTransaction(Document):
    def validate(self):
        set_investor_accounts(self)


def set_investor_accounts(doc, method=None):
    if not doc.investor:
        return

    investor = frappe.db.get_value(
        "LMS Investor",
        doc.investor,
        ["company", "investor_liability_account"],
        as_dict=True,
    )
    if not investor:
        frappe.throw(f"LMS Investor {doc.investor} not found")

    doc.company = investor.company
    doc.investor_liability_account = investor.investor_liability_account
