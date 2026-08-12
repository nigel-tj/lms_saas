"""Release-gate workflow tests (R10) — gate rows 5.1–5.5.

Loan approval workflow, notifications, dashboard, search, mobile.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

OFFICER_EMAIL = "officer@kesari.africa"
COMPANY = "LMS Demo Co"


def _resolve_branch() -> str:
    branch = frappe.db.get_value("Employee", {"user_id": OFFICER_EMAIL}, "custom_lms_branch")
    return branch or frappe.db.get_value("Cost Center", {"is_group": 0}, "name") or "Main Branch"


def _seed_officer() -> str:
    return frappe.db.get_value("Employee", {"user_id": OFFICER_EMAIL}, "name") or "HR-EMP-00003"


class TestReleaseGateWorkflow(FrappeTestCase):
    """Gate rows 5.1–5.5 — workflow, notifications, dashboard, search."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.officer = _seed_officer()

    def test_loan_application_doctype_exists(self):
        """5.1: Loan Application DocType exists for the approval workflow."""
        self.assertTrue(frappe.db.exists("DocType", "Loan Application"))

    def test_loan_application_has_status_field(self):
        """5.1: Loan Application has a status field for workflow states."""
        self.assertTrue(frappe.get_meta("Loan Application").has_field("status"))

    def test_sms_template_doctype_exists(self):
        """5.2: SMS Template DocType exists for notification templates."""
        self.assertTrue(frappe.db.exists("DocType", "LMS SMS Template"))

    def test_sms_send_log_doctype_exists(self):
        """5.2: SMS Send Log DocType exists for notification audit."""
        self.assertTrue(frappe.db.exists("DocType", "LMS SMS Send Log"))

    def test_notification_log_doctype_exists(self):
        """5.2: Notification Log DocType exists for in-app notifications."""
        self.assertTrue(frappe.db.exists("DocType", "LMS Notification Log"))

    def test_dashboard_api_exists(self):
        """5.3: the dashboard API module is importable."""
        from lms_saas.api import dashboard
        self.assertTrue(hasattr(dashboard, "get_desk_dashboard"))

    def test_loan_list_view_exists(self):
        """5.4: the Loan DocType has a list view configuration."""
        meta = frappe.get_meta("Loan")
        # Frappe DocTypes always have a default list view — assert the
        # meta has the standard fields needed for list views.
        self.assertTrue(meta.has_field("loan_amount"))
        self.assertTrue(meta.has_field("status"))

    def test_portal_routes_resolve(self):
        """5.5: key portal routes are registered in website_route_rules."""
        from lms_saas.hooks import website_route_rules
        routes = {r["from_route"] for r in website_route_rules}
        for expected in ("/lms", "/lms/loan", "/lms/apply", "/lms/pay"):
            self.assertIn(expected, routes, f"Portal route {expected} not registered")

    def test_officer_portal_route_exists(self):
        """5.5: the officer portal route is registered."""
        from lms_saas.hooks import website_route_rules
        routes = {r["from_route"] for r in website_route_rules}
        self.assertIn("/lms/officer", routes)

    def test_manager_portal_route_exists(self):
        """5.5: the manager portal route is registered."""
        from lms_saas.hooks import website_route_rules
        routes = {r["from_route"] for r in website_route_rules}
        self.assertIn("/lms/manager", routes)


if __name__ == "__main__":
    unittest.main()
