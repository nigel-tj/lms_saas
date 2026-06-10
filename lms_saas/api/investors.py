import frappe


def post_investor_gl_entry(doc, method):
    """
    Generates double-entry transaction when an investor record ledger is submitted.
    Maps to Investor Liability Account vs. Company Default Bank/Cash Account.
    """
    company = doc.company
    liability_account = doc.investor_liability_account

    if not company or not liability_account:
        frappe.throw("Company and Investor Liability Account are required before submit.")

    bank_account = _get_company_liquid_account(company)

    if not bank_account:
        frappe.throw(f"Please configure a Bank or Cash Account for company {company}")

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.company = company
    je.posting_date = doc.posting_date
    je.user_remark = f"Automated ledger posting for Investor Transaction: {doc.name}"

    if doc.transaction_type == "Credit":
        je.append(
            "accounts",
            {
                "account": bank_account,
                "debit_in_account_currency": doc.amount,
                "credit_in_account_currency": 0,
            },
        )
        je.append(
            "accounts",
            {
                "account": liability_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": doc.amount,
            },
        )
    elif doc.transaction_type == "Debit":
        je.append(
            "accounts",
            {
                "account": liability_account,
                "debit_in_account_currency": doc.amount,
                "credit_in_account_currency": 0,
            },
        )
        je.append(
            "accounts",
            {
                "account": bank_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": doc.amount,
            },
        )

    je.insert(ignore_permissions=True)
    je.submit()

    doc.db_set("reference_journal_entry", je.name)


def _get_company_liquid_account(company):
    for account_type in ("Bank", "Cash"):
        account = frappe.db.get_value(
            "Account",
            {"account_type": account_type, "company": company, "is_group": 0},
            "name",
        )
        if account:
            return account
    return None


def cancel_investor_gl_entry(doc, method):
    if doc.reference_journal_entry:
        je = frappe.get_doc("Journal Entry", doc.reference_journal_entry)
        if je.docstatus == 1:
            je.cancel()
