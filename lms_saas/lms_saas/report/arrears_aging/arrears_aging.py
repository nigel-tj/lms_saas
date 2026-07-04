import frappe
from frappe.utils import flt

from lms_saas.utils.calculations import par_bucket, principal_outstanding
from lms_saas.utils.charts import to_frappe_report_chart


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
            "custom_lms_branch",
            "days_past_due",
            "custom_days_past_due",
            "loan_amount",
            "total_principal_paid",
            "written_off_amount",
        ],
    )

    columns = [
        {"label": "Loan", "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 140},
        {"label": "Borrower", "fieldname": "applicant", "fieldtype": "Data", "width": 160},
        {"label": "Branch", "fieldname": "branch", "fieldtype": "Link", "options": "Cost Center", "width": 120},
        {"label": "DPD", "fieldname": "dpd", "fieldtype": "Int", "width": 80},
        {"label": "Aging Bucket", "fieldname": "bucket", "fieldtype": "Data", "width": 120},
        {"label": "Principal", "fieldname": "principal", "fieldtype": "Currency", "width": 110},
    ]

    data = []
    bucket_totals = {}
    for loan in loans:
        dpd = loan.custom_days_past_due or loan.days_past_due or 0
        bucket = par_bucket(dpd)
        principal = principal_outstanding(
            loan.loan_amount, loan.total_principal_paid, loan.written_off_amount
        )
        bucket_totals[bucket] = bucket_totals.get(bucket, 0) + principal

        data.append(
            {
                "loan": loan.name,
                "applicant": loan.applicant,
                "branch": loan.custom_lms_branch,
                "dpd": dpd,
                "bucket": bucket,
                "principal": principal,
            }
        )

    labels = sorted(bucket_totals.keys(), key=_bucket_sort_key)
    chart = to_frappe_report_chart(
        labels,
        [flt(bucket_totals.get(label)) for label in labels],
        chart_type="bar",
    )

    return columns, data, None, chart


def _bucket_sort_key(label):
    order = {
        "0 - Current": 0,
        "1-30 Days": 1,
        "31-60 Days": 2,
        "61-90 Days": 3,
        "90+ Days": 4,
    }
    return order.get(label, 99)
