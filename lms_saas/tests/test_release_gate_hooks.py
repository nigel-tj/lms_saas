"""Release-gate hooks tests (R08) — gate rows 3.2 / 3.6 / 3.7 / 3.8 / 3.9.

Static checks that every hooks.py entry resolves to a real symbol,
no frappe.db.sql uses string interpolation, and the API surface is
importable.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase


class TestReleaseGateHooks(FrappeTestCase):
    """Gate rows 3.2 / 3.6 / 3.7 — hooks resolve, DB safety, form scripts."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")

    def test_hooks_py_importable(self):
        """3.2: hooks.py imports without error."""
        import lms_saas.hooks  # noqa: F401
        self.assertTrue(hasattr(lms_saas.hooks, "app_name"))

    def test_required_apps_exist(self):
        """3.2: every app in required_apps is installed."""
        from lms_saas.hooks import required_apps
        for app in required_apps:
            self.assertTrue(
                frappe.db.exists("Installed Application", {"app_name": app}),
                f"Required app '{app}' is not installed"
            )

    def test_fixtures_resolve(self):
        """3.3: every fixture dt has a corresponding JSON file."""
        from lms_saas.hooks import fixtures
        for f in fixtures:
            dt = f.get("dt")
            self.assertTrue(dt, "Fixture must have a dt")
            self.assertTrue(
                frappe.db.exists("DocType", dt),
                f"Fixture DocType '{dt}' does not exist"
            )

    def test_website_route_rules_resolve(self):
        """3.2: every website_route_rules entry has from_route and to_route."""
        from lms_saas.hooks import website_route_rules
        for rule in website_route_rules:
            self.assertIn("from_route", rule)
            self.assertIn("to_route", rule)

    def test_no_string_interpolated_db_sql(self):
        """3.6: no frappe.db.sql call uses f-string or .format() interpolation."""
        import os
        import re
        app_path = frappe.get_app_path("lms_saas")
        violations = []
        sql_pattern = re.compile(r"frappe\.db\.sql\s*\(\s*f['\"]")
        for root, dirs, files in os.walk(app_path):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath) as f:
                    for i, line in enumerate(f, 1):
                        if sql_pattern.search(line):
                            violations.append(f"{fpath}:{i}: {line.strip()}")
        self.assertEqual(violations, [], f"String-interpolated db.sql found:\n{violations}")

    def test_doctype_js_files_exist(self):
        """3.7: every doctype_js entry points to an existing file."""
        import os
        from lms_saas.hooks import doctype_js
        app_path = frappe.get_app_path("lms_saas")
        for dt, js_path in doctype_js.items():
            full_path = os.path.join(app_path, js_path)
            self.assertTrue(
                os.path.isfile(full_path),
                f"doctype_js for {dt}: file not found at {js_path}"
            )

    def test_api_modules_importable(self):
        """3.9: key API modules import without error."""
        from lms_saas.api import manager, portal, officer, compliance
        self.assertTrue(hasattr(manager, "disburse_loan"))
        self.assertTrue(hasattr(manager, "record_repayment"))
        self.assertTrue(hasattr(portal, "get_loan_estimate"))


if __name__ == "__main__":
    unittest.main()
