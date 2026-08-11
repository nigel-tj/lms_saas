"""Regression test for the lms_saas whitelist bootstrap.

Frappe only registers @frappe.whitelist() methods into the handler's
`whitelisted` set when the module that declares them is imported on the
bench process. Our api/ submodules are not referenced by any auto-boot
code path, so before R35 the first request to a whitelisted method
returned 'Function ... is not whitelisted.' We register a `connect` hook
that walks every lms_saas.api.* module so the registration is populated
before any request hits the handler.

This test exercises the bootstrapper in isolation: it calls the
bootstrapper, then asserts both `get_approval_queue` and
`get_assigned_loans` are now in `frappe.whitelisted`, and that
re-running the bootstrapper is a no-op.
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock


# Ensure the bench apps are importable so the test exercises the real
# decorated functions.
BENCH_APPS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "apps")
BENCH_APPS = os.path.abspath(BENCH_APPS)
for _name in ("frappe", "lms_saas", "erpnext", "lending", "hrms"):
	_path = os.path.join(BENCH_APPS, _name)
	if _path not in sys.path:
		sys.path.insert(0, _path)


class TestLmsWhitelistBootstrap(unittest.TestCase):
	"""The lms_saas whitelist bootstrap must register the manager + officer
	whitelisted functions, and must be idempotent / safe to call repeatedly."""

	def setUp(self):
		# Reset the module-level flag so the bootstrapper actually runs.
		import lms_saas.hooks as hooks

		hooks._LMS_WHITELIST_BOOTSTRAP_DONE = False

	def test_bootstrap_registers_manager_and_officer_functions(self):
		import frappe
		import lms_saas.hooks as hooks

		# Run the bootstrapper and assert both functions are in the
		# global Frappe whitelist. (They may already be present from
		# earlier imports; the bootstrapper just needs to guarantee
		# they are in the set after it runs.)
		hooks._bootstrap_lms_whitelisted_methods()
		whitelisted_names = sorted(
			getattr(fn, "__name__", "")
			for fn in frappe.whitelisted
		)
		self.assertIn("get_approval_queue", whitelisted_names)
		self.assertIn("get_assigned_loans", whitelisted_names)
		# Idempotency: a second run is a no-op (the module-level flag
		# short-circuits).
		hooks._bootstrap_lms_whitelisted_methods()
		whitelisted_names2 = sorted(
			getattr(fn, "__name__", "")
			for fn in frappe.whitelisted
		)
		self.assertEqual(whitelisted_names, whitelisted_names2)

	def test_bootstrap_idempotent_flag(self):
		import frappe
		import lms_saas.hooks as hooks

		# Idempotency: call the bootstrapper twice and confirm the
		# whitelisted set is unchanged (no duplicates, no missing entries).
		hooks._LMS_WHITELIST_BOOTSTRAP_DONE = False
		hooks._bootstrap_lms_whitelisted_methods()
		after_first = set(frappe.whitelisted)
		hooks._bootstrap_lms_whitelisted_methods()
		after_second = set(frappe.whitelisted)
		self.assertEqual(after_first, after_second)
		self.assertTrue(hooks._LMS_WHITELIST_BOOTSTRAP_DONE)


if __name__ == "__main__":
	unittest.main()


class TestR35OnLoginRedirectFix(unittest.TestCase):
    """R35-#24 / R35-#26: the on_login hook rewrites the post-login home_page
    so portal users never get stuck on the broken /desk/lending URL."""

    def setUp(self):
        import frappe
        self._original_user = getattr(frappe.session, "user", None)
        self._original_response_home = getattr(frappe.local.response, "home_page", None)
        frappe.session.user = "Administrator"
        frappe.local.response["home_page"] = "/desk/lending"

    def tearDown(self):
        import frappe
        frappe.session.user = self._original_user or "Administrator"
        if self._original_response_home is None:
            frappe.local.response.pop("home_page", None)
        else:
            frappe.local.response["home_page"] = self._original_response_home

    def test_borrower_redirect_rewrites_desk_lending(self):
        """A borrower login must not land on /desk/lending."""
        import frappe
        from lms_saas.boot import on_login, get_lms_home_page

        login_manager = type("LM", (), {"user": "borrower@example.com"})()
        on_login(login_manager=login_manager)
        self.assertEqual(
            frappe.local.response.get("home_page"),
            get_lms_home_page(user="borrower@example.com"),
        )
        # Specifically NOT the broken URL.
        self.assertNotEqual(
            frappe.local.response.get("home_page"),
            "/desk/lending",
        )

    def test_admin_redirect_uses_actual_workspace(self):
        """An admin login must not land on the broken /desk/lending URL."""
        import frappe
        from lms_saas.boot import on_login, get_lms_home_page

        login_manager = type("LM", (), {"user": "admin@kesari.africa"})()
        on_login(login_manager=login_manager)
        target = frappe.local.response.get("home_page")
        # Must point at a real desk workspace (not /desk/lending).
        self.assertNotEqual(target, "/desk/lending")
        # And must satisfy get_lms_home_page for admin.
        self.assertEqual(target, get_lms_home_page(user="admin@kesari.africa"))

    def test_get_default_path_returns_none_for_portal_users(self):
        """R54: patched get_default_path returns None for LMS portal users
        (Customer / LMS Portal Staff) so Frappe's auth.make_session falls
        through to /" + get_home_page() which calls our hook → /lms."""
        import frappe
        import frappe.apps as apps_module
        from lms_saas import boot

        # Load boot to ensure the patch is applied. (In a test process the
        # patch fires on first import of lms_saas.boot; in production it
        # fires via boot_session hook firing get_attr.)
        boot

        original_user = getattr(frappe.session, "user", None)
        try:
            # Borrower: Customer role. Patch should return None.
            frappe.session.user = "borrower@example.com"
            self.assertIsNone(apps_module.get_default_path())

            # Loan Officer: LMS Portal Staff role. Patch should return None.
            frappe.session.user = "officer@kesari.africa"
            self.assertIsNone(apps_module.get_default_path())

            # System Manager / Administrator: no portal role. Patch should
            # fall through to the original get_default_path, which returns
            # a truthy path.
            frappe.session.user = "admin@kesari.africa"
            self.assertIsNotNone(apps_module.get_default_path())
            self.assertTrue(apps_module.get_default_path().startswith("/"))
        finally:
            frappe.session.user = original_user or "Administrator"

    def test_get_default_path_returns_none_for_guest(self):
        """R54: the patch returns None for Guest (no bypass of the /desk
        fallback for unauthenticated users)."""
        import frappe
        import frappe.apps as apps_module
        from lms_saas import boot

        boot  # ensure patch is applied

        original_user = getattr(frappe.session, "user", None)
        try:
            frappe.session.user = "Guest"
            self.assertIsNone(apps_module.get_default_path())
        finally:
            frappe.session.user = original_user or "Administrator"


if __name__ == "__main__":
    unittest.main()
