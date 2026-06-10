"""Optional demo loan path: bench --site lms.localhost execute lms_saas.setup.seed_demo.run

Bulk feasibility data:
    bench --site lms.localhost execute lms_saas.setup.seed_demo.run_bulk
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_days, add_months, flt, today


def run():
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        frappe.throw("Set Global Defaults default company first.")

    customer = frappe.db.get_value("Customer", {}, "name")
    if not customer:
        frappe.throw("Create a Customer first.")

    product = frappe.db.get_value("Loan Product", {"company": company}, "name")
    if not product:
        frappe.throw("Run after_install to seed Loan Product.")

    if frappe.db.exists("Loan", {"applicant": customer, "docstatus": 1}):
        return {"skipped": "loan already exists for customer", "customer": customer}

    compliance = _ensure_compliance(customer)
    collateral = _ensure_demo_collateral(customer, company)
    application = _create_loan_application(customer, company, product, compliance, collateral)
    loan = _create_loan_from_application(application)
    _disburse_loan(loan)

    frappe.db.commit()
    return {
        "customer": customer,
        "loan_application": application,
        "loan": loan,
        "collateral": collateral,
    }


def _ensure_demo_collateral(customer, company):
    existing = frappe.db.get_value("LMS Collateral", {"owner_customer": customer, "docstatus": 1}, "name")
    if existing:
        return existing

    branch = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
    doc = frappe.get_doc(
        {
            "doctype": "LMS Collateral",
            "collateral_title": "Toyota Hilux 2019 (DEMO-COL)",
            "collateral_type": "Vehicle",
            "owner_customer": customer,
            "company": company,
            "branch": branch,
            "status": "Pledged",
            "market_value": 18000,
            "haircut_percent": 20,
            "valuation_date": today(),
            "valuer_name": "Demo Valuations Ltd",
            "reference_no": "DEMO-COL-001",
        }
    )
    doc.insert(ignore_permissions=True)
    doc.submit()
    return doc.name


def _ensure_compliance(customer):
    name = frappe.db.get_value("LMS Borrower Compliance", {"customer": customer}, "name")
    if name:
        # Ensure KYC + reqd attachments so underwriting's comp_doc.save() does not
        # fail re-validation when the loan application is submitted.
        frappe.db.set_value(
            "LMS Borrower Compliance",
            name,
            {
                "kyc_status": "Approved",
                "id_document_proof": frappe.db.get_value("LMS Borrower Compliance", name, "id_document_proof")
                or "/files/demo_id_proof.txt",
                "proof_of_address": frappe.db.get_value("LMS Borrower Compliance", name, "proof_of_address")
                or "/files/demo_address_proof.txt",
            },
        )
        return name

    doc = frappe.get_doc(
        {
            "doctype": "LMS Borrower Compliance",
            "customer": customer,
            "national_id_number": "DEMO-00001",
            "kyc_status": "Approved",
            "credit_score": 720,
            "id_document_proof": "/files/demo_id_proof.txt",
            "proof_of_address": "/files/demo_address_proof.txt",
        }
    )
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)
    return doc.name


def _create_loan_application(customer, company, product, compliance, collateral=None):
    branch = frappe.db.get_value("Cost Center", {"company": company}, "name")
    doc = frappe.get_doc(
        {
            "doctype": "Loan Application",
            "applicant_type": "Customer",
            "applicant": customer,
            "company": company,
            "loan_product": product,
            "loan_amount": 10000,
            "repayment_method": "Repay Over Number of Periods",
            "repayment_periods": 6,
            "posting_date": today(),
            "custom_lms_branch": branch,
        }
    )
    if collateral:
        doc.append("custom_collateral", {"collateral": collateral})
    doc.insert(ignore_permissions=True)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"score": 720, "dti": 0.25}
    with patch("lms_saas.api.underwriting.requests.post", return_value=mock_response):
        doc.submit()
    return doc.name


def _create_loan_from_application(application_name):
    app = frappe.get_doc("Loan Application", application_name)
    if frappe.db.exists("Loan", {"loan_application": application_name}):
        return frappe.db.get_value("Loan", {"loan_application": application_name}, "name")

    loan = frappe.get_doc(
        {
            "doctype": "Loan",
            "applicant_type": app.applicant_type,
            "applicant": app.applicant,
            "company": app.company,
            "loan_product": app.loan_product,
            "loan_application": app.name,
            "loan_amount": app.loan_amount,
            "rate_of_interest": app.rate_of_interest or frappe.db.get_value(
                "Loan Product", app.loan_product, "rate_of_interest"
            ),
            "repayment_method": app.repayment_method,
            "repayment_periods": app.repayment_periods,
            "repayment_start_date": add_months(today(), 1),
            "posting_date": today(),
            "custom_lms_branch": app.get("custom_lms_branch"),
        }
    )
    loan.insert(ignore_permissions=True)
    loan.submit()
    return loan.name


def _disburse_loan(loan_name):
    loan = frappe.get_doc("Loan", loan_name)
    if loan.status == "Disbursed":
        return

    try:
        if hasattr(loan, "create_loan_disbursement"):
            loan.create_loan_disbursement()
            return
        disbursement = frappe.get_doc(
            {
                "doctype": "Loan Disbursement",
                "against_loan": loan_name,
                "applicant_type": loan.applicant_type,
                "applicant": loan.applicant,
                "company": loan.company,
                "disbursement_date": today(),
                "disbursed_amount": loan.loan_amount,
                "posting_date": today(),
            }
        )
        disbursement.insert(ignore_permissions=True)
        disbursement.submit()
    except Exception as e:
        frappe.log_error(title="LMS seed_demo disbursement", message=str(e))


# ---------------------------------------------------------------------------
# Bulk feasibility seed: varied borrowers, branches, delinquency, repayments
# ---------------------------------------------------------------------------

DELINQUENCY_PROFILES = ("current", "current", "watchlist", "npa")


def run_bulk(count=12, with_repayments=True):
    """Seed a realistic portfolio for operational feasibility testing.

    Creates `count` borrowers spread across branches with a mix of current,
    watchlist (31-60 DPD) and NPA (90+ DPD) loans, plus partial repayments.
    Returns a summary dict with created counts and any per-borrower errors.
    """
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        frappe.throw("Set Global Defaults default company first.")

    product = frappe.db.get_value("Loan Product", {"company": company}, "name")
    if not product:
        frappe.throw("Run after_install to seed Loan Product.")

    branches = frappe.get_all(
        "Cost Center",
        filters={"company": company, "is_group": 0},
        pluck="name",
    ) or [None]

    summary = {"created_loans": 0, "repayments": 0, "errors": []}

    for i in range(1, count + 1):
        profile = DELINQUENCY_PROFILES[i % len(DELINQUENCY_PROFILES)]
        branch = branches[i % len(branches)]
        try:
            customer = _ensure_bulk_customer(i, company)
            compliance = _ensure_compliance(customer)
            frappe.db.set_value("LMS Borrower Compliance", compliance, "kyc_status", "Approved")
            loan = _create_profiled_loan(customer, company, product, branch, profile, seq=i)
            if not loan:
                continue
            summary["created_loans"] += 1
            # Repayments only validate against overdue amounts; current loans have
            # nothing due yet, so collect partial payments on delinquent loans.
            if with_repayments and profile in ("watchlist", "npa"):
                if _create_repayment(loan, company):
                    summary["repayments"] += 1
        except Exception as e:  # noqa: BLE001 - capture per-borrower failures for the report
            summary["errors"].append({"seq": i, "profile": profile, "error": str(e)})
            frappe.log_error(title=f"LMS seed_bulk borrower {i}", message=frappe.get_traceback())

    frappe.db.commit()

    # Recompute DPD / classification so PAR and Arrears reports reflect the data.
    try:
        from lms_saas.tasks import evaluate_days_past_due

        evaluate_days_past_due()
        frappe.db.commit()
    except Exception as e:  # noqa: BLE001
        summary["errors"].append({"step": "evaluate_days_past_due", "error": str(e)})

    return summary


def _ensure_bulk_customer(seq, company):
    name = f"LMS Borrower {seq:03d}"
    existing = frappe.db.get_value("Customer", {"customer_name": name}, "name")
    if existing:
        return existing

    customer_group = (
        frappe.db.get_value("Customer Group", {"customer_group_name": "Individual"}, "name")
        or frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
    )
    territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")

    doc = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": name,
            "customer_type": "Individual",
            "customer_group": customer_group,
            "territory": territory,
            "mobile_no": f"+2771{seq:07d}",
            "email_id": f"borrower{seq:03d}@example.com",
        }
    )
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)
    return doc.name


def _profile_dates(profile):
    """Return (posting_date, disbursement_date, repayment_start_date) per profile."""
    if profile == "npa":
        return add_months(today(), -6), add_months(today(), -6), add_months(today(), -5)
    if profile == "watchlist":
        return add_months(today(), -3), add_months(today(), -3), add_months(today(), -2)
    return today(), today(), add_months(today(), 1)


def _create_profiled_loan(customer, company, product, branch, profile, seq):
    if frappe.db.exists("Loan", {"applicant": customer, "docstatus": 1}):
        return frappe.db.get_value("Loan", {"applicant": customer, "docstatus": 1}, "name")

    posting_date, disb_date, start_date = _profile_dates(profile)
    loan_amount = 5000 + (seq % 8) * 2500
    periods = 6 + (seq % 4) * 3

    application = frappe.get_doc(
        {
            "doctype": "Loan Application",
            "applicant_type": "Customer",
            "applicant": customer,
            "company": company,
            "loan_product": product,
            "loan_amount": loan_amount,
            "repayment_method": "Repay Over Number of Periods",
            "repayment_periods": periods,
            "posting_date": posting_date,
            "custom_lms_branch": branch,
        }
    )
    application.insert(ignore_permissions=True)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"score": 700 + (seq % 10) * 5, "dti": 0.25}
    with patch("lms_saas.api.underwriting.requests.post", return_value=mock_response):
        application.submit()

    rate = application.rate_of_interest or frappe.db.get_value(
        "Loan Product", product, "rate_of_interest"
    )
    loan = frappe.get_doc(
        {
            "doctype": "Loan",
            "applicant_type": "Customer",
            "applicant": customer,
            "company": company,
            "loan_product": product,
            "loan_application": application.name,
            "loan_amount": loan_amount,
            "rate_of_interest": rate,
            "repayment_method": "Repay Over Number of Periods",
            "repayment_periods": periods,
            "repayment_start_date": start_date,
            "posting_date": posting_date,
            "custom_lms_branch": branch,
        }
    )
    loan.insert(ignore_permissions=True)
    loan.submit()

    _disburse_loan_on(loan.name, disb_date)
    return loan.name


def _disburse_loan_on(loan_name, disbursement_date):
    loan = frappe.get_doc("Loan", loan_name)
    if loan.status == "Disbursed":
        return
    try:
        disbursement = frappe.get_doc(
            {
                "doctype": "Loan Disbursement",
                "against_loan": loan_name,
                "applicant_type": loan.applicant_type,
                "applicant": loan.applicant,
                "company": loan.company,
                "disbursement_date": disbursement_date,
                "disbursed_amount": loan.loan_amount,
                "posting_date": disbursement_date,
            }
        )
        disbursement.insert(ignore_permissions=True)
        disbursement.submit()
    except Exception:  # noqa: BLE001
        frappe.log_error(title="LMS seed_bulk disbursement", message=frappe.get_traceback())


def _create_repayment(loan_name, company):
    loan = frappe.get_doc("Loan", loan_name)
    # Pay half an installment so the amount never exceeds the overdue balance.
    installment = flt(loan.loan_amount) / max(flt(loan.repayment_periods or 6), 1)
    amount = round(installment * 0.5, 2)
    try:
        repayment = frappe.get_doc(
            {
                "doctype": "Loan Repayment",
                "against_loan": loan_name,
                "applicant_type": loan.applicant_type,
                "applicant": loan.applicant,
                "company": company,
                "posting_date": today(),
                "amount_paid": amount,
            }
        )
        repayment.insert(ignore_permissions=True)
        repayment.submit()
        return True
    except Exception:  # noqa: BLE001
        frappe.log_error(title="LMS seed_bulk repayment", message=frappe.get_traceback())
        return False
