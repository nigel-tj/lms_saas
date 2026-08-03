"""R34 regression tests — borrower Customer re-linking (issue #23).

QA-2026-08-03-#23: when the seeded demo borrower
(borrower@example.com) was linked to a freshly-created "Test
Borrower" Customer with zero loans, the borrower portal /lms
showed "0 loans, ZAR 0.00" while the manager dashboard showed 8
active loans worth ZAR 55,300. The fix is twofold:

1. A dedicated whitelisted endpoint
   ``lms_saas.setup.live_repair.link_borrower_to_demo_customer``
   that surgically re-points the borrower User → Contact → Customer
   link to a Customer that owns at least one Loan. Admin-only,
   idempotent, leaves users / employees / branches / loans / KYC
   untouched.

2. An active-loan fallback in
   ``lms_saas.permissions._portal_customer``: when the canonical
   Contact / Portal User / email-id resolution does NOT find a
   Customer OR finds one with zero loans AND the user has the LMS
   Borrower role, prefer the most-recently-modified Customer with
   at least one Loan. Self-heals the live portal without needing
   the operator to run the endpoint.

These tests pin both behaviours so a future refactor doesn't
silently regress the borrower demo flow.

Run via:
    cd frappe-bench && python run_all_lms_tests.py
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from lms_saas.setup import live_repair
from lms_saas import permissions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_user(email: str, roles: list[str]) -> None:
    """Create a User with the given roles if missing. Test-only."""
    if not frappe.db.exists("User", email):
        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": email.split("@")[0].title(),
            "send_welcome_email": 0,
            "enabled": 1,
        })
        user.flags.ignore_permissions = True
        user.insert()
    user = frappe.get_doc("User", email)
    for role_name in roles:
        if not frappe.db.exists("Has Role", {"parent": email, "role": role_name}):
            user.add_roles(role_name)
    frappe.db.commit()


def _ensure_role(name: str) -> None:
    if not frappe.db.exists("Role", name):
        frappe.get_doc({"doctype": "Role", "role_name": name}).insert(ignore_permissions=True)


def _make_customer(name: str) -> str:
    if not frappe.db.exists("Customer", name):
        frappe.get_doc({
            "doctype": "Customer",
            "customer_name": name,
            "customer_type": "Individual",
            "customer_group": "Individual",
            "territory": "All Territories",
        }).insert(ignore_permissions=True)
    return name


def _make_loan(applicant: str, amount: float = 1000.0) -> str:
    """Create a minimal Loan record (draft, no submission — fast)."""
    # Reuse the seeded LMS Standard loan product if present; otherwise
    # create a minimal one (product_code + company + interest rate are
    # required by the lending Loan validation hook).
    product = frappe.db.get_value(
        "Loan Product", {"product_code": "LMS-STD"}, "name"
    )
    if not product:
        company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
        if not company:
            company = frappe.db.get_value("Company", {}, "name") or ""
        if not company:
            company = "R34 Test Company"
            if not frappe.db.exists("Company", company):
                frappe.get_doc({
                    "doctype": "Company",
                    "company_name": company,
                    "abbr": "R34C",
                    "default_currency": "ZAR",
                    "country": "South Africa",
                }).insert(ignore_permissions=True)
        if not frappe.db.exists("Loan Product", "LMS-STD"):
            prod = frappe.new_doc("Loan Product")
            prod.product_code = "LMS-STD"
            prod.product_name = "LMS Standard"
            prod.company = company
            prod.rate_of_interest = 18
            prod.maximum_loan_amount = 100000
            prod.minimum_loan_amount = 1000
            prod.is_term_loan = 1
            prod.flags.ignore_permissions = True
            prod.insert()
        product = "LMS-STD"
    loan = frappe.get_doc({
        "doctype": "Loan",
        "loan_product": product,
        "loan_amount": amount,
        "applicant_type": "Customer",
        "applicant": applicant,
        "repayment_method": "Repay Over Number of Periods",
        "repayment_periods": 6,
        "rate_of_interest": 24.0,
        "docstatus": 1,
        "status": "Disbursed",
    })
    loan.flags.ignore_permissions = True
    loan.insert()
    return loan.name


def _clear_contact_links(email: str) -> None:
    """Remove Contact rows for an email so each test starts clean."""
    for contact_name in frappe.get_all(
        "Contact", filters={"email_id": email}, pluck="name"
    ):
        try:
            frappe.delete_doc("Contact", contact_name, force=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# link_borrower_to_demo_customer endpoint
# ---------------------------------------------------------------------------

class TestR34LinkBorrowerToDemoCustomer(FrappeTestCase):
    """R34-#23: re-pointing endpoint works and is safe."""

    BORROWER = "r34-borrower@example.com"
    EMPTY_CUSTOMER = "R34 Empty Customer"
    LOANED_CUSTOMER = "R34 Loaned Customer"

    def setUp(self):
        frappe.set_user("Administrator")
        _ensure_role("LMS Borrower")
        _ensure_user(self.BORROWER, ["LMS Borrower"])
        _make_customer(self.EMPTY_CUSTOMER)
        _make_customer(self.LOANED_CUSTOMER)
        _make_loan(self.LOANED_CUSTOMER, amount=5000.0)

    def tearDown(self):
        _clear_contact_links(self.BORROWER)
        for loan_name in frappe.get_all(
            "Loan", filters={"applicant": ("in", [self.EMPTY_CUSTOMER, self.LOANED_CUSTOMER])}, pluck="name"
        ):
            try:
                frappe.delete_doc("Loan", loan_name, force=True)
            except Exception:
                pass
        for cust in (self.EMPTY_CUSTOMER, self.LOANED_CUSTOMER):
            if frappe.db.exists("Customer", cust):
                try:
                    frappe.delete_doc("Customer", cust, force=True)
                except Exception:
                    pass
        if frappe.db.exists("User", self.BORROWER):
            try:
                frappe.delete_doc("User", self.BORROWER, force=True)
            except Exception:
                pass
        frappe.db.commit()

    def test_relinks_to_customer_with_active_loan(self):
        # Seed: borrower is linked to the EMPTY customer.
        contact = frappe.get_doc({
            "doctype": "Contact",
            "first_name": "R34",
            "last_name": "Borrower",
            "email_id": self.BORROWER,
            "is_primary_contact": 1,
            "user": self.BORROWER,
            "links": [{"link_doctype": "Customer", "link_name": self.EMPTY_CUSTOMER}],
        })
        contact.flags.ignore_permissions = True
        contact.insert()

        result = live_repair.link_borrower_to_demo_customer(email=self.BORROWER)

        self.assertTrue(result["ok"])
        self.assertEqual(result["previous_customer_id"], self.EMPTY_CUSTOMER)
        self.assertEqual(result["current_customer_id"], self.LOANED_CUSTOMER)
        self.assertGreaterEqual(result["loan_count"], 1)

        # The Contact Dynamic Link now points at the LOANED customer.
        link = frappe.db.get_value(
            "Dynamic Link",
            {"parenttype": "Contact", "link_doctype": "Customer",
             "parent": ("like", "%"), "link_name": self.LOANED_CUSTOMER},
            "link_name",
        )
        self.assertEqual(link, self.LOANED_CUSTOMER)

    def test_idempotent_when_already_correct(self):
        # Seed: borrower is linked to the LOANED customer (already correct).
        contact = frappe.get_doc({
            "doctype": "Contact",
            "first_name": "R34",
            "last_name": "Borrower",
            "email_id": self.BORROWER,
            "is_primary_contact": 1,
            "user": self.BORROWER,
            "links": [{"link_doctype": "Customer", "link_name": self.LOANED_CUSTOMER}],
        })
        contact.flags.ignore_permissions = True
        contact.insert()

        result = live_repair.link_borrower_to_demo_customer(email=self.BORROWER)

        self.assertTrue(result["ok"])
        self.assertIn("no change", result["message"].lower())

    def test_rejects_non_admin(self):
        # Switch to a non-admin user — should PermissionError.
        _ensure_user("r34-not-admin@example.com", ["LMS Borrower"])
        try:
            frappe.set_user("r34-not-admin@example.com")
            with self.assertRaises(frappe.PermissionError):
                live_repair.link_borrower_to_demo_customer(email=self.BORROWER)
        finally:
            frappe.set_user("Administrator")

    def test_returns_error_for_missing_user(self):
        result = live_repair.link_borrower_to_demo_customer(email="nonexistent@example.com")
        self.assertFalse(result["ok"])
        self.assertIn("does not exist", result["message"].lower())


# ---------------------------------------------------------------------------
# _portal_customer active-loan fallback
# ---------------------------------------------------------------------------

class TestR34PortalCustomerActiveLoanFallback(FrappeTestCase):
    """R34-#23: when canonical resolution finds no Customer but the
    user has LMS Borrower role, prefer a Customer with active loans."""

    BORROWER = "r34-fallback-borrower@example.com"
    LOANED_CUSTOMER = "R34 Fallback Loaned"

    def setUp(self):
        frappe.set_user("Administrator")
        _ensure_role("LMS Borrower")
        _ensure_user(self.BORROWER, ["LMS Borrower"])
        _make_customer(self.LOANED_CUSTOMER)
        _make_loan(self.LOANED_CUSTOMER, amount=2000.0)
        _clear_contact_links(self.BORROWER)

    def tearDown(self):
        _clear_contact_links(self.BORROWER)
        for loan_name in frappe.get_all(
            "Loan", filters={"applicant": self.LOANED_CUSTOMER}, pluck="name"
        ):
            try:
                frappe.delete_doc("Loan", loan_name, force=True)
            except Exception:
                pass
        if frappe.db.exists("Customer", self.LOANED_CUSTOMER):
            try:
                frappe.delete_doc("Customer", self.LOANED_CUSTOMER, force=True)
            except Exception:
                pass
        if frappe.db.exists("User", self.BORROWER):
            try:
                frappe.delete_doc("User", self.BORROWER, force=True)
            except Exception:
                pass
        frappe.db.commit()

    def test_fallback_returns_customer_with_active_loan(self):
        # No Contact exists → canonical resolution returns None →
        # fallback should pick the LOANED customer.
        result = permissions._portal_customer(self.BORROWER)
        self.assertEqual(result, self.LOANED_CUSTOMER)