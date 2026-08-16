"""R49 regression tests — email branding and template safety.

Pins the brand-safety contract for all LMS email templates:

1. **No hardcoded operator brand** — no "Kesari", "Nigel", or
   operator-specific hex colors in any template. Brand tokens must
   come from ``get_email_brand_context()`` (which reads from
   ``site_config`` / ``Website Settings`` via ``enrich_brand()``).

2. **No ``created_by`` leak** — Frappe's default password_reset and
   new_user templates use ``{{ created_by }}`` which leaks the
   operator's personal name. The LMS overrides must NOT reference
   ``created_by``.

3. **No "Sent via ERPNext" footer** — the Email Account footer must
   be cleared by ``reconcile_email_footer`` so Frappe's default
   third-party branding doesn't leak below the LMS branded footer.

4. **raw_html=True** — ``send_branded_email`` must pass
   ``raw_html=True`` to ``frappe.sendmail`` so the LMS wrapper
   (``lms_email_base.html``) isn't double-wrapped in Frappe's
   ``standard.html``.

5. **All templates render without errors** — every registered LMS
   email body template must render with its sample context without
   raising a Jinja exception.

6. **Frappe override templates exist** — the 6 Frappe default email
   templates that LMS overrides must exist in
   ``lms_saas/templates/emails/`` so the Jinja ChoiceLoader picks
   them up before Frappe's defaults.
"""

import os
import unittest

import frappe
from frappe.tests.test_utils import FrappeTestCase

from lms_saas.utils.email import (
	EMAIL_BODY_TEMPLATES,
	EMAIL_TEMPLATE_NAMES,
	_sample_subject_and_context,
	get_email_brand_context,
	render_branded_email,
)


class TestEmailBrandingSafety(FrappeTestCase):
	"""Brand-safety contract — no hardcoded operator values in templates."""

	BRAND_LEAKS = ("Kesari", "kesari", "Nigel", "nigel", "Jena", "jena")
	OPERATOR_HEX_COLORS = ("#2f4f46", "#204941", "#bedc98")
	TEMPLATE_DIRS = [
		"templates/email",  # LMS branded body templates
		"templates/emails",  # Frappe default overrides
	]

	def _read_all_templates(self) -> str:
		"""Concatenate all email template files for leak scanning."""
		app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		chunks = []
		for d in self.TEMPLATE_DIRS:
			dir_path = os.path.join(app_root, d)
			if not os.path.isdir(dir_path):
				continue
			for fname in os.listdir(dir_path):
				if not fname.endswith(".html"):
					continue
				fpath = os.path.join(dir_path, fname)
				# Skip the deprecated placeholder.
				if fname == "lms_branded_base.html":
					continue
				with open(fpath, encoding="utf-8") as f:
					chunks.append(f.read())
		return "\n---\n".join(chunks)

	def test_no_hardcoded_operator_brand_in_templates(self):
		"""No template file may contain the operator's brand name or
		personal name. Brand must come from get_email_brand_context()."""
		content = self._read_all_templates()
		for leak in self.BRAND_LEAKS:
			self.assertNotIn(
				leak,
				content,
				f"Brand leak: '{leak}' found in an email template. "
				"Use get_email_brand_context() instead of hardcoding.",
			)

	def test_no_hardcoded_operator_hex_in_templates(self):
		"""No template file may contain a hardcoded operator hex color.
		Colors must come from brand.primary_color (overridable via
		lms_brand_primary_color in site_config)."""
		content = self._read_all_templates()
		for hex_color in self.OPERATOR_HEX_COLORS:
			self.assertNotIn(
				hex_color,
				content,
				f"Hardcoded operator hex color '{hex_color}' found in a template. "
				"Use {{ brand.primary_color }} instead.",
			)

	def test_no_created_by_in_frappe_overrides(self):
		"""Frappe's default password_reset and new_user templates use
		{{ created_by }} which leaks the operator's personal name.
		The LMS overrides must NOT reference created_by."""
		app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		override_dir = os.path.join(app_root, "templates", "emails")
		for fname in os.listdir(override_dir):
			if not fname.endswith(".html"):
				continue
			if fname == "lms_branded_base.html":
				continue
			fpath = os.path.join(override_dir, fname)
			with open(fpath, encoding="utf-8") as f:
				content = f.read()
			self.assertNotIn(
				"created_by",
				content,
				f"'{fname}' references created_by — this leaks the "
				"operator's personal name. Use brand.company_name instead.",
			)


class TestSendBrandedEmailRawHtml(FrappeTestCase):
	"""R49: send_branded_email must pass raw_html=True to prevent
	double-wrapping in Frappe's standard.html."""

	def test_send_branded_email_source_has_raw_html(self):
		"""The source code of send_branded_email must contain
		raw_html=True. This is a source-level check (not a runtime
		check) because we can't easily intercept frappe.sendmail
		kwargs in a unit test without mocking."""
		import inspect

		from lms_saas.utils.email import send_branded_email

		source = inspect.getsource(send_branded_email)
		self.assertIn(
			"raw_html=True",
			source,
			"send_branded_email must pass raw_html=True to frappe.sendmail "
			"to prevent double-wrapping in standard.html.",
		)
		self.assertIn(
			"add_css=False",
			source,
			"send_branded_email must pass add_css=False to prevent "
			"conflicting Frappe email.css styles.",
		)


class TestEmailTemplateRendering(FrappeTestCase):
	"""Every registered LMS email body template must render without errors."""

	def test_all_body_templates_render(self):
		"""Render each template with its sample context and verify
		no Jinja exception is raised and the output is non-empty."""
		for body_key in EMAIL_BODY_TEMPLATES:
			with self.subTest(body_key=body_key):
				subject, context = _sample_subject_and_context(body_key)
				html = render_branded_email(body_key, context, subject=subject)
				self.assertTrue(
					len(html) > 100,
					f"Template '{body_key}' rendered to less than 100 chars — "
					"likely a rendering error or empty template.",
				)

	def test_all_templates_contain_brand_name(self):
		"""Every rendered email must contain the brand company_name
		(from get_email_brand_context) in the header."""
		brand = get_email_brand_context()
		company = brand["company_name"]
		for body_key in EMAIL_BODY_TEMPLATES:
			with self.subTest(body_key=body_key):
				subject, context = _sample_subject_and_context(body_key)
				html = render_branded_email(body_key, context, subject=subject)
				self.assertIn(
					company,
					html,
					f"Template '{body_key}' does not contain the brand "
					f"company_name '{company}' in the rendered output.",
				)

	def test_all_templates_contain_primary_color(self):
		"""Every rendered email must contain the brand primary_color
		in the header background — proving the color is theme-driven,
		not hardcoded."""
		brand = get_email_brand_context()
		color = brand["primary_color"]
		for body_key in EMAIL_BODY_TEMPLATES:
			with self.subTest(body_key=body_key):
				subject, context = _sample_subject_and_context(body_key)
				html = render_branded_email(body_key, context, subject=subject)
				self.assertIn(
					color,
					html,
					f"Template '{body_key}' does not contain the brand "
					f"primary_color '{color}' — the color may be hardcoded "
					"instead of using {{ primary_color }}.",
				)


class TestFrappeOverrideTemplatesExist(FrappeTestCase):
	"""The 6 Frappe default email templates that LMS overrides must
	exist in lms_saas/templates/emails/ so the Jinja ChoiceLoader
	picks them up before Frappe's defaults."""

	EXPECTED_OVERRIDES = [
		"password_reset.html",
		"login_with_email_link.html",
		"new_user.html",
		"verification_code.html",
		"user_invitation.html",
		"account_deletion_notification.html",
	]

	def test_override_templates_exist(self):
		app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		override_dir = os.path.join(app_root, "templates", "emails")
		for fname in self.EXPECTED_OVERRIDES:
			fpath = os.path.join(override_dir, fname)
			self.assertTrue(
				os.path.isfile(fpath),
				f"Frappe override template '{fname}' not found in "
				f"{override_dir}. Without it, Frappe's default (with "
				"created_by / 'Sent via ERPNext') will be used.",
			)

	def test_override_templates_use_brand_context(self):
		"""Every Frappe override template must call
		get_email_brand_context() — not hardcode the brand name."""
		app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		override_dir = os.path.join(app_root, "templates", "emails")
		for fname in self.EXPECTED_OVERRIDES:
			fpath = os.path.join(override_dir, fname)
			with open(fpath, encoding="utf-8") as f:
				content = f.read()
			self.assertIn(
				"get_email_brand_context",
				content,
				f"'{fname}' must call get_email_brand_context() to get "
				"brand tokens — no hardcoded operator names.",
			)


class TestEmailAccountFooterReconcile(FrappeTestCase):
	"""R49: reconcile_email_footer clears the Email Account footer."""

	def test_reconcile_email_footer_function_exists(self):
		"""The reconcile_email_footer function must be importable."""
		from lms_saas.setup.configure_live_email import reconcile_email_footer

		self.assertTrue(callable(reconcile_email_footer))

	def test_reconcile_email_footer_is_idempotent(self):
		"""Running reconcile_email_footer twice must not raise."""
		from lms_saas.setup.configure_live_email import reconcile_email_footer

		# First call — may or may not find an Email Account.
		try:
			reconcile_email_footer()
		except Exception as e:
			self.fail(f"reconcile_email_footer() raised on first call: {e}")
		# Second call — must be a no-op.
		try:
			reconcile_email_footer()
		except Exception as e:
			self.fail(f"reconcile_email_footer() raised on second call: {e}")


class TestNewEmailTemplatesRegistered(FrappeTestCase):
	"""R49: the 4 new LMS email templates must be registered in
	EMAIL_BODY_TEMPLATES and EMAIL_TEMPLATE_NAMES."""

	def test_new_templates_in_body_templates(self):
		for key in ("loan_approved", "loan_rejected", "collection_reminder", "kyc_expiring"):
			self.assertIn(
				key,
				EMAIL_BODY_TEMPLATES,
				f"'{key}' not registered in EMAIL_BODY_TEMPLATES.",
			)

	def test_new_templates_in_template_names(self):
		for key in ("loan_approved", "loan_rejected", "collection_reminder", "kyc_expiring"):
			self.assertIn(
				key,
				EMAIL_TEMPLATE_NAMES,
				f"'{key}' not registered in EMAIL_TEMPLATE_NAMES.",
			)

	def test_new_template_files_exist(self):
		app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		for fname in (
			"loan_approved_body.html",
			"loan_rejected_body.html",
			"collection_reminder_body.html",
			"kyc_expiring_body.html",
		):
			fpath = os.path.join(app_root, "templates", "email", fname)
			self.assertTrue(
				os.path.isfile(fpath),
				f"New template file '{fname}' not found in templates/email/.",
			)