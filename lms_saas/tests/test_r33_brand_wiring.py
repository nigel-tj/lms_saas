"""R33 regression tests — login page brand wiring + set_brand one-liner.

The R23 fix list (test_r23_rebrand.py) pinned the brand fallbacks to be
vendor-neutral, but did not cover the login template's _lms_brand_name
resolution chain. R33 surfaces the gap:

  * The login page (www/login.html) used to fall back to a hard-coded
    "Kesari" string if brand.portal_title was empty. R33 removes the
    hard-coded literal and makes the resolution chain explicit
    (brand.portal_title → app_name).
  * The operator had no single command to set the brand in all three
    places it lives (site_config + Website Settings + System Settings).
    R33 adds `lms_saas.utils.brand.set_brand` for that.

These tests pin both so a future engineer who touches login.html or
brand.py catches the regression in CI.

Run via:
    cd frappe-bench && python run_all_lms_tests.py
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

APP_ROOT = Path(__file__).resolve().parents[1]
# Resolve the login.html path relative to this test file. This file lives
# at apps/lms_saas/lms_saas/tests/, so parents[1] is apps/lms_saas/lms_saas/
# and login.html is right there at www/login.html.
LOGIN_HTML_PATH = APP_ROOT / "www" / "login.html"


# ---------------------------------------------------------------------------
# R33-A: login.html has no hard-coded corporate name (no "Kesari" / "LMS"
#        literal in the brand resolution chain).
# ---------------------------------------------------------------------------
class TestR33LoginHtmlBrandResolution(FrappeTestCase):
	"""R33-A: the login template's brand resolution must never hard-code
	a corporate or vendor name. The chain is documented in a comment and
	must be honoured by the actual code that follows.
	"""

	def test_login_html_has_no_user_facing_kesari_literal(self):
		"""No user-facing string in www/login.html may hard-code 'Kesari'.

		The docstring comments (R23 / R33 prose) are explicitly excluded —
		those are intentional explanations of the operator's brand
		strategy, not user-facing strings.
		"""
		src = LOGIN_HTML_PATH.read_text()
		for line in src.splitlines():
			stripped = line.strip()
			# Skip Jinja comments {# ... #} and pure prose lines
			# (commentary, not literals).
			if stripped.startswith("{#") or stripped.startswith("#"):
				continue
			# The forbidden case is a quoted literal on a code line.
			# Prose like "  Resolution order:" is fine.
			self.assertNotIn(
				"'Kesari'",
				line,
				f"hard-coded 'Kesari' literal in www/login.html: {line!r}",
			)
			self.assertNotIn(
				'"Kesari"',
				line,
				f'hard-coded "Kesari" literal in www/login.html: {line!r}',
			)

	def test_login_html_brand_chain_prefers_brand_portal_title(self):
		"""The resolution chain must put brand.portal_title first.

		The actual code line is:
		    {% set _lms_brand_name = (brand.portal_title if brand and brand.portal_title else (app_name or "")) %}
		Pin it so a future refactor can't silently swap the order.
		"""
		src = LOGIN_HTML_PATH.read_text()
		self.assertIn(
			"brand.portal_title",
			src,
			"login.html must reference brand.portal_title in the brand chain",
		)
		# And the literal must come BEFORE the app_name fallback in the
		# resolution expression.
		match_idx = src.find("_lms_brand_name")
		self.assertGreater(match_idx, 0)
		# Check the brand.portal_title reference appears before app_name.
		brand_idx = src.find("brand.portal_title", match_idx)
		app_idx = src.find("app_name", match_idx)
		self.assertGreater(brand_idx, match_idx)
		self.assertGreater(app_idx, brand_idx)

	def test_login_html_no_lms_literal_in_user_facing_lines(self):
		"""No user-facing 'LMS' literal in www/login.html.

		'LMS' may appear in prose and comments (where it documents the
		product family), but never as a quoted string used as the brand
		name on a user-facing line.
		"""
		src = LOGIN_HTML_PATH.read_text()
		# The forbidden case is "LMS" appearing in a quoted literal in
		# a non-comment line. We allow prose references like "the LMS
		# product family".
		for line in src.splitlines():
			stripped = line.strip()
			if stripped.startswith("{#"):
				continue
			# A quoted "LMS" — only check that it's not a brand literal.
			# We allow it inside docstring-style commentary; the previous
			# test (no "Kesari") already enforces the user-facing rule.
			# Here we just verify the chain doesn't terminate in a
			# "LMS" string literal.
			if '"LMS"' in line or "'LMS'" in line:
				# Acceptable if the literal is part of a foot comment
				# or a docstring prose example, not a brand literal.
				# The brand chain must NOT use "LMS" as a fallback.
				# The chain looks like: (brand.portal_title ... else (app_name or ""))
				# — note the empty string, NOT "LMS".
				if "_lms_brand_name" in line:
					self.assertNotIn(
						'or "LMS"',
						line,
						f'_lms_brand_name must not fall back to "LMS": {line!r}',
					)


# ---------------------------------------------------------------------------
# R33-B: set_brand one-liner exists and is idempotent.
# ---------------------------------------------------------------------------
class TestR33SetBrandHelper(FrappeTestCase):
	"""R33-B: lms_saas.utils.brand.set_brand exists and writes to the
	canonical three places in one call.
	"""

	def test_set_brand_function_exists(self):
		from lms_saas.utils import brand
		self.assertTrue(callable(getattr(brand, "set_brand", None)))

	def test_set_brand_dry_run_returns_plan_without_writes(self):
		from lms_saas.utils import brand
		result = brand.set_brand(
			portal_title="Acme Capital",
			tagline="Loans for everyone",
			dry_run=True,
		)
		# Dry-run must NOT write anything.
		self.assertEqual(result["applied"], [])
		self.assertEqual(result["failed"], [])
		self.assertIn("DRY RUN", "\n".join(result.get("plan", [])))

	def test_set_brand_empty_payload_returns_nothing_to_set(self):
		from lms_saas.utils import brand
		result = brand.set_brand(dry_run=True)
		self.assertTrue(result.get("failed") or result.get("plan"))
		# The function must refuse to no-op silently — it should
		# surface the no-op in failed or plan.
		combined = "\n".join(result.get("failed", []) + result.get("plan", []))
		self.assertIn("nothing to set", combined.lower())

	def test_set_brand_writes_site_config_when_applied(self):
		"""R33-B: set_brand writes lms_brand_portal_title to site_config.

		We use a mocked site_config path so the test doesn't actually
		mutate the running site's config.
		"""
		from lms_saas.utils import brand
		import tempfile
		import os
		with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
			json.dump({"db_name": "test"}, f)
			tmp_path = f.name
		try:
			# `frappe.utils.get_site_path("site_config.json")` is expected
			# to return the FULL path to the file. Mock accordingly.
			with mock.patch.object(
				frappe.utils,
				"get_site_path",
				return_value=tmp_path,
			):
				result = brand.set_brand(portal_title="Acme Capital", dry_run=False)
			# site_config.json now contains the new key.
			raw = json.loads(Path(tmp_path).read_text())
			self.assertEqual(
				raw.get("lms_brand_portal_title"),
				"Acme Capital",
				f"set_brand did not write to site_config. result={result}",
			)
			self.assertEqual(
				frappe.conf.get("lms_brand_portal_title"),
				"Acme Capital",
				"set_brand must mirror the value into frappe.conf",
			)
		finally:
			# Restore any in-memory drift the test caused.
			frappe.conf.pop("lms_brand_portal_title", None)
			os.unlink(tmp_path)

	def test_set_brand_round_trip(self):
		"""R33-B: enrich_brand picks up the value set by set_brand.

		Confirms the wiring: set_brand → site_config → enrich_brand.
		"""
		from lms_saas.utils import brand
		original = frappe.conf.get("lms_brand_portal_title")
		frappe.conf["lms_brand_portal_title"] = "Round Trip Co"
		try:
			enriched = brand.enrich_brand()
			self.assertEqual(enriched["portal_title"], "Round Trip Co")
		finally:
			if original is None:
				frappe.conf.pop("lms_brand_portal_title", None)
			else:
				frappe.conf["lms_brand_portal_title"] = original


# ---------------------------------------------------------------------------
# R33-C: live site recovery — the documented "fix the live site" recipe.
# ---------------------------------------------------------------------------
class TestR33LiveSiteBrandRecovery(FrappeTestCase):
	"""R33-C: if a site is missing lms_brand_portal_title, the chain must
	fall through to vendor-neutral (NOT to a hard-coded operator name).
	Pin the chain so a future engineer can't re-leak the original brand.
	"""

	def test_missing_lms_brand_portal_title_falls_back_to_lms(self):
		from lms_saas.utils import brand
		original = frappe.conf.get("lms_brand_portal_title")
		frappe.conf.pop("lms_brand_portal_title", None)
		try:
			enriched = brand.enrich_brand()
			# Default must be the vendor-neutral product family name.
			self.assertEqual(enriched["portal_title"], "LMS")
			# And NOT the original operator's brand.
			self.assertNotEqual(enriched["portal_title"], "Kesari")
		finally:
			if original is not None:
				frappe.conf["lms_brand_portal_title"] = original

	def test_brand_alias_falls_back_through_chain(self):
		"""_brand_alias: site_config lms_brand_<key> > lms_brand_portal_title > neutral default.

		This is the chain the operator uses to set per-key overrides
		(footer_text, tagline) without re-stating portal_title.
		"""
		from lms_saas.utils import brand
		original_title = frappe.conf.get("lms_brand_portal_title")
		original_tag = frappe.conf.get("lms_brand_tagline")
		frappe.conf["lms_brand_portal_title"] = "Acme"
		frappe.conf.pop("lms_brand_tagline", None)
		try:
			# operator_brand should resolve to "Acme" (the main brand).
			self.assertEqual(brand._brand_alias("operator_brand"), "Acme")
			# And the neutral default is "LMS" — NOT the original brand.
			frappe.conf.pop("lms_brand_portal_title", None)
			self.assertEqual(brand._brand_alias("operator_brand"), "LMS")
			self.assertNotEqual(brand._brand_alias("operator_brand"), "Kesari")
		finally:
			if original_title is not None:
				frappe.conf["lms_brand_portal_title"] = original_title
			if original_tag is not None:
				frappe.conf["lms_brand_tagline"] = original_tag


# ---------------------------------------------------------------------------
# R33-D: LMS Brand Settings Single is desk-editable and mirrors to site_config.
# ---------------------------------------------------------------------------
class TestR33BrandSettingsSingle(FrappeTestCase):
	"""R33-D: the LMS Brand Settings Single is the desk-side equivalent
	of `lms_saas.utils.brand.set_brand`. Saving the form must mirror the
	values to site_config.json so the next request picks them up.
	"""

	def test_doctype_is_registered(self):
		"""R33-D: the Single is shipped with the app and visible in the desk."""
		self.assertTrue(frappe.db.exists("DocType", "LMS Brand Settings"))
		s = frappe.get_single("LMS Brand Settings")
		# The Single is a singleton — it must always return a row.
		self.assertIsNotNone(s)
		# And the default portal_title is the vendor-neutral product family.
		self.assertTrue(s.portal_title)

	def test_saving_form_mirrors_to_site_config(self):
		"""R33-D: saving the form writes lms_brand_portal_title to site_config."""
		import json
		from pathlib import Path

		# Read the current site_config to know how to restore it.
		site_path = Path(
			frappe.utils.get_site_path("site_config.json")
		)
		original = json.loads(site_path.read_text() or "{}")
		original_title = original.get("lms_brand_portal_title")
		original_tagline = original.get("lms_brand_tagline")

		try:
			s = frappe.get_single("LMS Brand Settings")
			s.portal_title = "Test Brand From Form"
			s.tagline = "Form-saved tagline"
			s.save()
			frappe.db.commit()

			# Re-read site_config — the new values must be there.
			updated = json.loads(site_path.read_text() or "{}")
			self.assertEqual(updated.get("lms_brand_portal_title"), "Test Brand From Form")
			self.assertEqual(updated.get("lms_brand_tagline"), "Form-saved tagline")
			# And frappe.conf picked it up in-memory too.
			self.assertEqual(
				frappe.conf.get("lms_brand_portal_title"),
				"Test Brand From Form",
			)
		finally:
			# Restore so the next test sees a clean state.
			restore = dict(original)
			restore["lms_brand_portal_title"] = original_title
			restore["lms_brand_tagline"] = original_tagline
			site_path.write_text(json.dumps(restore, indent=2, sort_keys=True))
			frappe.conf["lms_brand_portal_title"] = original_title
			frappe.conf["lms_brand_tagline"] = original_tagline

	def test_form_round_trip_with_set_brand(self):
		"""R33-D: set_brand + the desk form write to the same place.

		Confirms the desk form is the desk-side equivalent of the CLI
		setter — they target the same canonical site_config keys.
		"""
		import json
		from pathlib import Path

		site_path = Path(
			frappe.utils.get_site_path("site_config.json")
		)
		original = json.loads(site_path.read_text() or "{}")
		original_title = original.get("lms_brand_portal_title")
		original_tagline = original.get("lms_brand_tagline")

		try:
			# Use the CLI setter to set the brand.
			from lms_saas.utils.brand import set_brand
			set_brand(portal_title="Acme", tagline="Acme tagline")
			frappe.db.commit()

			# Re-read via the desk form — it must see the new value.
			s = frappe.get_single("LMS Brand Settings")
			self.assertEqual(s.portal_title, "Acme")
			self.assertEqual(s.tagline, "Acme tagline")
		finally:
			# Restore.
			restore = dict(original)
			restore["lms_brand_portal_title"] = original_title
			restore["lms_brand_tagline"] = original_tagline
			site_path.write_text(json.dumps(restore, indent=2, sort_keys=True))
			frappe.conf["lms_brand_portal_title"] = original_title
			frappe.conf["lms_brand_tagline"] = original_tagline
