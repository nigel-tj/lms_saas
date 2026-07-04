import frappe
from frappe.utils import add_days, today


def execute(filters=None):
    filters = filters or {}
    company = filters.get("company")
    days_ahead = int(filters.get("days_ahead") or 7)
    end_date = add_days(today(), days_ahead)

    schedule_parents = frappe.get_all("Loan Repayment Schedule", filters={"docstatus": 1}, pluck="name")
    if not schedule_parents:
        return _columns(), []

    rows = frappe.get_all(
        "Repayment Schedule",
        filters={
            "parent": ("in", schedule_parents),
            "parenttype": "Loan Repayment Schedule",
            "payment_date": ("between", [today(), end_date]),
        },
        fields=["parent", "payment_date", "total_payment", "principal_amount", "interest_amount"],
        order_by="payment_date asc",
    )

    # Batch fetch: map schedule parent → loan (single query)
    parent_to_loan = {
        r["name"]: r["loan"]
        for r in frappe.get_all(
            "Loan Repayment Schedule",
            filters={"name": ("in", schedule_parents)},
            fields=["name", "loan"],
        )
    }

    # Batch fetch: all loan details in one query
    loan_names = list(set(parent_to_loan.values()))
    loan_map = {}
    if loan_names:
        for loan in frappe.get_all(
            "Loan",
            filters={"name": ("in", loan_names)},
            fields=["name", "applicant", "applicant_type", "company", "custom_lms_branch"],
        ):
            loan_map[loan.name] = loan

    # Batch fetch: customer contacts
    customer_names = [l.applicant for l in loan_map.values() if l.applicant_type == "Customer"]
    customer_mobiles = {}
    if customer_names:
        for c in frappe.get_all(
            "Customer", filters={"name": ("in", customer_names)}, fields=["name", "mobile_no"]
        ):
            customer_mobiles[c.name] = c.mobile_no

    columns = _columns()
    data = []

    for row in rows:
        loan_name = parent_to_loan.get(row.parent)
        if not loan_name:
            continue

        loan = loan_map.get(loan_name)
        if not loan:
            continue
        if company and loan.company != company:
            continue

        mobile = customer_mobiles.get(loan.applicant, "") if loan.applicant_type == "Customer" else ""
        amount = row.total_payment or (row.principal_amount or 0) + (row.interest_amount or 0)

        data.append(
            {
                "loan": loan_name,
                "borrower": loan.applicant,
                "branch": loan.custom_lms_branch,
                "due_date": row.payment_date,
                "amount": amount,
                "mobile": mobile,
            }
        )

    return columns, data


def _columns():
    return [
        {"label": "Due Date", "fieldname": "due_date", "fieldtype": "Date", "width": 100},
        {"label": "Loan", "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 130},
        {"label": "Borrower", "fieldname": "borrower", "fieldtype": "Data", "width": 160},
        {"label": "Branch", "fieldname": "branch", "fieldtype": "Link", "options": "Cost Center", "width": 120},
        {"label": "Amount", "fieldname": "amount", "fieldtype": "Currency", "width": 100},
        {"label": "Mobile", "fieldname": "mobile", "fieldtype": "Data", "width": 120},
    ]


def _contact_for_applicant(applicant_type, applicant):
    if applicant_type == "Customer":
        return frappe.db.get_value("Customer", applicant, "mobile_no")
    if applicant_type == "Employee":
        return frappe.db.get_value("Employee", applicant, "cell_number")
    return None
