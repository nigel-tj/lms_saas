"""Regression tests for the Loan Officer portal QA findings (2026-08-15)."""

from __future__ import annotations

import unittest

import frappe

from lms_saas.api import labels
from lms_saas.api import officer as officer_api
from lms_saas.utils import brand
from lms_saas.utils import reports


OFFICER_EMAIL = "officer@kesari.africa"


def _set_user(user):
    frappe.set_user(user)


class TestOfficerPortalQA(unittest.TestCase):
    """Pin the QA findings from the 2026-08-15 officer-portal review."""

    def setUp(self):
        frappe.set_user("Administrator")

    # #35
    def test_lms_page_title_includes_field_visits_and_task_management(self):
        ctx = {"brand": {"portal_title": ""}}
        self.assertEqual(brand._lms_page_title("field_visits", ctx), "Field Visits")
        self.assertEqual(brand._lms_page_title("visits", ctx), "Field Visits")
        self.assertEqual(brand._lms_page_title("task_management", ctx), "Tasks")
        self.assertEqual(brand._lms_page_title("tasks", ctx), "Tasks")
        self.assertEqual(brand._lms_page_title("announcements", ctx), "Announcements")
        self.assertEqual(brand._lms_page_title("documents", ctx), "Document Center")

    def test_lms_page_title_fallback_is_vendor_neutral(self):
        ctx = {"brand": {}}
        self.assertEqual(brand._lms_page_title("not_a_real_key", ctx), "LMS")

    # #37
    def test_portfolio_summary_returns_current_count(self):
        summary = reports.portfolio_summary()
        self.assertIn("current_count", summary)
        self.assertIn("current_outstanding", summary)
        self.assertGreaterEqual(summary["current_count"], 0)
        self.assertGreaterEqual(summary["current_outstanding"], 0)

    # #38
    def test_officer_label_resolves_employee_record_id_to_name(self):
        emp_id, emp_name = frappe.db.get_value(
            "Employee", {}, ["name", "employee_name"], order_by="creation asc"
        ) or (None, None)
        if not emp_id or not emp_name:
            self.skipTest("No Employee record available to test resolution")
        resolved = labels.officer_label(emp_id, 0)
        self.assertEqual(resolved, labels._sanitise_label(emp_name))

    def test_officer_label_returns_placeholder_for_empty(self):
        self.assertIn("Awaiting", labels.officer_label(None, 0))
        self.assertIn("Awaiting", labels.officer_label("", 0))
        self.assertIn("Needs", labels.officer_label(None, 60))

    def test_officer_label_passes_through_human_name(self):
        name = "Loan Officer Jane"
        self.assertEqual(labels.officer_label(name, 0), name)
        self.assertNotIn("<", labels.officer_label("<script>alert(1)</script>", 0))

    # #36
    def test_officer_dashboard_returns_review_queue_age(self):
        _set_user(OFFICER_EMAIL)
        result = officer_api.get_officer_dashboard()
        kpis = (result or {}).get("kpis") or {}
        self.assertIn("review_queue_age", kpis)
        self.assertIsInstance(kpis["review_queue_age"], int)
        self.assertGreaterEqual(kpis["review_queue_age"], 0)


if __name__ == "__main__":
    unittest.main()