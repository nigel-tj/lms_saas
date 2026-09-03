"""R58 regression: collection run sheet must surface arrears (overdue bucket).

Ticket #80 (server slice of #77): the run sheet behind Field Collection only
looked forward from today (``payment_date between today and today+N``). With
the default 14-day window and monthly installment cycles, the sheet read
"No dues in range" for weeks at a stretch while real arrears sat unpaid
(live finding: an unpaid August demand invisible to every collector, PAR 30+
at $10k on the manager dashboard, and zero repayments ever recorded).

Fix shape pinned here at the report seam (``collection_sheet.execute``):

1. **Overdue bucket** — an unpaid installment with payment date before today
   comes back tagged ``bucket="overdue"``, sorted most-overdue first.
2. **Paid filter** — an installment whose amount has already been collected
   (the loan's paid total has moved past it) does NOT appear as upcoming.
3. **Upcoming unchanged** — a future unpaid installment still comes back
   tagged ``bucket="upcoming"``.
4. **KPI agreement** — the API layer returns per-bucket totals
   (count + amount) that agree exactly with the rows (R35-#27: a KPI and
   its tab can never disagree; pinned in a test so a refactor cannot
   reintroduce the split).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


def _make_loan_with_schedule(
    *,
    loan_name: str,
    installments: list[dict],
    total_payment: float | None = None,
    total_paid: float = 0.0,
):
    """Fixture: a submitted Loan plus one submitted Loan Repayment Schedule
    whose child Repayment Schedule rows carry the given installments.

    installments: [{payment_date, total_payment, principal_amount, interest_amount}]
    Returns the loan doc name (== loan_name).
    """
    from frappe.utils import nowdate

    company = frappe.db.get_single_value("Global Defaults", "default_company") or "LMS Demo Co"
    branch = frappe.db.get_value(
        "Cost Center", {"company": company, "is_group": 0}, "name"
    )
    product = frappe.db.get_value("Loan Product", {}, "name")
    customer = frappe.db.get_value("Customer", {}, "name")

    # Clean any previous run of the same fixture (deterministic re-runs)
    for parent in frappe.get_all(
        "Loan Repayment Schedule", filters={"loan": loan_name}, pluck="name"
    ):
        frappe.db.delete("Repayment Schedule", {"parent": parent})
        frappe.db.delete("Loan Repayment Schedule", parent)
    if frappe.db.exists("Loan", loan_name):
        frappe.db.delete("Loan", loan_name)

    loan = frappe.get_doc(
        {
            "doctype": "Loan",
            "name": loan_name,
            "applicant_type": "Customer",
            "applicant": customer,
            "company": company,
            "loan_product": product,
            "loan_amount": sum(i["total_payment"] for i in installments) or 1000,
            "status": "Active",
            "docstatus": 1,
            "is_term_loan": 1,
            "custom_lms_branch": branch,
            "total_payment": total_payment or sum(i["total_payment"] for i in installments),
            "total_amount_paid": total_paid,
        }
    )
    loan.flags.ignore_permissions = True
    loan.flags.ignore_validate = True
    loan.db_insert()
    loan.db_set("docstatus", 1)

    schedule = frappe.get_doc(
        {
            "doctype": "Loan Repayment Schedule",
            "loan": loan_name,
            "company": company,
            "docstatus": 1,
            "status": "Active",
            "repayment_start_date": installments[0]["payment_date"] if installments else nowdate(),
            "repayment_schedule": [
                {
                    "payment_date": i["payment_date"],
                    "total_payment": i["total_payment"],
                    "principal_amount": i.get("principal_amount", 0),
                    "interest_amount": i.get("interest_amount", 0),
                }
                for i in installments
            ],
        }
    )
    schedule.flags.ignore_permissions = True
    schedule.flags.ignore_validate = True
    schedule.insert()
    schedule.db_set("docstatus", 1)
    for row in schedule.repayment_schedule:
        row.db_set("docstatus", 1)
    return loan_name


def _cleanup_loan(loan_name: str):
    for parent in frappe.get_all(
        "Loan Repayment Schedule", filters={"loan": loan_name}, pluck="name"
    ):
        frappe.db.delete("Repayment Schedule", {"parent": parent})
        frappe.db.delete("Loan Repayment Schedule", parent)
    if frappe.db.exists("Loan", loan_name):
        frappe.db.delete("Loan", loan_name)


class TestCollectionSheetBuckets(FrappeTestCase):
    """Bucket definitions at the report seam (fixture loans, no live data)."""

    LOAN = "R58-TEST-LOAN"

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        _cleanup_loan(self.LOAN)

    def test_overdue_unpaid_installment_is_tagged_overdue(self):
        """An unpaid installment before today lands in the overdue bucket."""
        from lms_saas.lms_saas.report.collection_sheet.collection_sheet import execute
        from frappe.utils import add_days, today

        past = add_days(today(), -10)
        _make_loan_with_schedule(
            loan_name=self.LOAN,
            installments=[{"payment_date": past, "total_payment": 500.0}],
        )

        _columns, rows = execute({"days_ahead": 14})
        overdue = [r for r in rows if r["loan"] == self.LOAN]
        self.assertEqual(1, len(overdue), f"expected the overdue row, got {rows}")
        self.assertEqual("overdue", overdue[0]["bucket"])
        self.assertEqual(500.0, overdue[0]["amount"])
        # Most-overdue first ordering: checked in the multi-row test below.

    def test_paid_installment_excluded_from_upcoming(self):
        """An installment already covered by repayments is not served as upcoming."""
        from lms_saas.lms_saas.report.collection_sheet.collection_sheet import execute
        from frappe.utils import add_days, today

        future = add_days(today(), 3)
        # Loan whose installment (500) has been fully paid (paid total 500+).
        _make_loan_with_schedule(
            loan_name=self.LOAN,
            installments=[{"payment_date": future, "total_payment": 500.0}],
            total_paid=500.0,
        )

        _columns, data = execute({"days_ahead": 14})
        mine = [r for r in data if r["loan"] == self.LOAN]
        self.assertEqual(
            [], mine, "paid installment must not appear in the upcoming bucket"
        )

    def test_future_unpaid_installment_is_upcoming(self):
        """A future unpaid installment stays in the upcoming bucket (unchanged)."""
        from lms_saas.lms_saas.report.collection_sheet.collection_sheet import execute
        from frappe.utils import add_days, today

        future = add_days(today(), 3)
        _make_loan_with_schedule(
            loan_name=self.LOAN,
            installments=[{"payment_date": future, "total_payment": 700.0}],
        )

        _columns, data = execute({"days_ahead": 14})
        mine = [r for r in data if r["loan"] == self.LOAN]
        self.assertEqual(1, len(mine))
        self.assertEqual("upcoming", mine[0]["bucket"])
        self.assertEqual(700.0, mine[0]["amount"])

    def test_overdue_sorts_most_overdue_first(self):
        """Rows within the overdue bucket are ordered most-overdue first."""
        from lms_saas.lms_saas.report.collection_sheet.collection_sheet import execute
        from frappe.utils import add_days, today

        _make_loan_with_schedule(
            loan_name=self.LOAN,
            installments=[
                {"payment_date": add_days(today(), -5), "total_payment": 300.0},
                {"payment_date": add_days(today(), -20), "total_payment": 400.0},
            ],
        )

        _columns, data = execute({"days_ahead": 14})
        mine = [r for r in data if r["loan"] == self.LOAN]
        self.assertEqual(2, len(mine))
        self.assertTrue(
            all(r["bucket"] == "overdue" for r in mine), mine
        )
        # Most-overdue first: the -20d installment precedes the -5d one.
        from frappe.utils import getdate

        self.assertEqual(getdate(add_days(today(), -20)), mine[0]["due_date"])
        self.assertEqual(getdate(add_days(today(), -5)), mine[1]["due_date"])

    def test_mixed_buckets_ordered_overdue_then_upcoming(self):
        """Overdue rows come before upcoming rows in the returned list."""
        from lms_saas.lms_saas.report.collection_sheet.collection_sheet import execute
        from frappe.utils import add_days, today

        _make_loan_with_schedule(
            loan_name=self.LOAN,
            installments=[
                {"payment_date": add_days(today(), -3), "total_payment": 100.0},
                {"payment_date": add_days(today(), 7), "total_payment": 200.0},
            ],
        )

        _columns, data = execute({"days_ahead": 14})
        mine = [r for r in data if r["loan"] == self.LOAN]
        self.assertEqual(2, len(mine))
        self.assertEqual("overdue", mine[0]["bucket"])
        self.assertEqual("upcoming", mine[1]["bucket"])


class TestRunSheetKpiAgreement(FrappeTestCase):
    """The API layer's per-bucket KPI totals must agree with the rows (R35-#27)."""

    LOAN = "R58-TEST-LOAN-KPI"

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        _cleanup_loan(self.LOAN)

    def test_api_kpis_match_rows(self):
        from lms_saas.api.field_collection import get_collection_run_sheet
        from frappe.utils import add_days, today

        _make_loan_with_schedule(
            loan_name=self.LOAN,
            installments=[
                {"payment_date": add_days(today(), -2), "total_payment": 150.0},
                {"payment_date": add_days(today(), 5), "total_payment": 250.0},
            ],
        )

        result = get_collection_run_sheet(days_ahead=14)
        rows = result["rows"]
        mine = [r for r in rows if r["loan"] == self.LOAN]
        self.assertEqual(2, len(mine))

        kpis = result.get("kpis") or {}
        self.assertIn("overdue", kpis)
        self.assertIn("upcoming", kpis)

        # R35-#27 pin: the KPI totals must be recomputable from the rows
        # the API returns — ALL of them (admin scope sees the whole bench,
        # so the totals span every branch's loans, not just the fixture).
        overdue_rows = [r for r in rows if r.get("bucket") == "overdue"]
        upcoming_rows = [r for r in rows if r.get("bucket") == "upcoming"]
        self.assertEqual(
            sum(r["amount"] for r in overdue_rows),
            kpis["overdue"]["amount"],
            "overdue KPI amount disagrees with overdue rows",
        )
        self.assertEqual(
            sum(r["amount"] for r in upcoming_rows),
            kpis["upcoming"]["amount"],
            "upcoming KPI amount disagrees with upcoming rows",
        )
        self.assertEqual(len(overdue_rows), kpis["overdue"]["count"])
        self.assertEqual(len(upcoming_rows), kpis["upcoming"]["count"])
        # The fixture loan's own rows must land in the right buckets.
        self.assertEqual({"overdue", "upcoming"}, {r["bucket"] for r in mine})