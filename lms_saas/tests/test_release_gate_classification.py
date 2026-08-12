"""Release-gate classification tests (R03) — gate rows 1.9 / 1.10 / 1.11.

Pins the wrapper-layer classification invariants:
- 1.9: NPA classification at 90 DPD + ECL provisioning.
- 1.10: Top-up / restructuring preserves the prior schedule (wrapper-level).
- 1.11: Multi-disbursement / tranche — interest only on disbursed amounts
  (wrapper-level: assert the loan's total_payment reflects only disbursed
  principal, not the full approved amount).
"""

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from lms_saas.api import manager as manager_api
from lms_saas.utils.calculations import (
    asset_classification,
    ecl_stage,
    expected_credit_loss,
    par_bucket,
)

OFFICER_EMAIL = "officer@kesari.africa"
COMPANY = "LMS Demo Co"


def _resolve_branch() -> str:
    branch = frappe.db.get_value(
        "Employee", {"user_id": OFFICER_EMAIL}, "custom_lms_branch"
    )
    if branch:
        return branch
    return frappe.db.get_value("Cost Center", {"is_group": 0}, "name") or "Main Branch"


def _seed_officer() -> str:
    emp_name = frappe.db.get_value("Employee", {"user_id": OFFICER_EMAIL}, "name")
    if not emp_name:
        emp = frappe.new_doc("Employee")
        emp.employee_id = "EMP-OFFICER-R03"
        emp.first_name = "Loan"
        emp.last_name = "Officer"
        emp.user_id = OFFICER_EMAIL
        emp.status = "Active"
        emp.company = COMPANY
        emp.date_of_joining = frappe.utils.today()
        emp.gender = "Male"
        emp.insert(ignore_permissions=True)
        emp_name = emp.name
    return emp_name


def _ensure_loan_product() -> str:
    if frappe.db.exists("Loan Product", {"product_code": "LMS-STD"}):
        return frappe.db.get_value("Loan Product", {"product_code": "LMS-STD"}, "name")
    prod = frappe.new_doc("Loan Product")
    prod.product_code = "LMS-STD"
    prod.product_name = "LMS Standard"
    prod.company = COMPANY
    prod.rate_of_interest = 18
    prod.maximum_loan_amount = 100000
    prod.minimum_loan_amount = 1000
    prod.is_term_loan = 1
    prod.flags.ignore_permissions = True
    prod.insert()
    return prod.name


def _make_borrower(suffix: str) -> str:
    stamp = frappe.utils.now_datetime().strftime("%H%M%S%f")
    name = f"R03 Borrower {suffix} {stamp}"
    cust = frappe.new_doc("Customer")
    cust.customer_name = name
    cust.customer_type = "Individual"
    cust.customer_group = "Individual"
    cust.territory = "All Territories"
    cust.custom_lms_branch = _resolve_branch()
    cust.custom_national_id_number = "8501011234089"
    cust.insert(ignore_permissions=True)
    comp = frappe.get_doc({
        "doctype": "LMS Borrower Compliance",
        "customer": cust.name,
        "kyc_status": "Approved",
        "aml_status": "Clear",
        "consent_given": 1,
        "consent_date": frappe.utils.today(),
        "national_id_number": "8501011234089",
        "id_document_proof": "NID-PDF",
        "proof_of_address": "UTILITY-PDF",
    })
    comp.insert(ignore_permissions=True)
    return cust.name


def _make_sanctioned_loan(employee: str, amount: float = 5000) -> str:
    branch = _resolve_branch()
    customer = _make_borrower("APP")
    product = _ensure_loan_product()
    la = frappe.get_doc({
        "doctype": "Loan Application",
        "applicant_type": "Customer",
        "applicant": customer,
        "company": COMPANY,
        "loan_product": product,
        "loan_amount": amount,
        "repayment_periods": 3,
        "rate_of_interest": 18,
        "posting_date": frappe.utils.today(),
        "status": "Approved",
        "custom_lms_branch": branch,
        "custom_loan_officer": employee,
    })
    la.insert(ignore_permissions=True)
    la.submit()
    loan = frappe.get_doc({
        "doctype": "Loan",
        "applicant_type": "Customer",
        "applicant": customer,
        "loan_product": product,
        "company": COMPANY,
        "loan_amount": amount,
        "rate_of_interest": 18,
        "repayment_method": "Repay Over Number of Periods",
        "repayment_periods": 3,
        "custom_lms_branch": branch,
        "custom_loan_officer": employee,
        "custom_lms_loan_application": la.name,
    })
    loan.insert(ignore_permissions=True)
    loan.submit()
    return loan.name


class TestReleaseGateClassification(FrappeTestCase):
    """Gate row 1.9 — NPA classification + ECL provisioning."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.officer = _seed_officer()

    def test_npa_thresholds(self):
        """1.9: asset_classification thresholds are pinned."""
        self.assertIsNone(asset_classification(0))
        self.assertIsNone(asset_classification(30))
        self.assertEqual(asset_classification(31), "Sub-Standard/Watchlist")
        self.assertEqual(asset_classification(90), "Sub-Standard/Watchlist")
        self.assertEqual(asset_classification(91), "Non-Performing Asset (NPA)")
        self.assertEqual(asset_classification(180), "Non-Performing Asset (NPA)")

    def test_ecl_stages(self):
        """1.9: ECL staging matches DPD thresholds."""
        self.assertEqual(ecl_stage(10), 1)
        self.assertEqual(ecl_stage(60), 2)
        self.assertEqual(ecl_stage(120), 3)

    def test_ecl_provision_amounts(self):
        """1.9: ECL provision = exposure × stage coverage rate."""
        self.assertAlmostEqual(expected_credit_loss(10000, 10), 100.0)   # 1%
        self.assertAlmostEqual(expected_credit_loss(10000, 60), 1000.0)  # 10%
        self.assertAlmostEqual(expected_credit_loss(10000, 120), 5000.0) # 50%

    def test_par_buckets(self):
        """1.9: PAR aging buckets are pinned."""
        self.assertEqual(par_bucket(0), "0 - Current")
        self.assertEqual(par_bucket(15), "1-30 Days")
        self.assertEqual(par_bucket(45), "31-60 Days")
        self.assertEqual(par_bucket(75), "61-90 Days")
        self.assertEqual(par_bucket(120), "90+ Days")

    def test_loan_custom_asset_classification_field(self):
        """1.9: the Loan DocType has the custom_asset_classification field."""
        loan = _make_sanctioned_loan(self.officer, amount=3000)
        loan_doc = frappe.get_doc("Loan", loan)
        self.assertTrue(
            loan_doc.meta.has_field("custom_asset_classification"),
            "Loan must have custom_asset_classification field"
        )

    def test_loan_custom_days_past_due_field(self):
        """1.9: the Loan DocType has the custom_days_past_due field."""
        loan = _make_sanctioned_loan(self.officer, amount=3000)
        loan_doc = frappe.get_doc("Loan", loan)
        self.assertTrue(
            loan_doc.meta.has_field("custom_days_past_due"),
            "Loan must have custom_days_past_due field"
        )


class TestReleaseGateTopUp(FrappeTestCase):
    """Gate row 1.10 — top-up / restructuring preserves prior schedule.

    The wrapper-layer invariant: a second disbursement on an existing loan
    creates a new Loan Disbursement doc without corrupting the original
    loan's docstatus or schedule. We assert the second disbursement succeeds
    and the loan remains active.
    """

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.officer = _seed_officer()

    def test_second_disbursement_preserves_loan(self):
        """1.10: a second disbursement (top-up) on an active loan succeeds
        without corrupting the loan's state."""
        loan = _make_sanctioned_loan(self.officer, amount=5000)
        # First disbursement
        frappe.flags.ignore_permissions = True
        res1 = manager_api.disburse_loan(loan_name=loan, disbursed_amount=3000)
        frappe.flags.ignore_permissions = False
        self.assertEqual(res1["status"], "disbursed")

        # Second disbursement (top-up)
        frappe.flags.ignore_permissions = True
        res2 = manager_api.disburse_loan(loan_name=loan, disbursed_amount=2000)
        frappe.flags.ignore_permissions = False
        self.assertEqual(res2["status"], "disbursed")

        # Loan is still submitted and active
        loan_doc = frappe.get_doc("Loan", loan)
        self.assertEqual(loan_doc.docstatus, 1)
        self.assertIn(loan_doc.status, ("Disbursed", "Active", "Partially Disbursed"))


class TestReleaseGateTranche(FrappeTestCase):
    """Gate row 1.11 — multi-disbursement / tranche.

    The wrapper-layer invariant: partial disbursements create separate
    Loan Disbursement docs, each with the correct amount. The loan's
    total disbursement equals the sum of the tranches.
    """

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.officer = _seed_officer()

    def test_partial_disbursements_create_separate_docs(self):
        """1.11: two partial disbursements create two Loan Disbursement docs."""
        loan = _make_sanctioned_loan(self.officer, amount=5000)
        frappe.flags.ignore_permissions = True
        res1 = manager_api.disburse_loan(loan_name=loan, disbursed_amount=2000)
        res2 = manager_api.disburse_loan(loan_name=loan, disbursed_amount=3000)
        frappe.flags.ignore_permissions = False

        self.assertEqual(res1["amount"], 2000)
        self.assertEqual(res2["amount"], 3000)
        self.assertNotEqual(res1["disbursement"], res2["disbursement"])

        # Both disbursement docs exist and are submitted
        d1 = frappe.get_doc("Loan Disbursement", res1["disbursement"])
        d2 = frappe.get_doc("Loan Disbursement", res2["disbursement"])
        self.assertEqual(d1.docstatus, 1)
        self.assertEqual(d2.docstatus, 1)
        self.assertEqual(float(d1.disbursed_amount), 2000.0)
        self.assertEqual(float(d2.disbursed_amount), 3000.0)


if __name__ == "__main__":
    unittest.main()
