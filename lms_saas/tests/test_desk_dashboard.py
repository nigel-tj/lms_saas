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
		):
			self.assertTrue(callable(getattr(dashboard, fn, None)), fn)

	def test_application_pipeline(self):
		"""get_application_pipeline returns counts and applications list."""
		from lms_saas.api.dashboard import get_application_pipeline

		result = get_application_pipeline()
		self.assertIn("counts", result)
		self.assertIn("applications", result)
		self.assertIsInstance(result["counts"], dict)

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
		"""get_system_health returns scheduler, integrations, errors, backup."""
		from lms_saas.api.dashboard import get_system_health

		result = get_system_health()
		self.assertIn("scheduler_enabled", result)
		self.assertIn("integrations", result)
		self.assertIn("error_count_24h", result)
		self.assertIn("integrations", result)
		# Check integration keys
		for key in ("aml", "credit_bureau", "sms", "payments"):
			self.assertIn(key, result["integrations"])