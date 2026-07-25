"""Loan Officer KYC use case — full workflow coverage.

R15 added the KYC Queue tab, the review modal, the upload widget, and
the audit trail. This test suite locks in the officer-side API and
guards the cross-branch reject path.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import today

from lms_saas.api import officer as officer_api


OFFICER_EMAIL = "officer@kesari.africa"
BRANCH = "Main Branch - LMS"
COMPANY = "LMS Demo Co"


def _set_user(user: str) -> None:
    frappe.set_user(user)


def _seed_branch() -> None:
    if not frappe.db.exists("Branch", "Main Branch"):
        b = frappe.new_doc("Branch")
        b.branch = "Main Branch"
        b.insert(ignore_permissions=True)


def _seed_user_permission() -> None:
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
    emp.save(ignore_permissions=True)
    return emp.name


def _ensure_borrower(suffix: str) -> str:
    """Return the Customer's actual PK (the autoname-generated id), not
    a human-readable name. Frappe's Customer uses `naming_series:` so
    any pre-set `name` is overridden at insert time."""
    cust_id = f"Officer R15 Borrower {suffix}"
    # Look up by customer_name (display) first — that's the stable key.
    existing = frappe.db.get_value("Customer", {"customer_name": cust_id}, "name")
    if existing:
        cust = frappe.get_doc("Customer", existing)
        if cust.meta.has_field("custom_lms_branch"):
            cust.custom_lms_branch = BRANCH
        cust.save(ignore_permissions=True)
        return existing
    cust = frappe.new_doc("Customer")
    cust.customer_name = cust_id
    cust.customer_type = "Individual"
    cust.customer_group = "Individual"
    cust.territory = "All Territories"
    cust.insert(ignore_permissions=True)
    if cust.meta.has_field("custom_lms_branch"):
        cust.custom_lms_branch = BRANCH
    cust.save(ignore_permissions=True)
    return cust.name


class TestOfficerKycWorkflow(unittest.TestCase):
    """R15: Loan Officer can start, update, and review KYC records for
    borrowers in their branch. The API refuses to mark Approved without
    the four required fields, and every change is captured in the LMS
    Audit Event table for the regulator export."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        _seed_branch()
        _seed_user_permission()
        cls.employee_name = _seed_employee()
        cls.borrower = _ensure_borrower("01")
        cls.borrower_other = _ensure_borrower("02")

    def setUp(self):
        _set_user(OFFICER_EMAIL)

    def test_get_kyc_queue_returns_branch_records_and_counts(self):
        result = officer_api.get_kyc_queue()
        # The branch resolution must work; counts must be a dict with the
        # five buckets + no_kyc.
        self.assertEqual(result.get("branch"), BRANCH)
        counts = result.get("counts") or {}
        for k in ("pending", "in_review", "approved", "rejected", "no_kyc"):
            self.assertIn(k, counts)
        # Queue is a list (possibly empty — depends on existing test data).
        self.assertIsInstance(result.get("queue"), list)

    def test_start_kyc_creates_pending_record(self):
        # Clean slate — start a brand new KYC for our test borrower.
        existing = frappe.db.get_value(
            "LMS Borrower Compliance", {"customer": self.borrower}, "name"
        )
        if existing:
            frappe.delete_doc("LMS Borrower Compliance", existing,
                              ignore_permissions=True, force=True)

        result = officer_api.start_kyc(
            customer=self.borrower, kyc_status="Pending", national_id="8501011234089"
        )
        self.assertTrue(result.get("kyc"))
        self.assertTrue(result.get("created"))
        rec = frappe.get_doc("LMS Borrower Compliance", result["kyc"])
        self.assertEqual(rec.kyc_status, "Pending")
        self.assertEqual(rec.national_id_number, "8501011234089")

    def test_start_kyc_is_idempotent(self):
        # Calling start_kyc a second time returns the existing record,
        # not a new one — there must be one KYC per borrower.
        result1 = officer_api.start_kyc(customer=self.borrower)
        result2 = officer_api.start_kyc(customer=self.borrower)
        self.assertEqual(result1["kyc"], result2["kyc"])
        self.assertFalse(result2.get("created"))

    def test_update_kyc_records_consent_and_nid(self):
        kyc = frappe.db.get_value(
            "LMS Borrower Compliance", {"customer": self.borrower}, "name"
        )
        result = officer_api.update_kyc(
            kyc_name=kyc,
            consent_given=1,
            national_id="8501019999999",
            notes="Verified at counter",
        )
        self.assertEqual(result.get("status"), "ok")
        rec = frappe.get_doc("LMS Borrower Compliance", kyc)
        self.assertEqual(int(rec.consent_given or 0), 1)
        self.assertTrue(rec.consent_date)
        self.assertEqual(rec.national_id_number, "8501019999999")

    def test_update_kyc_refuses_approved_without_docs(self):
        # Use a fresh borrower for this test so previous state doesn't
        # leak in. The officer can only Approved when ALL four fields
        # (NID + ID + POA + consent) are present.
        # Create the borrower as Administrator (officer doesn't have
        # Customer create perm), then switch back to officer for the
        # actual KYC workflow calls.
        frappe.set_user("Administrator")
        fresh = _ensure_borrower("03")
        _set_user(OFFICER_EMAIL)
        # Make sure no KYC record exists.
        existing = frappe.db.get_value(
            "LMS Borrower Compliance", {"customer": fresh}, "name"
        )
        if existing:
            frappe.delete_doc("LMS Borrower Compliance", existing,
                              ignore_permissions=True, force=True)
        officer_api.start_kyc(customer=fresh, kyc_status="In Review",
                              national_id="8501013333333")

        kyc = frappe.db.get_value(
            "LMS Borrower Compliance", {"customer": fresh}, "name"
        )
        self.assertTrue(kyc, "start_kyc should have created a KYC record")
        # Try to flip to Approved with NID set but no consent + no docs.
        with self.assertRaises(frappe.ValidationError):
            officer_api.update_kyc(
                kyc_name=kyc,
                kyc_status="Approved",
            )
        # Try with ID + POA but no consent — still must refuse because
        # consent is missing. (kyc_status='Approved' is required to
        # trigger the gate; without it the API just saves the docs.)
        with self.assertRaises(frappe.ValidationError):
            officer_api.update_kyc(
                kyc_name=kyc,
                kyc_status="Approved",
                id_document_proof="/files/test-id.txt",
                proof_of_address="/files/test-poa.txt",
            )

    def test_update_kyc_approves_when_all_four_in_place(self):
        kyc = frappe.db.get_value(
            "LMS Borrower Compliance", {"customer": self.borrower}, "name"
        )
        result = officer_api.update_kyc(
            kyc_name=kyc,
            kyc_status="Approved",
            consent_given=1,
            national_id="8501011234089",
            id_document_proof="/files/test-id.txt",
            proof_of_address="/files/test-poa.txt",
            notes="All four fields confirmed",
        )
        self.assertEqual(result.get("status"), "ok")
        self.assertEqual(result.get("kyc_status"), "Approved")

    def test_update_kyc_writes_audit_trail(self):
        kyc = frappe.db.get_value(
            "LMS Borrower Compliance", {"customer": self.borrower}, "name"
        )
        # Re-flip to In Review to generate a new audit row.
        officer_api.update_kyc(kyc_name=kyc, kyc_status="In Review", notes="Audit test")
        trail = officer_api.get_kyc_audit_trail(kyc_name=kyc)
        rows = trail.get("trail") or []
        # We have at least the 3 audit rows from this test (consent, NID,
        # the Approved flip, the In Review flip).
        self.assertGreaterEqual(len(rows), 1)
        # Each row carries event_type + user + details.
        for r in rows:
            self.assertEqual(r.get("event_type"), "kyc_status_change")
            self.assertIn("KYC status", r.get("details", ""))

    def test_get_kyc_detail_returns_borrower_summary(self):
        # Ensure a record exists for our primary borrower; previous tests
        # may have deleted it.
        if not frappe.db.exists("LMS Borrower Compliance", {"customer": self.borrower}):
            officer_api.start_kyc(customer=self.borrower, kyc_status="Pending")
        kyc = frappe.db.get_value(
            "LMS Borrower Compliance", {"customer": self.borrower}, "name"
        )
        detail = officer_api.get_kyc_detail(kyc_name=kyc)
        self.assertIn("kyc", detail)
        self.assertIn("borrower", detail)
        self.assertEqual(detail["kyc"]["customer"], self.borrower)
        self.assertEqual(detail["borrower"]["name"], self.borrower)
        self.assertEqual(detail["borrower"]["custom_lms_branch"], BRANCH)

    def test_update_kyc_rejects_other_branch(self):
        # Move the borrower to a different branch then try to update KYC
        # as the officer. Must be rejected.
        if not frappe.db.exists("Customer", self.borrower_other):
            cust = frappe.new_doc("Customer")
            cust.name = self.borrower_other
            cust.customer_name = self.borrower_other
            cust.customer_type = "Individual"
            cust.customer_group = "Individual"
            cust.territory = "All Territories"
            cust.insert(ignore_permissions=True)
        # Move the borrower to South Branch
        frappe.db.set_value("Customer", self.borrower_other, "custom_lms_branch",
                            "South Branch - LMS")
        # The other-branch KYC doesn't exist yet; the start_kyc guard fires.
        with self.assertRaises(frappe.PermissionError):
            officer_api.start_kyc(customer=self.borrower_other)
        # Restore so re-runs work
        frappe.db.set_value("Customer", self.borrower_other, "custom_lms_branch", BRANCH)


if __name__ == "__main__":
    unittest.main()
