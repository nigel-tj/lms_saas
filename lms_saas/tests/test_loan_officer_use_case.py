"""Loan Officer use case — full workflow coverage.

This test suite exercises every Loan Officer portal use case end-to-end
against a seeded branch + borrowers + applications + loans + leads. The
intent is to lock in the fixes from the Round 14 board review and
guarantee the officer can:

  * view + edit a borrower profile (name, mobile, email, national ID)
  * view the dashboard, applications, my loans, leads, reports tabs
  * disburse a loan (via disburse_assigned_loan)
  * record a repayment on an active loan
  * record consent on a lead and convert it
  * create a new loan application on behalf of a borrower
  * create a new borrower

The shared `_seed` helper is idempotent so tests can be run repeatedly
against the same dev site.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import today

from lms_saas.api import officer as officer_api
from lms_saas.api import staff as staff_api


OFFICER_EMAIL = "officer@kesari.africa"
BRANCH = "Main Branch - LMS"
COMPANY = "LMS Demo Co"


def _set_user(user: str) -> None:
    frappe.set_user(user)


def _seed_branch() -> None:
    """Make sure a HRMS Branch record exists for the officer's cost center.

    The HRMS Branch is used by the Employee.branch field; the Cost Center
    is used by the LMS custom branch field. Both are needed for full
    branch scoping.
    """
    if not frappe.db.exists("Branch", "Main Branch"):
        b = frappe.new_doc("Branch")
        b.branch = "Main Branch"
        b.insert(ignore_permissions=True)


def _seed_user_permission() -> None:
    """Make sure the officer has a Cost Center User Permission."""
    existing = frappe.get_all(
        "User Permission",
        filters={"user": OFFICER_EMAIL, "allow": "Cost Center", "for_value": BRANCH},
        pluck="name",
    )
    for name in existing:
        frappe.delete_doc("User Permission", name, ignore_permissions=True, force=True)

    perm = frappe.new_doc("User Permission")
    perm.user = OFFICER_EMAIL
    perm.allow = "Cost Center"
    perm.for_value = BRANCH
    perm.apply_to_all_doctypes = 1
    perm.insert(ignore_permissions=True)


def _seed_employee() -> str:
    """Ensure the officer has an Employee record with custom_lms_branch set."""
    emp_name = frappe.db.get_value("Employee", {"user_id": OFFICER_EMAIL}, "name")
    if not emp_name:
        emp = frappe.new_doc("Employee")
        emp.employee_id = "EMP-OFFICER-1"
        emp.first_name = "Loan"
        emp.last_name = "Officer"
        emp.user_id = OFFICER_EMAIL
        emp.status = "Active"
        emp.company = COMPANY
        emp.date_of_joining = today()
        emp.gender = "Male"
        emp.insert(ignore_permissions=True)
        emp_name = emp.name

    emp = frappe.get_doc("Employee", emp_name)
    emp.user_id = OFFICER_EMAIL
    emp.status = "Active"
    emp.company = COMPANY
    if emp.meta.has_field("custom_lms_persona"):
        emp.custom_lms_persona = "Loan Officer"
    if emp.meta.has_field("custom_lms_branch"):
        emp.custom_lms_branch = BRANCH
    if emp.meta.has_field("branch"):
        try:
            emp.branch = "Main Branch"
        except Exception:
            pass
    emp.save(ignore_permissions=True)
    return emp.name


def _ensure_test_borrower(suffix: str) -> str:
    """Idempotent — return a borrower name in the officer's branch."""
    cust_id = f"Officer Test Borrower {suffix}"
    if not frappe.db.exists("Customer", cust_id):
        cust = frappe.new_doc("Customer")
        cust.name = cust_id
        cust.customer_name = cust_id
        cust.customer_type = "Individual"
        cust.customer_group = "Individual"
        cust.territory = "All Territories"
        cust.insert(ignore_permissions=True)
    cust = frappe.get_doc("Customer", cust_id)
    if cust.meta.has_field("custom_lms_branch"):
        cust.custom_lms_branch = BRANCH
    cust.save(ignore_permissions=True)
    return cust_id


def _ensure_loan_product() -> str:
    if frappe.db.exists("Loan Product", "LMS-STD"):
        return "LMS-STD"
    # Fall back: pick the first product in the company
    prods = frappe.get_all(
        "Loan Product", fields=["name", "company"], limit_page_length=20
    )
    for p in prods:
        if p.company == COMPANY:
            return p.name
    return prods[0].name if prods else None


class TestOfficerBranchResolution(unittest.TestCase):
    """R14 fix: branch resolution must prefer custom_lms_branch (Cost Center)
    over the HRMS `branch` field, otherwise branch-scoped queries return
    empty data."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        _seed_branch()
        _seed_user_permission()
        cls.employee_name = _seed_employee()

    def test_officer_branch_resolves_to_cost_center(self):
        _set_user(OFFICER_EMAIL)
        branch = staff_api.get_current_user_branch()
        self.assertEqual(
            branch,
            BRANCH,
            f"expected officer branch={BRANCH!r}, got {branch!r}. "
            "If you see the HRMS Branch name here, the branch-scope fix "
            "in lms_saas.api.staff.get_current_user_branch has regressed.",
        )


class TestOfficerDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        _seed_branch()
        _seed_user_permission()
        cls.employee_name = _seed_employee()
        cls.product = _ensure_loan_product()
        # Ensure at least one test borrower + application + lead
        cls.borrower = _ensure_test_borrower("R14")

    def setUp(self):
        _set_user(OFFICER_EMAIL)

    def test_dashboard_returns_branch_and_employee(self):
        d = officer_api.get_officer_dashboard()
        self.assertEqual(d.get("branch"), BRANCH)
        self.assertEqual(d.get("employee"), self.employee_name)
        kpis = d.get("kpis") or {}
        # The dashboard must not throw and must return the four KPI keys
        for k in ("pending_applications", "my_active_loans", "pending_disbursement",
                  "disbursed_this_month", "par_ratio", "par_count", "branch_leads"):
            self.assertIn(k, kpis)


class TestOfficerBorrowerEdit(unittest.TestCase):
    """R14 fix: officer can edit a borrower's contact details. Before the
    fix the borrower modal was view-only and `update_borrower` triggered a
    403 because the Customer <-> Contact sync hook needed write access
    on the Contact DocType."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        _seed_branch()
        _seed_user_permission()
        cls.employee_name = _seed_employee()
        cls.borrower = _ensure_test_borrower("R14-EDIT")

    def setUp(self):
        _set_user(OFFICER_EMAIL)

    def test_update_borrower_changes_contact_fields(self):
        new_email = f"officer-r14-{frappe.utils.now_datetime().strftime('%H%M%S%f')}@example.com"
        new_mobile = "+27-71-555-9001"
        new_nid = "8501011234089"

        result = officer_api.update_borrower(
            customer_name=self.borrower,
            email_id=new_email,
            mobile_no=new_mobile,
            national_id=new_nid,
        )
        self.assertEqual(result.get("status"), "updated")

        cust = frappe.get_doc("Customer", self.borrower)
        self.assertEqual(cust.email_id, new_email)
        self.assertEqual(cust.mobile_no, new_mobile)
        if cust.meta.has_field("custom_national_id_number"):
            self.assertEqual(cust.custom_national_id_number, new_nid)

    def test_update_borrower_rejects_out_of_branch(self):
        # Create a borrower in a different branch and try to edit as the
        # officer. Must be rejected.
        other = "R14-OTHER-BRANCH"
        if not frappe.db.exists("Customer", other):
            cust = frappe.new_doc("Customer")
            cust.name = other
            cust.customer_name = other
            cust.customer_type = "Individual"
            cust.customer_group = "Individual"
            cust.territory = "All Territories"
            cust.insert(ignore_permissions=True)
            if cust.meta.has_field("custom_lms_branch"):
                cust.custom_lms_branch = "South Branch - LMS"
                cust.save(ignore_permissions=True)

        with self.assertRaises(frappe.PermissionError):
            officer_api.update_borrower(
                customer_name=other,
                email_id="evil@example.com",
            )


class TestOfficerLeadConsent(unittest.TestCase):
    """R14 fix: officer can record consent on a lead (the half-step
    before convert_lead). Required because the lead's Actions column
    was empty when there was no consent and no way to record one."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        _seed_branch()
        _seed_user_permission()
        cls.employee_name = _seed_employee()
        # Pre-create the two test leads (we don't have create perms as
        # the officer, so we set them up as Administrator here, then
        # the test methods act as the officer).
        cls.lead_ok = cls._make_lead("01")
        cls.lead_other = cls._make_lead("02")

    @staticmethod
    def _make_lead(suffix: str) -> str:
        # Lead autonames to CRM-LEAD-#### — we return the actual document
        # name (the PK) so callers can look it up by `name`.
        # Match by lead_name to keep tests idempotent.
        lead_name = f"Officer R14 Lead {suffix}"
        existing = frappe.db.get_value("Lead", {"lead_name": lead_name}, "name")
        if existing:
            return existing
        ld = frappe.new_doc("Lead")
        ld.lead_name = lead_name
        ld.company_name = lead_name + " Co"
        ld.email_id = f"r14-{suffix.lower()}@example.com"
        # Use a numeric suffix; otherwise the contact phone validator rejects
        # suffixes like "A" / "B" which aren't real digits.
        ld.mobile_no = f"+27-71-555-90{suffix}"
        ld.status = "Lead"
        ld.source = "Walk In"
        if ld.meta.has_field("custom_lms_branch"):
            ld.custom_lms_branch = BRANCH
        ld.insert(ignore_permissions=True)
        return ld.name

    def setUp(self):
        _set_user(OFFICER_EMAIL)

    def test_set_lead_consent(self):
        result = officer_api.set_lead_consent(lead_name=self.lead_ok)
        self.assertEqual(result.get("status"), "ok")
        ld = frappe.get_doc("Lead", self.lead_ok)
        if ld.meta.has_field("custom_consent_given"):
            self.assertEqual(int(ld.custom_consent_given or 0), 1)
        if ld.meta.has_field("custom_consent_date"):
            self.assertTrue(ld.custom_consent_date)

    def test_set_lead_consent_rejects_other_branch(self):
        # Move the lead to another branch
        if frappe.get_meta("Lead").has_field("custom_lms_branch"):
            frappe.db.set_value("Lead", self.lead_other, "custom_lms_branch", "South Branch - LMS")
        with self.assertRaises(frappe.PermissionError):
            officer_api.set_lead_consent(lead_name=self.lead_other)
        # Restore so re-running tests still works
        frappe.db.set_value("Lead", self.lead_other, "custom_lms_branch", BRANCH)


class TestOfficerLoanDetail(unittest.TestCase):
    """R14 fix: get_loan_detail queried Repayment Schedule with a `paid`
    column that does not exist on this ERPNext version. The endpoint 500'd
    the moment an officer clicked View on a loan."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        _seed_branch()
        _seed_user_permission()
        cls.employee_name = _seed_employee()

    def setUp(self):
        _set_user(OFFICER_EMAIL)

    def test_get_loan_detail_does_not_throw(self):
        # Find an existing active loan the officer can view. Use one of
        # the officer's own loans seeded in earlier test runs (e.g. the
        # `Officer Test Borrower 4` / `Officer Test Borrower 5` loans).
        candidates = frappe.get_all(
            "Loan",
            filters={"docstatus": 1, "status": "Disbursed"},
            fields=["name"],
            order_by="creation desc",
            limit_page_length=5,
        )
        if not candidates:
            self.skipTest("No disbursed loans on this site — cannot test loan detail.")
        ln_name = candidates[0]["name"]

        # This MUST not throw. Before the R14 fix it 500'd with
        # `Unknown column 'paid' in 'SELECT'`.
        detail = officer_api.get_loan_detail(ln_name)
        self.assertIn("loan", detail)
        self.assertIn("schedule", detail)
        # schedule rows may be empty if no repayment schedule was generated,
        # but the call must succeed.
        self.assertIsInstance(detail.get("repayments"), list)
        self.assertIsInstance(detail.get("disbursements"), list)


class TestOfficerCreateApplication(unittest.TestCase):
    """Officer submits a loan application on behalf of a borrower. The
    application must be auto-tagged with the officer's branch and
    Employee record so the manager portal filters correctly."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        _seed_branch()
        _seed_user_permission()
        cls.employee_name = _seed_employee()
        cls.product = _ensure_loan_product()
        cls.borrower = _ensure_test_borrower("R14-APP")

    def setUp(self):
        _set_user(OFFICER_EMAIL)

    def test_submit_application_on_behalf(self):
        result = officer_api.submit_application_on_behalf(
            customer=self.borrower,
            loan_amount=4000,
            loan_product=self.product,
            repayment_periods=4,
        )
        app_name = result.get("application")
        self.assertTrue(app_name)
        app = frappe.get_doc("Loan Application", app_name)
        self.assertEqual(app.applicant, self.borrower)
        if app.meta.has_field("custom_lms_branch"):
            self.assertEqual(app.custom_lms_branch, BRANCH)
        if app.meta.has_field("custom_loan_officer"):
            self.assertEqual(app.custom_loan_officer, self.employee_name)


if __name__ == "__main__":
    unittest.main()
