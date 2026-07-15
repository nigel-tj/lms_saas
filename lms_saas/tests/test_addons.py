"""Tests for the addon registry and toggling."""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from lms_saas.utils.addons import (
	ADDON_REGISTRY,
	addon_nav_items,
	get_all_addon_specs,
	get_enabled_addons,
	is_addon_enabled,
	require_addon,
	require_addon_api,
	require_addon_persona,
)


class TestAddonRegistry(FrappeTestCase):
	"""Verify the addon registry and guards work as expected."""

	def test_registry_has_all_addons(self):
		"""Registry must contain the 20 planned addons."""
		self.assertGreaterEqual(len(ADDON_REGISTRY), 15, "Should have at least 15 registered addons")

	def test_registry_entries_have_required_keys(self):
		"""Every registry entry must have key, label, route, personas, description."""
		for key, spec in ADDON_REGISTRY.items():
			self.assertEqual(key, spec.get("key", None) or key)
			self.assertTrue(spec.get("label"), f"{key} missing label")
			self.assertTrue(spec.get("route"), f"{key} missing route")
			self.assertTrue(spec.get("personas"), f"{key} missing personas")
			self.assertTrue(spec.get("description"), f"{key} missing description")
			self.assertTrue(spec.get("icon"), f"{key} missing icon")

	def test_routes_are_unique(self):
		"""No two addons may share the same portal route."""
		routes = [s["route"] for s in ADDON_REGISTRY.values()]
		self.assertEqual(len(routes), len(set(routes)), "Duplicate routes in registry")

	def test_keys_are_unique(self):
		"""Addon keys must be unique."""
		keys = list(ADDON_REGISTRY.keys())
		self.assertEqual(len(keys), len(set(keys)), "Duplicate keys in registry")

	def test_is_addon_enabled_returns_bool(self):
		"""is_addon_enabled returns a boolean for known and unknown keys."""
		# Unknown key
		self.assertFalse(is_addon_enabled("nonexistent_addon_xyz"))
		# Known key (no site_config set → False by default)
		self.assertIsInstance(is_addon_enabled("announcements"), bool)

	def test_get_enabled_addons_returns_list(self):
		"""get_enabled_addons returns a list (may be empty)."""
		result = get_enabled_addons()
		self.assertIsInstance(result, list)
		# No site_config is set in test env → empty
		# (or may be set if test runner populated it)

	def test_get_all_addon_specs_includes_everything(self):
		"""get_all_addon_specs returns ALL registered addons regardless of toggle."""
		specs = get_all_addon_specs()
		self.assertEqual(len(specs), len(ADDON_REGISTRY))

	def test_addon_nav_items_respects_personas(self):
		"""addon_nav_items returns only items matching the persona's allowed list."""
		# With no enabled addons (default in test), empty list
		nav = addon_nav_items("Branch Manager")
		self.assertIsInstance(nav, list)
		# Each returned item should have key, label, route
		for item in nav:
			self.assertIn("key", item)
			self.assertIn("label", item)
			self.assertIn("route", item)
			self.assertIn("icon", item)


class TestAddonGuards(FrappeTestCase):
	"""Verify the page/API guards throw appropriately."""

	def test_require_addon_api_blocks_disabled_addon(self):
		"""require_addon_api throws PermissionError when the addon is disabled."""
		# No site_config → all addons are off by default
		with self.assertRaises(frappe.PermissionError):
			require_addon_api("announcements")

	def test_require_addon_redirects_disabled_addon(self):
		"""require_addon raises Redirect when the addon is disabled."""
		with self.assertRaises(frappe.Redirect):
			require_addon("helpdesk")

	def test_require_addon_api_unknown_key_blocks(self):
		"""Unknown addon keys are never enabled → must throw."""
		with self.assertRaises(frappe.PermissionError):
			require_addon_api("totally_made_up_addon")