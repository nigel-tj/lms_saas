"""LMS Brand Settings — desk-side brand configuration.

A single DocType that exposes the operator's brand as a desk-editable
form. On every save, the values are mirrored to:

  1. site_config.json (lms_brand_* keys) — the canonical source of truth
     read at request time.
  2. Website Settings (app_name, brand_html) — the desk chrome.
  3. System Settings (app_name) — the title bar / browser tab.

This is the desk-side equivalent of the CLI setter
`lms_saas.utils.brand.set_brand`. The setter and the desk form write
to the same places, so editing the form in the desk is functionally
identical to running `bench execute lms_saas.utils.brand.set_brand`.

See docs/BRAND_QUICKSTART.md for the full reference.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe.model.document import Document


class LMSBrandSettings(Document):
	"""Single DocType for the operator's brand. See module docstring."""

	def __init__(self, *args, **kwargs):
		"""Standard Document init, then mirror site_config → form fields.

		Frappe's `onload` hook is only called from the desk form loader,
		not from `frappe.get_single()` callers (tests, API handlers,
		bench-execute, etc). For a brand-editor Single, the desk loader
		isn't the only caller — bench-execute and tests need the form
		to reflect site_config too. So we run the same mirror here.
		"""
		super().__init__(*args, **kwargs)
		if not getattr(self, "flags", None):
			self.flags = frappe._dict()
		# Only run after load_from_db has populated fields (i.e. when
		# we got a name from the DB). Skips new-doc construction.
		if self.get("__islocal"):
			return
		try:
			self.onload()
		except Exception:  # noqa: BLE001
			# Never let a brand sync error break a document load.
			pass

	def onload(self):
		"""Populate form fields from the canonical site_config on every load.

		Without this hook, the desk form would always show the DB defaults
		(vendor-neutral "LMS") even when the operator has already set a
		brand via `lms_saas.utils.brand.set_brand` or the Frappe Cloud
		dashboard. The DB Single is the desk-side EDITOR; site_config.json
		is the canonical SOURCE OF TRUTH. On every form load, we mirror
		the source-of-truth values into the form fields so the operator
		sees what's actually live.
		"""
		# Map form field → site_config key. Anything in this map is
		# considered "owned" by site_config and refreshed on load.
		# A field NOT in this map stays as the DB default (used for
		# descriptive fields that don't have a site_config equivalent).
		field_to_conf = (
			("portal_title", "lms_brand_portal_title"),
			("tagline", "lms_brand_tagline"),
			("product_subtitle", "lms_brand_product_subtitle"),
			("footer_text", "lms_brand_footer_text"),
			("primary_color", "lms_brand_primary_color"),
			("support_email", "lms_support_email"),
			("logo_path", "lms_brand_logo_path"),
			("favicon_path", "lms_brand_favicon_path"),
			("theme_id", "lms_theme"),
		)
		for field, conf_key in field_to_conf:
			value = frappe.conf.get(conf_key)
			if value:
				# Only overwrite if the site_config has a value — never
				# clobber the DB default when site_config is empty.
				setattr(self, field, value)

	def validate(self):
		# R23-H1: validate the portal_title before we mirror it to three
		# places. A typo or unrendered placeholder would otherwise leak
		# verbatim to the portal boot, navbar, and email footers.
		from lms_saas.utils.brand import _sanitize_brand_value, _validate_brand

		if self.portal_title:
			self.portal_title = _sanitize_brand_value("portal_title", self.portal_title)
		warnings = _validate_brand(
			{
				"portal_title": self.portal_title or "",
			}
		)
		if warnings:
			# Surface the warning to the operator (banner on the form
			# after save) without blocking the save. The user has
			# to consciously fix the warning before going live.
			frappe.msgprint(
				"<br>".join(warnings),
				title="Brand validation warning",
				indicator="orange",
			)

	def on_update(self):
		"""Mirror the form values to site_config + Website + System Settings.

		Idempotent: re-saving the form with the same values is a no-op.
		"""
		# Build the kwargs the CLI setter expects.
		kwargs = {
			"portal_title": self.portal_title or None,
			"tagline": self.tagline or None,
			"footer_text": self.footer_text if self.footer_text is not None else None,
			"primary_color": self.primary_color or None,
			"support_email": self.support_email or None,
			"logo_path": self.logo_path or None,
			"favicon_path": self.favicon_path or None,
		}
		# Drop Nones so the setter only writes keys that are set.
		kwargs = {k: v for k, v in kwargs.items() if v}
		if not kwargs:
			return
		# Theme is a separate site_config key (lms_theme) — handle it
		# directly here so the setter doesn't have to special-case it.
		if self.theme_id:
			_set_site_config_key("lms_theme", self.theme_id)
			frappe.conf["lms_theme"] = self.theme_id

		from lms_saas.utils.brand import set_brand

		result = set_brand(**kwargs)
		# Surface the audit report in the form so the operator can see
		# exactly what got mirrored to which setting.
		applied = result.get("applied", [])
		failed = result.get("failed", [])
		if applied:
			frappe.msgprint(
				"<b>Mirrored to:</b><br>" + "<br>".join(applied),
				title="Brand applied",
				indicator="green",
			)
		if failed:
			frappe.msgprint(
				"<b>Failed:</b><br>" + "<br>".join(failed),
				title="Brand sync errors",
				indicator="red",
			)


def _set_site_config_key(key: str, value) -> None:
	"""Write a single key to site_config.json + in-memory frappe.conf.

	Tiny helper so the on_update hook can persist a single key without
	boilerplating the JSON read/write. Mirrors the same write site_config
	pattern that `lms_saas.utils.brand.set_brand` uses.
	"""
	site_path = Path(frappe.utils.get_site_path("site_config.json"))
	raw = json.loads(site_path.read_text() or "{}")
	raw[key] = value
	site_path.write_text(json.dumps(raw, indent=2, sort_keys=True))
	frappe.conf[key] = value
