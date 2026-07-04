"""IFRS 9 Expected Credit Loss (ECL) provisioning report.

Stages loans (1/2/3) by days-past-due and applies a simplified provision
matrix to outstanding principal exposure. Supports branch and loan-officer
drill-down via filters. See `utils/calculations.py` for the staging logic.
"""

import frappe

from lms_saas.utils.calculations import (
    ECL_PROVISION_RATES,
    ecl_stage,
    expected_credit_loss,
    principal_outstanding,
)


def execute(filters=None):
    filters = filters or {}

    loan_filters = {"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])}
    if filters.get("company"):
        loan_filters["company"] = filters["company"]
    if filters.get("branch"):
        loan_filters["custom_lms_branch"] = filters["branch"]
    if filters.get("loan_officer"):
        loan_filters["custom_loan_officer"] = filters["loan_officer"]

    loans = frappe.get_all(
        "Loan",
        filters=loan_filters,
        fields=[
            "name",
            "applicant",
            "custom_lms_branch",
            "custom_loan_officer",
            "loan_amount",
            "total_principal_paid",
            "written_off_amount",
            "days_past_due",
            "custom_days_past_due",
        ],
    )

    columns = [
        {"label": "Loan", "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 140},
        {"label": "Borrower", "fieldname": "applicant", "fieldtype": "Data", "width": 150},
        {"label": "Branch", "fieldname": "branch", "fieldtype": "Link", "options": "Cost Center", "width": 120},
        {"label": "Officer", "fieldname": "officer", "fieldtype": "Data", "width": 120},
        {"label": "DPD", "fieldname": "dpd", "fieldtype": "Int", "width": 70},
        {"label": "Stage", "fieldname": "stage", "fieldtype": "Int", "width": 70},
        {"label": "Exposure (EAD)", "fieldname": "exposure", "fieldtype": "Currency", "width": 130},
        {"label": "ECL Rate", "fieldname": "ecl_rate", "fieldtype": "Percent", "width": 90},
        {"label": "ECL Provision", "fieldname": "provision", "fieldtype": "Currency", "width": 130},
    ]

    data = []
    stage_totals = {1: {"exposure": 0, "provision": 0}, 2: {"exposure": 0, "provision": 0}, 3: {"exposure": 0, "provision": 0}}

    for loan in loans:
        dpd = loan.custom_days_past_due or loan.days_past_due or 0
        exposure = principal_outstanding(loan.loan_amount, loan.total_principal_paid, loan.written_off_amount)
        stage = ecl_stage(dpd)
        provision = expected_credit_loss(exposure, dpd)
        stage_totals[stage]["exposure"] += exposure
        stage_totals[stage]["provision"] += provision

        data.append(
            {
                "loan": loan.name,
                "applicant": loan.applicant,
                "branch": loan.custom_lms_branch,
                "officer": loan.custom_loan_officer,
                "dpd": dpd,
                "stage": stage,
                "exposure": exposure,
                "ecl_rate": ECL_PROVISION_RATES.get(stage, 0) * 100,
                "provision": provision,
            }
        )

    total_exposure = sum(s["exposure"] for s in stage_totals.values())
    total_provision = sum(s["provision"] for s in stage_totals.values())
    coverage = (total_provision / total_exposure * 100) if total_exposure else 0

    report_summary = [
        {"label": "Total Exposure", "value": total_exposure, "datatype": "Currency"},
        {"label": "Total ECL Provision", "value": total_provision, "datatype": "Currency"},
        {"label": "Coverage Ratio", "value": coverage, "datatype": "Percent"},
        {"label": "Stage 3 Exposure", "value": stage_totals[3]["exposure"], "datatype": "Currency", "indicator": "Red"},
    ]

    chart = {
        "data": {
            "labels": ["Stage 1", "Stage 2", "Stage 3"],
            "datasets": [{"name": "ECL Provision", "values": [stage_totals[s]["provision"] for s in (1, 2, 3)]}],
        },
        "type": "bar",
    }

    return columns, data, None, chart, report_summary
