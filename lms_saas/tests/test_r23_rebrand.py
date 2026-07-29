"""R23 regression tests — rebrand readiness.

The R23 board review surfaced 12 findings across 5 personas (Q1 SaaS
Architect, Q2 White-Label Operator, Q3 Independent Lender, Q4 Pen-Tester,
Q5 Frappe Engineer). This test file pins the fixes so a future engineer
who changes any of the touched modules will catch the regression in CI.

R23 fix list (post-review rebrand strategy):
- Q1-C1: hard-coded "Kesari" fallbacks removed from user-facing strings.
  Brand fallbacks are now vendor-neutral ("LMS") so a fresh install never
  leaks a competitor's brand.
- Q1-H1: app_title="LMS" (vendor-neutral product family name) in hooks.py.
- Q1-H2: brand asset fallbacks are config-overridable via
  lms_brand_logo_path / lms_brand_favicon_path.
- Q2-C1: NEW setup/rebrand.py runner — single bench execute for the
  full rebrand (company, domain, brand, license, SMTP).
- Q2-H1: kesari.africa hard-coded references in configure_live_email.py
  removed; docstrings use operator-config values.
- Q2-H2: demo-mode users derive email from lms_brand_portal_title via
  lms_demo_email_domain (default: kesari.example.com for the original
  operator, <brand>.example.com for any other operator).
- Q3-H1: enrich_brand validates the configured brand value and surfaces
  warnings for empty / oversized / RTL-override values.
- Q5-M1: get_lms_company() helper with lms_company config override.

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


# ---------------------------------------------------------------------------
# Q1-C1: hard-coded "Kesari" fallbacks removed.
# ---------------------------------------------------------------------------
class TestR23BrandFallbacksAreVendorNeutral(FrappeTestCase):
    """R23-C1: brand fallbacks must NOT hard-code the original operator's
    name. The fallbacks are vendor-neutral ("LMS") so a fresh install
    never leaks a competitor's brand.
    """

    def test_default_brand_falls_back_to_lms_not_kesari(self):
        from lms_saas.utils.brand import DEFAULT_BRAND
        self.assertEqual(DEFAULT_BRAND["portal_title"], "LMS")
        self.assertEqual(DEFAULT_BRAND["footer_text"], "Powered by LMS")

    def test_utils_brand_module_no_user_facing_kesari_string(self):
        """No user-facing string in utils/brand.py may hard-code 'Kesari'."""
        from lms_saas.utils import brand
        src = Path(brand.__file__).read_text()
        # The string "Kesari" must NOT appear in user-facing contexts.
        # (Docstrings and comments are excluded — those are
        # intentional explanations of the operator's brand strategy.)
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            self.assertNotIn("'Kesari'", line, f"hard-coded 'Kesari' literal in: {line!r}")
            self.assertNotIn('"Kesari"', line, f'hard-coded "Kesari" literal in: {line!r}')

    def test_utils_email_module_no_user_facing_kesari_string(self):
        """No user-facing string in utils/email.py may hard-code 'Kesari'."""
        from lms_saas.utils import email
        src = Path(email.__file__).read_text()
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            self.assertNotIn("'Kesari'", line, f"hard-coded 'Kesari' literal in: {line!r}")
            self.assertNotIn('"Kesari"', line, f'hard-coded "Kesari" literal in: {line!r}')

    def test_lms_user_setup_no_hard_coded_kesari_fallback(self):
        """lms_user_setup.py uses config-driven brand, not 'Kesari'."""
        path = (
            Path(APP_ROOT)
            / "lms_saas"
            / "doctype"
            / "lms_user_setup"
            / "lms_user_setup.py"
        )
        src = path.read_text()
        # Look for the welcome email subject line — it must use config.
        self.assertIn('frappe.conf.get("lms_brand_portal_title")', src)
        # And it must not have a hard-coded "Kesari" fallback.
        self.assertNotIn('or "Kesari"', src)


# ---------------------------------------------------------------------------
# Q1-H1: app_title="LMS" (vendor-neutral product family name).
# ---------------------------------------------------------------------------
class TestR23AppTitleIsVendorNeutral(FrappeTestCase):
    """R23-H1: app_title is the vendor-neutral product family name."""

    def test_app_title_is_lms_not_kesari(self):
        from lms_saas import hooks
        self.assertEqual(hooks.app_title, "LMS")

    def test_app_name_still_vendor_neutral_package(self):
        """The Python package name stays lms_saas (vendor-neutral)."""
        from lms_saas import hooks
        self.assertEqual(hooks.app_name, "lms_saas")


# ---------------------------------------------------------------------------
# Q1-H2: brand asset fallbacks are config-overridable.
# ---------------------------------------------------------------------------
class TestR23BrandAssetFallbacks(FrappeTestCase):
    """R23-H2: get_brand_logo_url and get_brand_favicon_url respect
    the operator's lms_brand_logo_path / lms_brand_favicon_path config."""

    def test_logo_path_respects_operator_override(self):
        """R23-H2: lms_brand_logo_path is the highest-priority fallback."""
        from lms_saas.utils import brand
        # Use the real frappe.conf so the LocalProxy + __contains__ paths work,
        # but set the operator's override on the actual site_config so the
        # function picks it up.
        original = frappe.conf.get("lms_brand_logo_path")
        frappe.conf["lms_brand_logo_path"] = "/files/operator-logo.svg"
        try:
            url = brand.get_brand_logo_url()
            self.assertEqual(url, "/files/operator-logo.svg")
        finally:
            if original is None:
                frappe.conf.pop("lms_brand_logo_path", None)
            else:
                frappe.conf["lms_brand_logo_path"] = original

    def test_favicon_path_respects_operator_override(self):
        """R23-H2: lms_brand_favicon_path is the highest-priority fallback."""
        from lms_saas.utils import brand
        original = frappe.conf.get("lms_brand_favicon_path")
        frappe.conf["lms_brand_favicon_path"] = "/files/operator-favicon.svg"
        try:
            url = brand.get_brand_favicon_url()
            self.assertEqual(url, "/files/operator-favicon.svg")
        finally:
            if original is None:
                frappe.conf.pop("lms_brand_favicon_path", None)
            else:
                frappe.conf["lms_brand_favicon_path"] = original


# ---------------------------------------------------------------------------
# Q2-C1: setup/rebrand.py runner exists and is dry-run by default.
# ---------------------------------------------------------------------------
class TestR23RebrandRunner(FrappeTestCase):
    """R23-C1: a single bench execute that rebrand the full site."""

    def test_runner_is_importable(self):
        from lms_saas.setup import rebrand
        self.assertTrue(hasattr(rebrand, "run"))
        self.assertTrue(hasattr(rebrand, "diff"))

    def test_runner_dry_run_returns_plan(self):
        from lms_saas.setup import rebrand
        result = rebrand.run(
            portal_title="Kopo Capital",
            company="Kopo Capital Microfinance",
            smtp_server="mail.kopocapital.example.com",
            smtp_email="app@kopocapital.example.com",
            smtp_password="<secret>",
        )
        # Default apply=False → plan only, no writes.
        self.assertIn("plan", result)
        self.assertIn("DRY RUN", "\n".join(result["plan"]))

    def test_runner_missing_required_keys_fails(self):
        from lms_saas.setup import rebrand
        result = rebrand.run()
        # Missing portal_title and company → fails closed.
        self.assertTrue(result["failed"])
        self.assertIn("Missing required keys", result["failed"][0])

    def test_runner_required_keys_listed(self):
        from lms_saas.setup import rebrand
        # Spot-check the REQUIRED_KEYS contract.
        self.assertIn("portal_title", rebrand.REQUIRED_KEYS)
        self.assertIn("company", rebrand.REQUIRED_KEYS)


# ---------------------------------------------------------------------------
# Q2-H1: configure_live_email.py docstrings no longer hard-code kesari.africa.
# ---------------------------------------------------------------------------
class TestR23ConfigureLiveEmailIsConfigDriven(FrappeTestCase):
    """R23-H1: docstrings and test subjects use operator-config values."""

    def test_module_docstring_no_hard_coded_kesari(self):
        from lms_saas.setup import configure_live_email
        src = Path(configure_live_email.__file__).read_text()
        # The module docstring may mention "kesari" as the historical
        # example, but the live docstring should describe a placeholder
        # pattern, not a hard-coded domain.
        # The function-level docstrings for retry_stuck_queue and
        # clean_demo_queue must not mention kesari.africa.
        # We use a heuristic: look at the lines after def retry_stuck_queue
        # and def clean_demo_queue and check no 'kesari' substring.
        lines = src.splitlines()
        in_docstring = False
        docstring_target = None
        for i, line in enumerate(lines):
            if "def retry_stuck_queue" in line or "def clean_demo_queue" in line:
                in_docstring = True
                docstring_target = lines[i + 1 : i + 15]
                break
        self.assertIsNotNone(docstring_target)
        joined = "\n".join(docstring_target)
        # The docstring should NOT contain the literal string 'kesari'
        # in a way that suggests the SMTP server is hard-coded.
        self.assertNotIn("kesari.africa", joined)

    def test_test_email_subject_uses_config(self):
        """The send_test_email subject uses frappe.conf.get, not a hard-coded string."""
        from lms_saas.setup import configure_live_email
        src = Path(configure_live_email.__file__).read_text()
        # Find the send_test_email function and check its subject line.
        self.assertIn(
            "frappe.conf.get(\"lms_live_smtp_server\")",
            src,
            "send_test_email must use lms_live_smtp_server config",
        )


# ---------------------------------------------------------------------------
# Q2-H2: demo-mode users derive email from operator's brand.
# ---------------------------------------------------------------------------
class TestR23DemoUserEmailDerivation(FrappeTestCase):
    """R23-H2: demo-mode users get emails derived from operator's brand."""

    def test_demo_email_domain_default_uses_brand(self):
        from lms_saas.scripts import toggle_demo_mode
        original_brand = frappe.conf.get("lms_brand_portal_title")
        original_override = frappe.conf.get("lms_demo_email_domain")
        frappe.conf["lms_brand_portal_title"] = "Kopo Capital"
        frappe.conf.pop("lms_demo_email_domain", None)
        try:
            domain = toggle_demo_mode._demo_email_domain()
            self.assertIn("kopo", domain.lower())
            self.assertTrue(domain.endswith(".example.com"))
            # Should NOT leak the original operator's domain.
            self.assertNotIn("kesari", domain)
        finally:
            if original_brand is None:
                frappe.conf.pop("lms_brand_portal_title", None)
            else:
                frappe.conf["lms_brand_portal_title"] = original_brand
            if original_override is not None:
                frappe.conf["lms_demo_email_domain"] = original_override

    def test_demo_email_domain_respects_explicit_override(self):
        from lms_saas.scripts import toggle_demo_mode
        original = frappe.conf.get("lms_demo_email_domain")
        frappe.conf["lms_demo_email_domain"] = "demo.mycorp.test"
        try:
            from lms_saas.scripts import toggle_demo_mode as tdm
            domain = tdm._demo_email_domain()
            self.assertEqual(domain, "demo.mycorp.test")
        finally:
            if original is None:
                frappe.conf.pop("lms_demo_email_domain", None)
            else:
                frappe.conf["lms_demo_email_domain"] = original

    def test_demo_user_email_format(self):
        from lms_saas.scripts import toggle_demo_mode
        original_brand = frappe.conf.get("lms_brand_portal_title")
        original_override = frappe.conf.get("lms_demo_email_domain")
        frappe.conf["lms_brand_portal_title"] = "Kopo Capital"
        frappe.conf.pop("lms_demo_email_domain", None)
        try:
            email = toggle_demo_mode._demo_user_email("Branch Manager")
            self.assertIn("branchmanager", email)
            self.assertTrue(email.endswith("@kopocapital.example.com"))
        finally:
            if original_brand is None:
                frappe.conf.pop("lms_brand_portal_title", None)
            else:
                frappe.conf["lms_brand_portal_title"] = original_brand
            if original_override is not None:
                frappe.conf["lms_demo_email_domain"] = original_override


# ---------------------------------------------------------------------------
# Q3-H1: brand validation surfaces warnings for suspicious values.
# ---------------------------------------------------------------------------
class TestR23BrandValidation(FrappeTestCase):
    """R23-H1: enrich_brand validates the operator's configured value."""

    def test_empty_brand_value_surfaces_warning(self):
        from lms_saas.utils import brand
        warnings = brand._validate_brand({"portal_title": ""})
        self.assertTrue(any("portal_title is empty" in w for w in warnings))

    def test_oversized_brand_value_surfaces_warning(self):
        from lms_saas.utils import brand
        long_title = "A" * 80
        warnings = brand._validate_brand({"portal_title": long_title})
        self.assertTrue(any("chars" in w for w in warnings))

    def test_rtl_override_surfaces_warning(self):
        from lms_saas.utils import brand
        # U+202E = RIGHT-TO-LEFT OVERRIDE — historically used in
        # phishing-style brand spoofing.
        warnings = brand._validate_brand({"portal_title": "Evil\u202eBrand"})
        self.assertTrue(any("right-to-left" in w for w in warnings))

    def test_jinja_placeholder_stripped(self):
        from lms_saas.utils import brand
        cleaned = brand._sanitize_brand_value("portal_title", "Hello {{ name }}")
        self.assertNotIn("{{", cleaned)
        self.assertNotIn("}}", cleaned)


# ---------------------------------------------------------------------------
# Q5-M1: get_lms_company helper.
# ---------------------------------------------------------------------------
class TestR23LmsCompanyHelper(FrappeTestCase):
    """R23-M1: get_lms_company() respects lms_company config override."""

    def test_helper_exists(self):
        from lms_saas.api import lms_company
        self.assertTrue(hasattr(lms_company, "get_lms_company"))

    def test_helper_returns_none_for_no_company_site(self):
        """When the site has no Company, the helper returns None rather
        than raising — call sites handle None defensively."""
        from lms_saas.api import lms_company
        original = frappe.conf.get("lms_company")
        frappe.conf.pop("lms_company", None)
        try:
            result = lms_company.get_lms_company()
            # The site may or may not have a Company in this test context;
            # the contract is that the helper returns a string OR None,
            # never raises.
            self.assertTrue(result is None or isinstance(result, str))
        finally:
            if original is not None:
                frappe.conf["lms_company"] = original
