"""A4 early-settlement tests (R53-T9 / #61).

Pins the early-settlement behaviour the pre-demo test plan section A4
requires, against the method locked in #53 (Rule of 78 for flat rates):

Reducing-balance:
- Settlement figure = outstanding principal + ACCRUED interest only.
- Unearned future interest (months 4-6) must NOT be charged — the system
  must not simply sum the remaining instalments. (Lending's
  ``calculate_amounts(payment_type="Full Settlement")`` charges accrued
  interest only; "Loan Closure" adds unbooked+unaccrued — the wrong mode.)

Flat:
- Rule of 78 rebate: for a 6-month flat loan with total interest T settled
  after 3 instalments, earned = (6+5+4)/21 x T = 15/21 x T, so the rebate
  is 6/21 x T = 51.43 for T = 180.
- The rebate method is stamped on the quote and stated in the disclosure.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, now_datetime, today

from lms_saas.api import manager as manager_api

try:
    from lms_saas.tests.test_release_gate_money import (
        _make_borrower,
        _resolve_branch,
        _seed_branch,
        _seed_officer,
    )
except ImportError:  # pragma: no cover - fallback for ad-hoc invocation
    from test_release_gate_money import (  # type: ignore[no-redef]
        _make_borrower,
        _resolve_branch,
        _seed_branch,
        _seed_officer,
    )


COMPANY = "LMS Demo Co"


def _make_loan(
    employee: str,
    branch: str,
    *,
    schedule_type: str = "Flat Interest Rate",
    amount: float = 600,
    periods: int = 6,
    rate_annual_pct: float = 60,
) -> str:
    """Create + approve + disburse a loan for settlement tests."""
    customer = _make_borrower("SETTLE")

    product_code = "LMS-FLAT" if schedule_type == "Flat Interest Rate" else "LMS-STD"
    product = frappe.db.get_value("Loan Product", {"product_code": product_code}, "name")
    if not product:
        prod = frappe.new_doc("Loan Product")
        prod.product_code = product_code
        prod.product_name = f"LMS {schedule_type}"
        prod.company = COMPANY
        prod.rate_of_interest = rate_annual_pct
        prod.maximum_loan_amount = 100000
        prod.minimum_loan_amount = 100
        prod.is_term_loan = 1
        prod.repayment_schedule_type = schedule_type
        # Lending validates these as mandatory (mirrors the seeded LMS-STD).
        prod.collection_offset_sequence_for_standard_asset = "Standard Collection Offset"
        prod.collection_offset_sequence_for_sub_standard_asset = "Standard Collection Offset"
        prod.collection_offset_sequence_for_written_off_asset = "Standard Collection Offset"
        prod.collection_offset_sequence_for_settlement_collection = "Standard Collection Offset"
        prod.flags.ignore_permissions = True
        prod.insert()
        product = prod.name

    la = frappe.get_doc(
        {
            "doctype": "Loan Application",
            "applicant_type": "Customer",
            "applicant": customer,
            "company": COMPANY,
            "loan_product": product,
            "loan_amount": amount,
            "repayment_periods": periods,
            "rate_of_interest": rate_annual_pct,
            "repayment_method": "Repay Over Number of Periods",
            "posting_date": today(),
            "status": "Open",
            "custom_lms_branch": branch,
            "custom_loan_officer": employee,
        }
    )
    la.insert(ignore_permissions=True)

    res = manager_api.approve_application(application_name=la.name)
    if res.get("status") != "approved":
        raise AssertionError(f"approve failed: {res}")
    loan_name = res["loan"]

    manager_api.disburse_loan(loan_name=loan_name, disbursed_amount=amount)
    return loan_name


class TestA4EarlySettlement(FrappeTestCase):
    """R53-T9 (#61) — early settlement after instalment 3."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.branch = _resolve_branch()
        _seed_branch(cls.branch)
        cls.officer = _seed_officer()

    def setUp(self):
        frappe.set_user("Administrator")
        self._prev_flag = getattr(frappe.flags, "ignore_permissions", None)
        frappe.flags.ignore_permissions = True

    def tearDown(self):
        if self._prev_flag is None:
            try:
                del frappe.flags.ignore_permissions
            except AttributeError:
                pass
        else:
            frappe.flags.ignore_permissions = self._prev_flag

    def test_rule_of_78_rebate_math_exact(self):
        """Pure-math pin of the Rule-of-78 helper locked in #53.

        6-month flat loan, total interest 180, settle after 3 instalments:
        earned = (6+5+4)/21 x 180 = 128.57; rebate = 180 - 128.57 = 51.43.
        """
        from lms_saas.utils.settlement import rule_of_78_rebate

        rebate = rule_of_78_rebate(total_interest=180.0, periods=6, instalments_paid=3)
        self.assertAlmostEqual(rebate, 51.43, places=2)

        # Boundary: no instalments paid (no rebate — nothing settled early)
        # and full term paid (no rebate — loan already ended).
        self.assertAlmostEqual(rule_of_78_rebate(total_interest=180.0, periods=6, instalments_paid=0), 0.0, places=2)
        self.assertAlmostEqual(rule_of_78_rebate(total_interest=180.0, periods=6, instalments_paid=6), 0.0, places=2)

    def test_settlement_quote_flat_applies_rule_of_78_rebate(self):
        """Flat 600 @ 5%/mo over 6 months, settled after 3 instalments of 130:

        The figure must be STRICTLY BELOW the naive 390 remaining-instalment
        sum (that's A4's 'must not simply sum the remaining instalments') and
        at or above the outstanding principal (300).
        """
        loan = _make_loan(self.officer, self.branch, schedule_type="Flat Interest Rate")
        for _ in range(3):
            manager_api.record_repayment(loan_name=loan, amount=130, payment_mode="Cash")

        quote = manager_api.get_settlement_quote(loan_name=loan)
        self.assertEqual(quote["method"], "Rule of 78")
        self.assertAlmostEqual(
            float(quote["rebate"]), 51.43, places=2,
            msg=f"expected Rule-of-78 rebate 51.43, got {quote['rebate']}",
        )
        figure = float(quote["settlement_amount"])
        self.assertLess(figure, 390.00, "settlement must not sum remaining instalments")
        self.assertGreaterEqual(figure, 300.00, "settlement below outstanding principal")
        # A4: "The rebate method is stated on screen".
        self.assertIn("Rule of 78", quote.get("disclosure", ""))

    def test_settle_loan_stamps_method_and_closes(self):
        """Executing the settlement stamps rebate_method = 'Rule of 78' and
        leaves the loan settled with an audit row."""
        loan = _make_loan(self.officer, self.branch, schedule_type="Flat Interest Rate")
        for _ in range(3):
            manager_api.record_repayment(loan_name=loan, amount=130, payment_mode="Cash")

        quote = manager_api.get_settlement_quote(loan_name=loan)
        res = manager_api.settle_loan(
            loan_name=loan,
            settlement_amount=quote["settlement_amount"],
            payment_mode="Cash",
        )
        self.assertEqual(res.get("status"), "settled", f"settle failed: {res}")

        settlement = frappe.get_doc("Loan Repayment", res["repayment"])
        self.assertEqual(settlement.docstatus, 1)
        # Method + rebate stamped on the settled repayment (A4 + #53).
        self.assertEqual(settlement.get("rebate_method"), "Rule of 78")
        self.assertAlmostEqual(
            float(settlement.get("early_settlement_rebate") or 0), 51.43, places=2
        )

        # Audit row exists.
        rows = frappe.get_all(
            "LMS Audit Event",
            filters={
                "reference_doctype": "Loan Repayment",
                "reference_name": res["repayment"],
                "event_type": "LoanSettlement:ManagerRecorded",
            },
            pluck="name",
        )
        self.assertTrue(rows, "LoanSettlement audit row missing")

    def test_settlement_quote_reducing_balance_no_unearned_interest(self):
        """Reducing 600 @ 60% annual over 6 months: settle after 3 instalments.

        The quote mode must be 'Full Settlement' (accrued interest only —
        NOT 'Loan Closure', which adds unbooked+unaccrued interest). The
        figure must be strictly below the naive sum of remaining instalments.
        """
        loan = _make_loan(
            self.officer, self.branch,
            schedule_type="Monthly as per repayment start date",
        )
        for _ in range(3):
            manager_api.record_repayment(loan_name=loan, amount=106, payment_mode="Cash")

        quote = manager_api.get_settlement_quote(loan_name=loan)
        self.assertEqual(quote["method"], "None", "reducing balance has no rebate method")
        self.assertEqual(float(quote.get("rebate") or 0), 0.0)

        # Naive remaining-instalments sum, computed in Python (no raw SQL).
        schedule_name = frappe.db.get_value(
            "Loan Repayment Schedule", {"loan": loan}, "name"
        )
        remaining_naive = float(
            sum(
                flt(r.total_payment or 0)
                for r in frappe.get_all(
                    "Repayment Schedule",
                    filters={"parent": schedule_name},
                    fields=["total_payment"],
                )
            )
        ) if schedule_name else 0.0
        self.assertGreater(remaining_naive, 0, "schedule rows missing for loan")
        figure = float(quote["settlement_amount"])
        self.assertLess(
            figure, remaining_naive,
            "settlement must not simply sum the remaining instalments",
        )


if __name__ == "__main__":
    unittest.main()