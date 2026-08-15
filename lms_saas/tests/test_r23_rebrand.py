"""R23 regression tests — rebrand readiness.

The R23 board review surfaced 12 findings across 5 personas (Q1 SaaS
Architect, Q2 White-Label Operator, Q3 Independent Lender, Q4 Pen-Tester,
Q5 Frappe Engineer). This test file pins the fixes so a future engineer
who changes any of the touched modules will catch the regression in CI.

R23 fix list (post-review rebrand strategy):
- Q1-C1: hard-coded "Kesari" fallbacks removed from user-facing strings.
  Brand fallbacks are now vendor-neutral ("LMS") so a fresh install never
  leaks a competitor's brand.
- Q1-H1: app_title strategy was originally "LMS" (vendor-neutral product
  family name) in hooks.py. The R30 board re-reviewed this and decided to
  KEEP the operator's brand ("Kesari") in hooks.app_title so a fresh
  install shows the brand accurately without any site_config editing.
  The runtime override (R32) reaches the desk chrome via a per-request
  boot hook so the operator can rebrand without a code change.
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

R32 fix list (operator app_name reflects in desk chrome):
- R32-1: hooks.app_title is the operator's brand (R30 decision).
- R32-2: lms_app_title / lms_brand_portal_title resolve to a per-request
  override that boot._apply_operator_app_name stamps onto bootinfo +
  frappe.conf + frappe.local so the desk navbar / login page show the
  right wordmark even if Website Settings / System Settings are stale.
- R32-3: frappe-cloud-update.sh re-applies _setup_navbar_branding on
  every deploy so the DB app_name fields stay in sync with site_config.

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
        """lms_user_setup.py uses the centralised brand chain (utils.brand.
        _brand_alias) — the original operator's literal name ("Kesari")
        must not appear anywhere in the file."""
        path = (
            Path(APP_ROOT)
            / "lms_saas"
            / "doctype"
            / "lms_user_setup"
            / "lms_user_setup.py"
        )
        src = path.read_text()
        # The welcome email subject now uses the brand chain helper.
        self.assertIn("_brand_alias", src)
        # And it must NOT have a hard-coded "Kesari" literal anywhere.
        self.assertNotIn('"Kesari"', src)
        self.assertNotIn("'Kesari'", src)


# ---------------------------------------------------------------------------
# Q1-H1: app_title is the operator's brand (R30 board decision).
# ---------------------------------------------------------------------------
class TestR23AppTitleIsVendorNeutral(FrappeTestCase):
    """R23-H1 / R30 decision: app_title is the operator's brand.

	The R23 board originally proposed making ``hooks.app_title = "LMS"``
	(vendor-neutral product family name) and overriding the desk chrome
	via a runtime ``lms_app_title`` config. The R30 board re-reviewed the
	proposal and decided to keep the operator's brand baked into
	``hooks.app_title`` so a fresh install shows the brand accurately
	without any site_config editing. The vendor-neutral rename is
	tracked as a separate task.

	The runtime override chain is still required so a rebrand (operator
	changes ``lms_brand_portal_title`` in site_config) reaches the desk
	navbar / login page without a code change. See ``TestR32AppNameOverride``
	for the runtime-side checks.
	"""

    def test_app_title_is_kesari_per_r30_decision(self):
        from lms_saas import hooks
        # R30 board kept the operator's brand in hooks.app_title. Pin that
        # here so a future engineer who flips it to "LMS" without running
        # the migration through the board process gets a clear test failure.
        self.assertEqual(hooks.app_title, "Kesari")

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


# ---------------------------------------------------------------------------
# R32: runtime app_name override (lms_app_title / lms_brand_portal_title).
# ---------------------------------------------------------------------------
class TestR32AppNameOverride(FrappeTestCase):
    """R32: the desk navbar login wordmark must reflect the operator's brand
    even when ``hooks.app_title`` is a different literal.

    History: the live site was running with ``lms_brand_portal_title=Kesari``
    in site_config but ``Website Settings.app_name=LMS`` in the DB (the
    after_install hook either never ran or its writes were rolled back).
    The desk navbar reads ``bootinfo.app_name`` (mirrored from
    ``frappe.conf["app_name"]`` / ``hooks.app_title``), so the operator
    was seeing "LMS" in the navbar instead of "Kesari". The
    ``resolve_operator_app_name`` helper + ``boot._apply_operator_app_name``
    hook fix this by re-stamping the operator's brand onto the boot
    payload on every request, so the desk chrome matches the portal
    without a code change.
    """

    def test_resolve_returns_lms_app_title_override(self):
        """R32-1: lms_app_title wins over lms_brand_portal_title."""
        from lms_saas.utils.brand import resolve_operator_app_name
        with mock.patch.dict(
            frappe.conf,
            {
                "lms_app_title": "Kopo Capital",
                "lms_brand_portal_title": "Kesari",
            },
        ):
            self.assertEqual(resolve_operator_app_name(), "Kopo Capital")

    def test_resolve_falls_back_to_brand_portal_title(self):
        """R32-2: lms_brand_portal_title is used when lms_app_title is unset."""
        from lms_saas.utils.brand import resolve_operator_app_name
        with mock.patch.dict(
            frappe.conf,
            {"lms_brand_portal_title": "Kesari"},
            clear=False,
        ):
            frappe.conf.pop("lms_app_title", None)
            self.assertEqual(resolve_operator_app_name(), "Kesari")

    def test_resolve_returns_none_when_neither_set(self):
        """R32-3: no override → None so the build-time value stays put."""
        from lms_saas.utils.brand import resolve_operator_app_name
        with mock.patch.dict(frappe.conf, {}, clear=False):
            frappe.conf.pop("lms_app_title", None)
            frappe.conf.pop("lms_brand_portal_title", None)
            self.assertIsNone(resolve_operator_app_name())

    def test_resolve_strips_whitespace(self):
        """R32-4: a misconfigured value with stray whitespace is treated as empty."""
        from lms_saas.utils.brand import resolve_operator_app_name
        with mock.patch.dict(
            frappe.conf,
            {"lms_app_title": "   ", "lms_brand_portal_title": "Kesari"},
            clear=False,
        ):
            # Pure whitespace is treated as empty so the brand chain
            # falls through to the next valid entry.
            self.assertEqual(resolve_operator_app_name(), "Kesari")

    def test_boot_apply_stamps_app_name_on_bootinfo(self):
        """R32-5: boot._apply_operator_app_name sets bootinfo.app_name
        from the operator's brand (so the desk navbar reads the right
        wordmark without a code change).
        """
        from lms_saas import boot as boot_mod
        from types import SimpleNamespace

        fake_bootinfo = SimpleNamespace()
        original_conf = frappe.conf.get("lms_app_title")
        original_brand = frappe.conf.get("lms_brand_portal_title")
        original_app = frappe.conf.get("app_name")
        original_local_app = getattr(frappe.local, "app_name", None)
        try:
            frappe.conf["lms_app_title"] = "Kesari"
            boot_mod._apply_operator_app_name(fake_bootinfo)
            self.assertEqual(fake_bootinfo.app_name, "Kesari")
            self.assertEqual(frappe.conf["app_name"], "Kesari")
            # frappe.local.app_name was set on the request-local scope.
            self.assertEqual(getattr(frappe.local, "app_name", None), "Kesari")
        finally:
            # Restore to avoid leaking the override into later tests.
            if original_conf is None:
                frappe.conf.pop("lms_app_title", None)
            else:
                frappe.conf["lms_app_title"] = original_conf
            if original_brand is None:
                frappe.conf.pop("lms_brand_portal_title", None)
            else:
                frappe.conf["lms_brand_portal_title"] = original_brand
            if original_app is None:
                frappe.conf.pop("app_name", None)
            else:
                frappe.conf["app_name"] = original_app
            if original_local_app is None:
                if hasattr(frappe.local, "app_name"):
                    delattr(frappe.local, "app_name")
            else:
                frappe.local.app_name = original_local_app

    def test_boot_apply_is_noop_when_no_override(self):
        """R32-6: with no override, the build-time app_name is preserved."""
        from lms_saas import boot as boot_mod
        from types import SimpleNamespace

        fake_bootinfo = SimpleNamespace(app_name="Kesari")
        with mock.patch.dict(frappe.conf, {}, clear=False):
            frappe.conf.pop("lms_app_title", None)
            frappe.conf.pop("lms_brand_portal_title", None)
            boot_mod._apply_operator_app_name(fake_bootinfo)
            # The build-time value is unchanged.
            self.assertEqual(fake_bootinfo.app_name, "Kesari")


# ---------------------------------------------------------------------------
# R23 follow-on: login page watermark pattern. Pins the diagonal
# monogram background on the form panel so a future refactor can't
# silently drop it (or accidentally hardcode a brand hex).
# ---------------------------------------------------------------------------
class TestLoginPageWatermark(FrappeTestCase):
    """Login form panel has a subtle diagonal monogram watermark
    (R23 follow-on). The pattern must be:

      1. Defined on .lms-login-panel (the right form panel only — the
         brand panel stays clean so the wordmark stays the anchor).
      2. Rotated (the pattern must read as a flow, not a grid).
      3. Tiled (background-repeat set so the pattern extends past
         viewport edges).
      4. Opacity < 0.20 (visible but never competes with the form).
      5. NOT using a hardcoded hex brand color — the R23 brand chain
         fix would silently regress if a hex were hardcoded here.
    """

    CSS_FILE = (
        Path(__file__).resolve().parent.parent.parent
        / "lms_saas" / "public" / "css" / "lms_login.css"
    )
    SVG_FILE = (
        Path(__file__).resolve().parent.parent.parent
        / "lms_saas" / "public" / "images" / "lms-monogram.svg"
    )

    def _css(self) -> str:
        return self.CSS_FILE.read_text()

    def test_panel_has_watermark_pseudo(self):
        """The .lms-login-panel must carry the ::before watermark rule."""
        css = self._css()
        self.assertIn(".lms-login-panel::before", css)
        # Must point at the monogram asset.
        self.assertIn("lms-monogram.svg", css)

    def test_watermark_is_rotated_and_tiled(self):
        """Rotation + background-repeat keeps the pattern reading
        as a watermark rather than a centered stamp."""
        css = self._css()
        # Find the ::before block.
        start = css.find(".lms-login-panel::before")
        self.assertNotEqual(start, -1, "::before block missing")
        block = css[start:start + 600]
        self.assertIn("repeat", block, "background-repeat must be set")
        self.assertIn("rotate", block, "transform: rotate(...) must be set")

    def test_watermark_opacity_is_quiet(self):
        """Opacity must be < 0.20 so the pattern never competes with
        the white form card."""
        import re
        css = self._css()
        start = css.find(".lms-login-panel::before")
        block = css[start:start + 600]
        m = re.search(r"opacity:\s*([0-9.]+)", block)
        self.assertIsNotNone(m, "opacity declaration missing on ::before")
        opacity = float(m.group(1))
        self.assertGreaterEqual(opacity, 0.05)
        self.assertLess(opacity, 0.20)

    def test_watermark_uses_css_token_no_hardcoded_brand_hex(self):
        """R23 regression guard: the watermark color MUST be driven by
        a CSS token (var(--lms-accent)), never a hardcoded hex. A
        hardcoded hex here would re-leak an operator brand color onto
        a fresh install."""
        import re
        css = self._css()
        start = css.find(".lms-login-panel::before")
        block = css[start:start + 600]
        # Allow the token (currentColor path or explicit var(--lms-accent)).
        uses_token = (
            "currentColor" in block
            or "var(--lms-accent)" in block
            or "color-mix" in block
        )
        self.assertTrue(
            uses_token,
            "watermark color must be theme-driven (currentColor / "
            "var(--lms-accent) / color-mix), not a hardcoded hex",
        )
        # Disallow any #xxxxxx literal inside the ::before block.
        hex_matches = re.findall(r"#[0-9a-fA-F]{6}\b", block)
        self.assertEqual(
            hex_matches,
            [],
            f"hardcoded brand hex in watermark block: {hex_matches}",
        )

    def test_watermark_does_not_bleed_through_form_card(self):
        """The .lms-login-forms wrapper must sit ABOVE the ::before
        watermark via z-index, so the white card has a clean surface."""
        css = self._css()
        # Look for the forms rule after the ::before block.
        idx_forms = css.find(".lms-login-forms")
        self.assertNotEqual(idx_forms, -1, ".lms-login-forms rule missing")
        block = css[idx_forms:idx_forms + 200]
        self.assertIn("z-index", block)
        # Must be relative so z-index takes effect.
        self.assertIn("position: relative", block)

    def test_monogram_svg_uses_currentColor(self):
        """The monogram SVG must use currentColor so the CSS can drive
        the fill. A hardcoded fill="#xxxxxx" here would defeat the
        rebrand-safety contract."""
        svg = self.SVG_FILE.read_text()
        self.assertIn("currentColor", svg)
        # Disallow any hardcoded fill attribute (other than currentColor).
        import re
        bad_fills = re.findall(
            r'fill\s*=\s*"(#[0-9a-fA-F]{6})"', svg
        )
        self.assertEqual(
            bad_fills,
            [],
            f"monogram SVG has hardcoded fill hex: {bad_fills}",
        )
