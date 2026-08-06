"""R43 brand CSS regression tests.

Three regressions were filed 2026-08-06:

- **R43-C1**: ``lms_themes/default.css`` was missing `--theme-primary`
  (and `--theme-primary-light` was defined but never aliased to the
  primary surface). Every ``var(--lms-primary)`` consumer in
  ``lms_components.css`` and ``lms_portal.css`` silently resolved to
  ``rgba(0, 0, 0, 0)`` because ``--theme-primary`` was undefined. The
  visible symptom: the user-menu avatar circle rendered as a plain
  text "B" (no green pill), the "New Application" primary button had
  no visible background until hover, and 85 other primary-coloured
  consumers were broken. The lesson: a theme file with some brand
  variables but no ``--theme-primary`` is the worst possible failure
  mode — silent.

- **R43-C2**: the bell badge (``lms-topbar__badge``) used
  ``var(--lms-danger)`` which is red. A red badge signals "error" /
  "failure". The bell counts unread notifications — informational.
  Brand green is the correct semantic.

- **R43-C3**: the bell badge count sat at an offset that read as
  off-centre when the count was a single digit. Padding/line-height
  tuned so the number is centred on the badge.

These tests are JS-source + CSS-source assertions. The point is to
lock the fixes in place so a future refactor can't regress the
brand surface without test failure.
"""

import os
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
APP_ROOT = REPO_ROOT / "apps" / "lms_saas" / "lms_saas"


def _read(rel_path):
    return (APP_ROOT / rel_path).read_text()


class TestR43BrandCss(unittest.TestCase):
    """R43 brand CSS source-level regression coverage."""

    # --------------------------------------------------------------
    # R43-C1: every theme file MUST define --theme-primary. A missing
    # primary silently breaks 85 consumers across the portal.
    # --------------------------------------------------------------
    def test_every_theme_file_defines_theme_primary(self):
        """`--theme-primary` is the single most-referenced theme token
        (85 consumers). If a theme file omits it, every consumer
        resolves to rgba(0, 0, 0, 0) — invisible. Pin the rule so a
        future theme addition cannot silently break the portal.

        Note: ``high-contrast.css`` is an `@media` accessibility
        override file (triggered by ``prefers-contrast: more``), not
        a theme. It deliberately does NOT redefine theme tokens —
        accessibility overrides modify borders / focus rings, not
        brand colour. We skip it here.
        """
        theme_dir = APP_ROOT / "public" / "css" / "lms_themes"
        self.assertTrue(theme_dir.is_dir(), "lms_themes directory missing")
        for css_file in sorted(theme_dir.glob("*.css")):
            if css_file.name == "high-contrast.css":
                # Accessibility override file; not a theme.
                continue
            text = css_file.read_text()
            self.assertRegex(
                text,
                r"--theme-primary\s*:",
                f"{css_file.name} is missing --theme-primary. Every "
                "lms_themes/*.css file must define --theme-primary or "
                "var(--lms-primary) consumers render as transparent.",
            )

    def test_default_theme_primary_matches_brand_green(self):
        """The default theme's --theme-primary must be the forest green
        brand value (hex #2f4f46, oklch 0.353 0.038 175). The other
        themes pair their unique colours with a consistent semantic
        ramp; the default theme is the operator-facing brand."""
        text = _read("public/css/lms_themes/default.css")
        m = re.search(
            r"--theme-primary\s*:\s*([^;]+);",
            text,
        )
        self.assertIsNotNone(m, "default.css must define --theme-primary")
        value = m.group(1).strip()
        # Accept either the explicit oklch value or a hex. The hex
        # string "#2f4f46" is the legacy/canonical brand value.
        oklch_ok = "0.353" in value and "0.038" in value and "175" in value
        hex_ok = "2f4f46" in value.lower()
        self.assertTrue(
            oklch_ok or hex_ok,
            f"default.css --theme-primary ({value!r}) must be the brand "
            "forest green (#2f4f46 / oklch(0.353 0.038 175)).",
        )

    # --------------------------------------------------------------
    # R43-C2: bell badge uses brand green, not danger red.
    # --------------------------------------------------------------
    def test_topbar_badge_uses_brand_primary_not_danger(self):
        """The bell badge (``lms-topbar__badge``) shows the unread
        notification count. Red is reserved for errors/danger; the
        count is informational. The badge must use
        ``var(--lms-primary)`` (brand green), not ``var(--lms-danger)``.
        """
        css = _read("public/css/lms_portal.css")
        m = re.search(
            r"\.lms-topbar__badge\s*\{([^}]*)\}",
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(m, ".lms-topbar__badge rule must exist")
        body = m.group(1)
        self.assertIn(
            "var(--lms-primary)",
            body,
            ".lms-topbar__badge must use var(--lms-primary) (brand "
            "green) — red signals an error, not a notification count.",
        )
        self.assertNotIn(
            "var(--lms-danger)",
            body,
            ".lms-topbar__badge must NOT use var(--lms-danger) — red "
            "is reserved for failures and shapes the user toward "
            "panic-reading the badge.",
        )

    # --------------------------------------------------------------
    # R43-C3: bell badge number is centred.
    # --------------------------------------------------------------
    def test_topbar_badge_centres_its_count(self):
        """The badge contents must be vertically + horizontally
        centred. The previous declaration had align-items + justify
        but was missing ``line-height: 1`` so a single-digit count
        sat at the top of the pill."""
        css = _read("public/css/lms_portal.css")
        m = re.search(
            r"\.lms-topbar__badge\s*\{([^}]*)\}",
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("display: inline-flex", body)
        self.assertIn("align-items: center", body)
        self.assertIn("justify-content: center", body)
        self.assertIn(
            "line-height: 1",
            body,
            ".lms-topbar__badge must declare line-height: 1 so a "
            "single digit count sits vertically centred inside the pill.",
        )

    # --------------------------------------------------------------
    # R43-C4: bell badge count is vertically + horizontally centred.
    # --------------------------------------------------------------
    def test_topbar_badge_is_horizontally_and_vertically_centred(self):
        """The bell badge count must be centered on both axes. The
        bug was two competing rules — `.lms-topbar__badge` declared
        `display: inline-flex` + `align-items: center` +
        `justify-content: center`, but `.lms-notification-badge` had
        no `display` so the base `<span>` defaulted to `display: block`,
        and the JS then set `style.display = "inline-block"` which
        silently overrode the flex centering. Pin both the CSS rule
        and the JS so the centring cannot regress.
        """
        css = _read("public/css/lms_portal.css")
        m = re.search(
            r"\.lms-notification-badge\s*\{([^}]*)\}",
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(m, ".lms-notification-badge rule must exist")
        body = m.group(1)
        # The CSS rule must explicitly use the flex centring triple.
        self.assertIn(
            "display: inline-flex",
            body,
            ".lms-notification-badge must use display: inline-flex so "
            "align-items: center + justify-content: center actually "
            "centre the digit on both axes.",
        )
        self.assertIn("align-items: center", body)
        self.assertIn("justify-content: center", body)
        # Bell badge background must be brand green, not danger red.
        self.assertIn("var(--lms-primary)", body)
        self.assertNotIn(
            "var(--lms-danger)",
            body,
            ".lms-notification-badge must NOT use var(--lms-danger) "
            "(red is reserved for failures).",
        )

    def test_bell_badge_js_does_not_force_inline_block(self):
        """The JS that polls the unread count must not set
        ``badge.style.display = \"inline-block\"`` — that style
        silently overrides the CSS ``display: inline-flex`` and the
        number floats to the top-left of the pill. The JS should
        clear the inline `display` (or set ``inline-flex``) so the
        CSS rule applies.
        """
        js = _read("public/js/lms_portal.js")
        self.assertNotRegex(
            js,
            r"badge\.style\.display\s*=\s*[\"']inline-block[\"']",
            "lms_portal.js must NOT set badge.style.display = "
            "'inline-block' — it clobbers the CSS flex centring and "
            "leaves the badge count uncentred.",
        )

    # --------------------------------------------------------------
    # CSS brace sanity: every theme file must be a single balanced
    # block (no unclosed braces that would silently break the whole
    # file).
    # --------------------------------------------------------------
    def test_theme_css_brace_balance(self):
        theme_dir = APP_ROOT / "public" / "css" / "lms_themes"
        for css_file in sorted(theme_dir.glob("*.css")):
            text = css_file.read_text()
            depth = 0
            i = 0
            n = len(text)
            unbalanced = None
            while i < n:
                ch = text[i]
                if ch == "/" and i + 1 < n and text[i + 1] == "*":
                    close = text.find("*/", i + 2)
                    if close == -1:
                        break
                    i = close + 2
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth < 0:
                        unbalanced = i
                        break
                i += 1
            self.assertIsNone(
                unbalanced,
                f"{css_file.name}: stray closing brace at offset {unbalanced}",
            )
            self.assertEqual(
                depth,
                0,
                f"{css_file.name}: unbalanced braces (depth={depth}) — "
                "a previous edit left an unclosed :root block that "
                "broke the whole theme file.",
            )


if __name__ == "__main__":
    unittest.main()
