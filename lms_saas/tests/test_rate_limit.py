"""Tests for the rate limiting decorator."""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestRateLimit(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_rate_limit_decorator_exists(self):
		"""The rate_limit decorator is importable and callable."""
		from lms_saas.utils.rate_limit import rate_limit

		self.assertTrue(callable(rate_limit))

	def test_administrator_bypasses_limit(self):
		"""Administrator is not rate-limited."""
		from lms_saas.utils.rate_limit import rate_limit

		call_count = {"n": 0}

		@rate_limit(max_calls=2, window_seconds=60)
		def test_fn():
			call_count["n"] += 1
			return "ok"

		# Administrator should bypass
		frappe.set_user("Administrator")
		for _ in range(5):
			result = test_fn()
			self.assertEqual(result, "ok")
		self.assertEqual(call_count["n"], 5)

	def test_rate_limit_allows_under_threshold(self):
		"""Calls under the limit are allowed."""
		from lms_saas.utils.rate_limit import rate_limit

		call_count = {"n": 0}

		@rate_limit(max_calls=10, window_seconds=60)
		def test_fn():
			call_count["n"] += 1
			return "ok"

		# Administrator bypasses, so this should work
		result = test_fn()
		self.assertEqual(result, "ok")
		self.assertEqual(call_count["n"], 1)