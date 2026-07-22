"""Tests for desk dashboard enhancements: pipeline, branch overview, collections, health."""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestDeskDashboard(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_dashboard_api_surface(self):
		"""New dashboard API methods exist and are callable."""
		from lms_saas.api import dashboard

		for fn in (
			"get_application_pipeline",
			"get_branch_overview",
			"get_collections_overview",
			"get_system_health",
			"invalidate_dashboard_cache",
			# Phase 2 — admin console endpoints
			"get_kyc_queue",
			"get_recent_activity",
			"get_active_branches",
		):
			self.assertTrue(callable(getattr(dashboard, fn, None)), fn)

	def test_application_pipeline(self):
		"""get_application_pipeline returns counts, total, and recent applications.

		Phase 2: counts now include every real Lending status (Draft, Open,
		Submitted, Approved, Sanctioned, Rejected, Partially Disbursed,
		Disbursed, Active, Closed, Cancelled, Withdrawn) plus a ``total``
		field for the admin console's pipeline summary line.
		"""
		from lms_saas.api.dashboard import get_application_pipeline

		result = get_application_pipeline()
		self.assertIn("counts", result)
		self.assertIn("applications", result)
		self.assertIn("total", result)
		self.assertIsInstance(result["counts"], dict)
		# Every known status should be a key in counts (even if value=0).
		for s in (
			"Draft", "Open", "Submitted", "Approved", "Sanctioned",
			"Rejected", "Partially Disbursed", "Disbursed", "Active",
			"Closed", "Cancelled", "Withdrawn",
		):
			self.assertIn(s, result["counts"], f"missing counts key: {s}")
		# total must equal sum of counts.
		self.assertEqual(result["total"], sum(result["counts"].values()))

	def test_branch_overview(self):
		"""get_branch_overview returns officer performance, exceptions, pending approvals."""
		from lms_saas.api.dashboard import get_branch_overview

		result = get_branch_overview()
		self.assertIn("officer_performance", result)
		self.assertIn("exceptions", result)
		self.assertIn("pending_approvals", result)

	def test_collections_overview(self):
		"""get_collections_overview returns today's collections, leaderboard, arrears."""
		from lms_saas.api.dashboard import get_collections_overview

		result = get_collections_overview()
		self.assertIn("today_total", result)
		self.assertIn("today_count", result)
		self.assertIn("leaderboard", result)
		self.assertIn("arrears", result)

	def test_system_health(self):
		"""get_system_health returns scheduler, integrations, errors, backup.

		Phase 2: the response now also includes scheduler_last_tick,
		error_breakdown_24h, last_backup_size_bytes, and
		last_backup_age_days for the admin console's health widget.
		"""
		from lms_saas.api.dashboard import get_system_health

		result = get_system_health()
		self.assertIn("scheduler_enabled", result)
		self.assertIn("integrations", result)
		self.assertIn("error_count_24h", result)
		self.assertIn("integrations", result)
		# Phase 2 — new keys
		self.assertIn("error_breakdown_24h", result)
		self.assertIn("last_backup_size_bytes", result)
		self.assertIn("last_backup_age_days", result)
		# Check integration keys
		for key in ("aml", "credit_bureau", "sms", "payments"):
			self.assertIn(key, result["integrations"])

	def test_get_desk_dashboard_enrichment(self):
		"""get_desk_dashboard returns truncation flag + cache_age_seconds.

		Phase 3: the response now exposes the ``truncated`` and ``limit``
		fields from ``_portfolio_metrics`` (so the admin console can warn
		if a portfolio exceeds the 50k cap) plus a ``cache_age_seconds``
		timestamp so the cache-age badge in the topbar can show "refreshed
		3 min ago" without a second round trip.
		"""
		from lms_saas.api.dashboard import get_desk_dashboard

		result = get_desk_dashboard()
		self.assertIn("kpis", result)
		self.assertIn("risk_buckets", result)
		self.assertIn("branch_outstanding", result)
		# Phase 3 — new keys
		self.assertIn("truncated", result)
		self.assertIn("limit", result)
		self.assertIn("cache_age_seconds", result)
		self.assertIsInstance(result["truncated"], bool)
		self.assertIsInstance(result["limit"], int)
		self.assertIsInstance(result["cache_age_seconds"], int)
		self.assertGreaterEqual(result["cache_age_seconds"], 0)
		self.assertLessEqual(result["cache_age_seconds"], 300)
		# limit is the 50k cap from _portfolio_metrics
		self.assertEqual(result["limit"], 50000)

	def test_get_active_branches(self):
		"""get_active_branches returns a list of active (is_group=0) Cost Centers."""
		from lms_saas.api.dashboard import get_active_branches

		result = get_active_branches()
		self.assertIn("branches", result)
		self.assertIsInstance(result["branches"], list)
		# Each entry is a {name, label} dict (could be empty on a fresh
		# install with no branches seeded).
		for b in result["branches"]:
			self.assertIn("name", b)
			self.assertIn("label", b)

	def test_get_kyc_queue(self):
		"""get_kyc_queue returns pending_count, by_status, oldest rows."""
		from lms_saas.api.dashboard import get_kyc_queue

		result = get_kyc_queue(limit=5)
		self.assertIn("pending_count", result)
		self.assertIn("by_status", result)
		self.assertIn("oldest", result)
		self.assertIsInstance(result["pending_count"], int)
		self.assertIsInstance(result["by_status"], dict)
		self.assertIsInstance(result["oldest"], list)
		# The ``oldest`` list must not exceed the limit.
		self.assertLessEqual(len(result["oldest"]), 5)
		# Each oldest row has the fields needed for the timeline UI.
		for row in result["oldest"]:
			self.assertIn("name", row)
			self.assertIn("customer", row)
			self.assertIn("kyc_status", row)
			self.assertIn("creation", row)

	def test_get_recent_activity(self):
		"""get_recent_activity returns the N most recent LMS Audit Event rows."""
		from lms_saas.api.dashboard import get_recent_activity

		result = get_recent_activity(limit=5)
		self.assertIn("events", result)
		self.assertIsInstance(result["events"], list)
		self.assertLessEqual(len(result["events"]), 5)
		# Each event has the fields needed for the timeline UI.
		for e in result["events"]:
			self.assertIn("event_type", e)
			self.assertIn("event_user", e)
			self.assertIn("event_time", e)
			self.assertIn("reference_doctype", e)
			self.assertIn("reference_name", e)
			# route is set when both reference_doctype + reference_name are present
			if e.get("reference_doctype") and e.get("reference_name"):
				self.assertIn("route", e)
				self.assertTrue(e["route"].startswith("/app/"))