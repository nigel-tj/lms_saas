import frappe
from frappe.utils import flt

from lms_saas.utils.calculations import principal_outstanding


def execute(filters=None):
    filters = filters or {}
    company = filters.get("company")

    loan_filters = {"docstatus": 1, "status": ("in", ["Disbursed", "Active"])}
    if company:
        loan_filters["company"] = company

    loans = frappe.get_all(
        "Loan",
        filters=loan_filters,
        fields=[
            "name",
            "applicant",
            "company",
            "loan_amount",
            "total_principal_paid",
            "written_off_amount",
            "days_past_due",
            "custom_days_past_due",
            "custom_lms_branch",
            "custom_asset_classification",
        ],
    )

    columns = [
        {"label": "Loan", "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 140},
        {"label": "Borrower", "fieldname": "applicant", "fieldtype": "Dynamic Link", "width": 160},
        {"label": "Branch", "fieldname": "branch", "fieldtype": "Link", "options": "Cost Center", "width": 120},
        {"label": "Outstanding", "fieldname": "outstanding", "fieldtype": "Currency", "width": 110},
        {"label": "DPD", "fieldname": "dpd", "fieldtype": "Int", "width": 70},
        {"label": "PAR Bucket", "fieldname": "par_bucket", "fieldtype": "Data", "width": 100},
        {"label": "Classification", "fieldname": "classification", "fieldtype": "Data", "width": 140},
    ]

    data = []
    totals = {"par30": 0, "par60": 0, "par90": 0, "total": 0}

    for loan in loans:
        dpd = loan.custom_days_past_due or loan.days_past_due or 0
        outstanding = principal_outstanding(
            loan.loan_amount, loan.total_principal_paid, loan.written_off_amount
        )
        bucket = "Current"
        if dpd > 90:
            bucket = "PAR 90+"
            totals["par90"] += outstanding
        elif dpd > 60:
            bucket = "PAR 60+"
            totals["par60"] += outstanding
        elif dpd > 30:
            bucket = "PAR 30+"
            totals["par30"] += outstanding
        totals["total"] += outstanding

        data.append(
            {
                "loan": loan.name,
                "applicant": loan.applicant,
                "branch": loan.custom_lms_branch,
                "outstanding": outstanding,
                "dpd": dpd,
                "par_bucket": bucket,
                "classification": loan.custom_asset_classification,
            }
        )

    chart = {
        "data": {
            "labels": ["PAR 30+", "PAR 60+", "PAR 90+"],
            "datasets": [{"values": [totals["par30"], totals["par60"], totals["par90"]]}],
        },
        "type": "bar",
    }

    report_summary = [
        {"label": "Portfolio", "value": totals["total"], "datatype": "Currency"},
        {"label": "PAR 30+", "value": totals["par30"], "datatype": "Currency"},
        {"label": "PAR 60+", "value": totals["par60"], "datatype": "Currency"},
        {"label": "PAR 90+", "value": totals["par90"], "datatype": "Currency"},
    ]

    return columns, data, None, chart, report_summary
