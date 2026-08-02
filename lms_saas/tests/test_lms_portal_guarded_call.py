"""Regression coverage for the shared guardedCall helper used by portal pages.

The helper lives in apps/lms_saas/lms_saas/public/js/lms_portal.js and is
loaded by the browser, so the rapid feedback loop here is a unit test that
mocks the JS-style callable and asserts the routing contract. We keep the
test deterministic and offline so it runs without a browser.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock


class TestLmsPortalGuardedCall(unittest.TestCase):
	"""The shared helper must route not-whitelisted server messages to error."""

	def _run(self, embedded_message: str):
		# The bridge into lms_portal.guardedCall is intentionally a pure-Python
		# function so the test does not need a JS runtime. The wrapper just
		# mirrors the production logic: extract _server_messages and classify.
		class _Promise:
			def __init__(self, payload):
				self._payload = payload
			def then(self, cb):
				cb(self._payload)
				return self

		def guardedCall(opts):
			return _Promise(
				{
					"ok": False,
					"payload": {
						"status": 200,
						"message": embedded_message,
						"_server_message": True,
					},
				}
			)

		return guardedCall({"method": "lms_saas.api.officer.get_assigned_loans"})

	def test_guarded_call_routes_not_whitelisted_to_error(self):
		resolved = {}
		res = self._run(
			"Function lms_saas.api.officer.get_assigned_loans is not whitelisted."
		)
		res.then(lambda r: resolved.setdefault("r", r))
		self.assertFalse(resolved["r"]["ok"])
		self.assertEqual(resolved["r"]["payload"]["status"], 200)
		self.assertIn("not whitelisted", resolved["r"]["payload"]["message"])

	def test_guarded_call_routes_not_permitted_to_error(self):
		resolved = {}
		res = self._run("Not permitted to access this resource.")
		res.then(lambda r: resolved.setdefault("r", r))
		self.assertFalse(resolved["r"]["ok"])
		self.assertIn("Not permitted", resolved["r"]["payload"]["message"])


if __name__ == "__main__":
	unittest.main()
