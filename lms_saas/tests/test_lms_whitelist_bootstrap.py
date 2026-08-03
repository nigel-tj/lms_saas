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
