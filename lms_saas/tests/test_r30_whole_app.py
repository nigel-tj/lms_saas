"""R30 regression tests — Whole-app adversarial review.

Covers EXPERT_BOARD_REPORT_R30_WHOLE_APP.md findings:

- B1: procurement.get_procurement_stats — sum() string + frappe.db.sum
- B2/B3: compliance.get_sandbox_report — count() string + sum() string
- B4: budgeting — three sum(debit)-sum(credit) strings + sum(disbursed_amount)
- B5: announcements.get_announcement_stats — references missing
  `LMS Announcement Acknowledgement` child table
- B6: recruitment.get_staffing_plan — requests `branch` field unconditionally
- B8: procurement — uses non-existent `frappe.db.sum`
- B9: budgeting.get_forecast — projection loop strftime crash
"""

from __future__ import annotations

import unittest

import frappe

from lms_saas.api import (
	announcements,
	budgeting,
	compliance,
	procurement,
	recruitment,
)


class R30ProcurementTests(unittest.TestCase):
	"""R30-B1: dict aggregate syntax. R30-B8: drop frappe.db.sum."""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		frappe.flags.ignore_permissions = True

	def test_get_procurement_stats_no_crash(self):
		"""B1: was `fields=["sum(grand_total) as total"]` → ValidationError.
		B8: was `frappe.db.sum(...)` → AttributeError. Both fixed."""
		out = procurement.get_procurement_stats()
		self.assertIsInstance(out, dict)
		# Must contain the spend key (could be 0)
		self.assertIn("total_spend_this_month", out)
		# monthly_spend should be a list of {label, value} dicts
		for row in out.get("monthly_spend", []):
			self.assertIn("label", row)
			self.assertIn("value", row)
			self.assertIsInstance(row["value"], (int, float))


class R30ComplianceTests(unittest.TestCase):
	"""R30-B2/B3: dict aggregate syntax on disbursements and repayments."""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		frappe.flags.ignore_permissions = True

	def test_get_sandbox_report_no_crash(self):
		"""B2/B3: was `fields=["count(name) as count", "sum(...) as value"]`
		→ ValidationError. Fixed by `{"COUNT": "name", "as": "count"}` and
		`{"SUM": "...", "as": "value"}`."""
		out = compliance.get_sandbox_report()
		self.assertIsInstance(out, dict)
		# transactions dict with count + value
		tx = out.get("transactions", {})
		self.assertIn("disbursements_count", tx)
		self.assertIn("disbursements_value", tx)
		self.assertIn("repayments_count", tx)
		self.assertIn("repayments_value", tx)


class R30BudgetingTests(unittest.TestCase):
	"""R30-B4 + B9: fix SQL fn strings + projection-loops strftime."""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		frappe.flags.ignore_permissions = True

	def test_get_forecast_no_crash(self):
		"""B4: historical loop’s `sum(disbursed_amount)` string → ValidationError.
		B9: projection loop’s `add_months(today(), i).strftime(...)` → AttributeError.
		Both fixed."""
		out = budgeting.get_forecast(months=3)
		self.assertIsInstance(out, dict)
		self.assertIn("historical", out)
		self.assertIn("forecast", out)
		# Historical rows must have month strings
		for row in out["historical"]:
			self.assertIn("month", row)
			self.assertIsInstance(row["month"], str)
			# YYYY-MM format
			self.assertEqual(len(row["month"].split("-")), 2)
		# Forecast rows must have month strings (B9)
		for row in out["forecast"]:
			self.assertIn("month", row)
			self.assertEqual(len(row["month"].split("-")), 2)

	def test_get_variance_analysis_no_crash(self):
		"""B4 helper used by variance analysis."""
		out = budgeting.get_variance_analysis(threshold=10)
		self.assertIsInstance(out, dict)
		self.assertIn("variances", out)
		self.assertIn("threshold", out)

	def test_get_budgeting_stats_no_crash(self):
		"""B4 helper used by budget dashboard."""
		out = budgeting.get_budgeting_stats()
		self.assertIsInstance(out, dict)
		self.assertIn("total_budgets", out)
		self.assertIn("accounts_over_budget", out)

	def test_get_budget_vs_actual_no_crash(self):
		"""B4 helper used by budget-vs-actual view."""
		out = budgeting.get_budget_vs_actual()
		self.assertIsInstance(out, dict)
		self.assertIn("comparisons", out)


class R30AnnouncementsTests(unittest.TestCase):
	"""R30-B5: missing `LMS Announcement Acknowledgement` child-table DocType."""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		frappe.flags.ignore_permissions = True
		cls._created = []

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.flags.ignore_permissions = True
		for name in cls._created:
			frappe.db.delete("LMS Announcement Acknowledgement", {"parent": name})
			frappe.db.delete("LMS Announcement", name)
		frappe.db.commit()

	def _make_announcement(self, title: str = "R30 Test") -> str:
		out = announcements.create_announcement(
			title=title,
			body="R30 regression test body",
			target_persona="All Staff",
			requires_acknowledgement=True,
		)
		self._created.append(out["name"])
		return out["name"]

	def test_get_announcement_stats_no_crash(self):
		"""B5: was failing with `DoesNotExistError` because the
		`LMS Announcement Acknowledgement` DocType was missing. We forced
		its migration in R30 — get_announcement_stats now rounds-up the
		child table."""
		out = announcements.get_announcement_stats()
		self.assertIsInstance(out, dict)
		self.assertIn("total", out)
		self.assertIn("published", out)
		self.assertIn("total_acknowledgements", out)
		# Numeric
		self.assertIsInstance(out["total_acknowledgements"], int)

	def test_acknowledge_announcement_writes_child_table(self):
		"""B5: ack rows are stored on the parent's child table; the
		DocType is now registered in the DB."""
		name = self._make_announcement("R30 Ack Test")
		ack = announcements.acknowledge_announcement(name)
		self.assertTrue(ack.get("ok"))
		# Verify a child row exists
		row = frappe.db.exists(
			"LMS Announcement Acknowledgement",
			{"parent": name, "user": "Administrator"},
		)
		self.assertTrue(row, "Expected an ack row in the child table")

	def test_acknowledge_announcement_twice_is_idempotent(self):
		"""B5: re-ack must return already_acknowledged=True without writing
		duplicate rows."""
		name = self._make_announcement("R30 Idempotent Test")
		first = announcements.acknowledge_announcement(name)
		second = announcements.acknowledge_announcement(name)
		self.assertTrue(first.get("ok"))
		self.assertTrue(second.get("ok"))
		self.assertTrue(second.get("already_acknowledged"))
		# Count rows
		c = frappe.db.count(
			"LMS Announcement Acknowledgement",
			{"parent": name, "user": "Administrator"},
		)
		self.assertEqual(c, 1, "Re-ack must not duplicate child rows")


class R30RecruitmentTests(unittest.TestCase):
	"""R30-B6: guard `branch` field on Staffing Plan (which doesn't have one)."""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		frappe.flags.ignore_permissions = True

	def test_get_staffing_plan_no_crash(self):
		"""B6: requests `branch` field on Staffing Plan unconditionally —
		Fixed via `meta.has_field('branch')` guard. Was throwing
		OperationalError(1054, "Unknown column 'branch' in 'SELECT'")."""
		out = recruitment.get_staffing_plan()
		self.assertIsInstance(out, dict)
		self.assertIn("plans", out)
		self.assertIn("actual_headcount", out)
		self.assertIn("branch", out)
		# Each plan (if any) must have only the requested fields
		for plan in out["plans"]:
			# The fields we requested (or the subset) should be present
			self.assertIn("name", plan)
			self.assertIn("from_date", plan)


if __name__ == "__main__":
	unittest.main()
