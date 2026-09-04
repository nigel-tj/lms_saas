"""R58 regression: Field Collection UI renders the Overdue bucket + KPI.

Ticket #81 (UI slice of #77): the server now returns bucket-tagged rows and
per-bucket KPI totals (#80); the collector page must render them. Pinned at
the JS-source seam (prior art: R57 collect-modal currency tests) — the same
lms_collect_pwa.js source the browser executes. These tests assert the
rendering CONTRACT: bucket separation, KPI strip entry, honest empty
states, and that every collect/promise/reveal binding keeps working on
overdue rows.
"""

from __future__ import annotations

import os
import re
import unittest


JS_PATH = "apps/lms_saas/lms_saas/public/js/lms_collect_pwa.js"


def _read_collect_js() -> str:
	# The bench symlinks apps/lms_saas into frappe-bench/apps/, so
	# frappe.get_app_path lands on the workspace app; the JS lives at
	# <app_root>/lms_saas/public/js/lms_collect_pwa.js.
	import frappe

	app_root = frappe.get_app_path("lms_saas")
	path = os.path.join(app_root, "lms_saas", "public", "js", "lms_collect_pwa.js")
	if not os.path.exists(path):
		# fallback: R57's documented layout (<app_root>/public/js/...)
		path = os.path.join(app_root, "public", "js", "lms_collect_pwa.js")
	with open(path) as f:
		return f.read()


class TestRunSheetOverdueRendering(unittest.TestCase):
	"""The collector page must render what the server now sends."""

	def setUp(self):
		self.src = _read_collect_js()

	def test_rows_carry_bucket_into_renderer(self):
		"""_loadRunSheet passes kpis to the renderer alongside rows."""
		self.assertIn(
			"r.message.kpis",
			self.src,
			"_loadRunSheet must read the per-bucket KPI payload (#80) and hand it to the renderer",
		)
		# R59: the renderer also receives the collector's own "collected
		# today" totals — the strip leads with that card, so it must be
		# fed from the same payload the server computed, not recomputed.
		self.assertIn(
			"r.message.collected_today",
			self.src,
			"_loadRunSheet must read the collected-today payload (R59) and hand it to the renderer",
		)
		self.assertIn(
			"_renderRunSheet(root, rows, kpis, collectedToday)",
			self.src,
			"renderer must receive kpis so the strip and lists cannot disagree",
		)

	def test_renderer_accepts_kpis_parameter(self):
		"""_renderRunSheet signature takes (root, rows, kpis, collectedToday)."""
		self.assertRegex(
			self.src,
			r"_renderRunSheet\s*=\s*function\s*\(\s*root\s*,\s*rows\s*,\s*kpis\s*,\s*collectedToday\s*\)",
			"_renderRunSheet must accept (root, rows, kpis, collectedToday)",
		)

	def test_overdue_list_rendered_above_upcoming(self):
		"""Overdue rows render in their own list, positioned before upcoming."""
		# The renderer must split rows by bucket and render two lists.
		self.assertIn(
			'"overdue"',
			self.src,
			"renderer must split rows on the overdue bucket tag",
		)
		self.assertIn(
			'"upcoming"',
			self.src,
			"renderer must split rows on the upcoming bucket tag",
		)
		# Overdue heading class must exist in the renderer and precede the
		# upcoming heading class (searching classes avoids comment matches
		# and HTML-escaping issues).
		overdue_idx = self.src.find('lms-overdue-heading')
		upcoming_idx = self.src.find('lms-upcoming-heading')
		self.assertGreater(overdue_idx, -1, "an 'Overdue' list heading must be rendered")
		self.assertGreater(upcoming_idx, -1, "an upcoming list heading must be rendered")
		self.assertLess(
			overdue_idx,
			upcoming_idx,
			"the Overdue list must be rendered above the upcoming list",
		)

	def test_overdue_kpi_in_strip(self):
		"""The KPI strip gains an Overdue entry fed from the server kpis."""
		self.assertRegex(
			self.src,
			r"label:\s*\"Overdue\"",
			"KPI strip must include an 'Overdue' entry",
		)
		# It must be fed from kpis, not recomputed from rows (R35-#27:
		# single source of truth — the server totals the scoped rows).
		# The strip references variables derived from the kpis payload;
		# pin that derivation, not the inline expression.
		self.assertRegex(
			self.src,
			r"kpiOverdue\w+\s*=\s*[^;]*kpis",
			"Overdue KPI values must be derived from the server kpis payload",
		)

	def test_honest_empty_states(self):
		"""Empty states distinguish 'no arrears' from 'no upcoming dues'."""
		self.assertIn(
			"No arrears — nothing overdue",
			self.src,
			"overdue list needs its own empty-state message",
		)
		self.assertIn(
			"No upcoming dues in range",
			self.src,
			"upcoming list needs its own empty-state message (not the old blanket 'No dues in range')",
		)
		self.assertNotIn(
			"No dues in range.",
			self.src,
			"the old blanket empty-state must be gone — it read as 'no work' during arrears",
		)

	def test_collect_bindings_apply_to_both_buckets(self):
		"""Collect/Promise/Reveal buttons are bound via shared selectors so overdue rows work identically."""
		# The renderer emits rows through ONE named builder used by both
		# bucket lists — verified by the builder emitting the collect
		# button and both lists calling the same builder.
		builder_idx = self.src.find("lms_collect._runSheetRowHtml = function")
		self.assertGreater(builder_idx, -1, "shared row builder must exist")
		builder_end = self.src.find("lms_collect._renderRunSheet", builder_idx)
		builder_body = self.src[builder_idx:builder_end]
		self.assertIn(
			"lms-collect-btn",
			builder_body,
			"the shared row builder must emit the collect button",
		)
		self.assertIn(
			"lms-promise-btn",
			builder_body,
			"the shared row builder must emit the promise button",
		)
		# The bucket split must reuse the same builder for both lists.
		self.assertEqual(
			2,
			self.src.count("lms_collect._runSheetRowHtml(row,"),
			"both bucket loops must call the shared row builder (exactly twice)",
		)

	def test_legacy_single_list_callers_updated(self):
		"""All internal _renderRunSheet call sites pass the kpis argument."""
		call_sites = re.findall(r"_renderRunSheet\(([^)]*)\)", self.src)
		self.assertTrue(call_sites, "renderer call sites must exist")
		for args in call_sites:
			self.assertEqual(
				4,
				len([a for a in args.split(",") if a.strip()]),
				f"_renderRunSheet called without (root, rows, kpis, collectedToday): _renderRunSheet({args})",
			)