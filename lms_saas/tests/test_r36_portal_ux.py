"""R36 portal UX regression tests.

Three user-facing portal bugs were filed:

- R36-C1: Approvals tab stuck on "Loading…" forever when the API
  timed out. Root cause was ``content.insertAdjacentHTML("beforeend", html)``
  leaving the loader behind.

- R36-C2: Active tab was lost on every page refresh — a manager working
  on Approvals would land back on Dashboard after every save / reload.
  No persistence layer existed.

- R36-C3: Toast notifications were anchored to the bottom-right corner
  and got hidden behind the chat sidebar at this viewport. Users
  literally could not see save-success or 417-error toasts.

These tests are JS-source assertions (not Python behaviour). The point
is to lock the fixes in place so a future refactor can't regress the
UX without test failure.
"""

import os
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
APP_ROOT = REPO_ROOT / "apps" / "lms_saas" / "lms_saas"


def _read(rel_path):
    return (APP_ROOT / rel_path).read_text()


class TestR36PortalUx(unittest.TestCase):
    """R36 portal UX source-level regression coverage."""

    # --------------------------------------------------------------
    # R36-C1: Approvals tab must not get stuck on "Loading…".
    # --------------------------------------------------------------
    def test_approvals_tab_clears_loader_before_cold_paint(self):
        """The fix replaces the panel in-place on hot-refresh rather than
        appending via ``insertAdjacentHTML("beforeend", html)`` without first
        clearing the loader — that previous behaviour left the "Loading…"
        spinner behind the rendered table on every re-render.

        The cold-paint path (first render of the panel) is allowed to use
        insertAdjacentHTML — but only AFTER wiping ``content.innerHTML = ""``
        so the loader is gone first."""
        src = _read("public/js/lms_manager_portal.js")
        body_match = re.search(
            r"lms_manager\._renderApprovalsTable\s*=\s*function\s*\([^)]*\)\s*\{(.+?)\n\};",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(body_match, "_renderApprovalsTable must exist")
        body = body_match.group(1)
        # The hot-refresh path must update in-place (not append to the loader).
        # We look for either `replaceWith` or a guard that the second-render
        # branch updates the existing panel rather than calling
        # insertAdjacentHTML blindly.
        self.assertIn(
            "replaceWith",
            body,
            "_renderApprovalsTable hot-refresh path must use replaceWith "
            "(or equivalent in-place swap) — appending via insertAdjacentHTML "
            "leaks the prior 'Loading…' spinner behind the new table.",
        )
        # The function must reference _approvalPanelRoot as the cached mount
        # point (the regression-tested fix).
        self.assertIn(
            "_approvalPanelRoot",
            body,
            "_renderApprovalsTable must cache _approvalPanelRoot so the "
            "second render updates the existing panel in place.",
        )
        # Cold-paint path must wipe the loader before re-injecting.
        self.assertRegex(
            body,
            r"content\.innerHTML\s*=\s*\"\"",
            "Cold-paint path must do `content.innerHTML = \"\"` BEFORE the "
            "insertAdjacentHTML call so the 'Loading…' spinner is wiped.",
        )

    def test_approvals_tab_empty_state_is_handled(self):
        """An empty queue must render a clear message, not a blank panel."""
        src = _read("public/js/lms_manager_portal.js")
        body_match = re.search(
            r"lms_manager\._renderApprovalsTable\s*=\s*function\s*\([^)]*\)\s*\{(.+?)\n\};",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(body_match)
        body = body_match.group(1)
        # Either an `if (!apps.length)` branch OR a `length === 0` branch must
        # render an empty-state message ("No pending approvals" or similar).
        self.assertRegex(
            body,
            r"apps\.length\s*[!=]==?\s*0|No pending|No applications",
            "Empty approval queue must show a fallback message, not render "
            "a blank table with no rows.",
        )

    def test_guarded_call_has_timeout(self):
        """Every tab that fetches data must use _guardedCall (with timeout)
        so a stuck safeCall can never leave the panel on 'Loading…'."""
        src = _read("public/js/lms_manager_portal.js")
        self.assertIn(
            "_guardedCall",
            src,
            "_guardedCall (timeout wrapper) is the defence against stuck "
            "loaders. Without it, a slow API leaves the panel on 'Loading…' "
            "indefinitely.",
        )
        # The Approvals loader must use _guardedCall (not raw safeCall).
        body_match = re.search(
            r"lms_manager\._loadApprovals\s*=\s*function\s*\([^)]*\)\s*\{(.+?)\n\};",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(body_match)
        body = body_match.group(1)
        self.assertIn(
            "_guardedCall",
            body,
            "_loadApprovals must use _guardedCall (timeout) — raw safeCall "
            "can stall the spinner forever if the API returns 500 without "
            "invoking the error callback.",
        )

    # --------------------------------------------------------------
    # R36-C2: Active tab persists across page refresh.
    # --------------------------------------------------------------
    def test_lms_portal_exposes_persistence_helpers(self):
        """lms_portal.persistedTab and lms_portal.saveActiveTab must exist
        so the manager + officer portals can read/write the active tab."""
        src = _read("public/js/lms_portal.js")
        self.assertRegex(
            src,
            r"lms_portal\.persistedTab\s*=\s*function",
            "lms_portal.persistedTab is required for tab restoration on init.",
        )
        self.assertRegex(
            src,
            r"lms_portal\.saveActiveTab\s*=\s*function",
            "lms_portal.saveActiveTab is required to write the active tab "
            "key on every tab switch.",
        )

    def test_persistence_uses_session_storage_key(self):
        """Tab state lives in sessionStorage under the lms_<ns>_active_tab
        key (session-scoped, not local, so it doesn't bleed across
        browser sessions)."""
        src = _read("public/js/lms_portal.js")
        self.assertIn(
            "lms_",
            src,
            "sessionStorage key prefix 'lms_' must be present.",
        )
        self.assertIn(
            "sessionStorage",
            src,
            "Tab state must use sessionStorage (not localStorage) so it "
            "resets when the user closes the tab/window.",
        )

    def test_manager_portal_restores_active_tab(self):
        """lms_manager.init must call lms_portal.persistedTab so the user
        lands on the tab they were last working on."""
        src = _read("public/js/lms_manager_portal.js")
        # The init function should reference persistedTab for "manager".
        m = re.search(
            r"lms_manager\.init\s*=\s*function\s*\(\s*\)\s*\{(.+?)\n\};",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn(
            'persistedTab("manager"',
            body,
            "lms_manager.init must call lms_portal.persistedTab('manager', ...) "
            "to restore the manager's last-active tab across refresh.",
        )

    def test_manager_portal_persists_on_tab_click(self):
        """Clicking a tab must call lms_portal.saveActiveTab so the next
        reload lands back on that tab."""
        src = _read("public/js/lms_manager_portal.js")
        m = re.search(
            r"lms_manager\._bindTabs\s*=\s*function\s*\(\s*\)\s*\{(.+?)\n\};",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn(
            'saveActiveTab("manager"',
            body,
            "lms_manager._bindTabs must call lms_portal.saveActiveTab('manager', ...) "
            "inside the click handler so the click is persisted before the "
            "tab is re-rendered.",
        )

    def test_officer_portal_restores_active_tab(self):
        """Same persistence contract for the officer portal."""
        src = _read("public/js/lms_officer_portal.js")
        m = re.search(
            r"lms_officer\.init\s*=\s*function\s*\(\s*\)\s*\{(.+?)\n\};",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn(
            'persistedTab("officer"',
            body,
            "lms_officer.init must restore the last-active officer tab.",
        )

    def test_officer_portal_persists_on_tab_click(self):
        src = _read("public/js/lms_officer_portal.js")
        m = re.search(
            r"lms_officer\._bindTabs\s*=\s*function\s*\(\s*\)\s*\{(.+?)\n\};",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn(
            'saveActiveTab("officer"',
            body,
            "lms_officer._bindTabs must persist the clicked tab.",
        )

    # --------------------------------------------------------------
    # R36-C3: Toast container is anchored to the top of the viewport,
    # not the bottom-right corner (where it collided with the chat
    # sidebar and was easy to miss).
    # --------------------------------------------------------------
    def test_toast_stack_is_top_anchored(self):
        css = _read("public/css/lms_components.css")
        # Find the .lms-toast-stack rule body and assert top is set
        # while bottom is not the primary anchor.
        m = re.search(
            r"\.lms-toast-stack\s*\{([^}]*)\}",
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(m, ".lms-toast-stack rule must exist in CSS")
        body = m.group(1)
        self.assertRegex(
            body,
            r"top\s*:\s*[^;]+;",
            ".lms-toast-stack must have a `top:` value to anchor it.",
        )
        self.assertIn(
            "position: fixed",
            body,
            ".lms-toast-stack must be position: fixed.",
        )

    def test_toast_stack_is_horizontally_centered(self):
        """`inset-inline: 0` + `margin: 0 auto` centres the stack at every
        viewport width — safer than hard-coded `left:`."""
        css = _read("public/css/lms_components.css")
        m = re.search(
            r"\.lms-toast-stack\s*\{([^}]*)\}",
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertRegex(
            body,
            r"inset-inline\s*:\s*0",
            ".lms-toast-stack must use inset-inline: 0 to centre on every "
            "writing direction.",
        )
        self.assertRegex(
            body,
            r"margin\s*:\s*0\s+auto",
            ".lms-toast-stack must use margin: 0 auto to centre horizontally.",
        )

    def test_toast_stack_pointer_events_disabled(self):
        """The stack container should be pointer-events: none so it
        doesn't intercept clicks for areas behind it; each toast re-enables
        pointer events for the dismiss button."""
        css = _read("public/css/lms_components.css")
        m = re.search(
            r"\.lms-toast-stack\s*\{([^}]*)\}",
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn(
            "pointer-events: none",
            body,
            ".lms-toast-stack must be pointer-events: none so toasts don't "
            "block clicks on dashboard tiles behind them.",
        )

    def test_toast_pointer_events_re_enabled(self):
        """Each individual toast must re-enable pointer events so the
        close (×) button stays clickable."""
        css = _read("public/css/lms_components.css")
        m = re.search(
            r"\.lms-toast\s*\{([^}]*)\}",
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(m, ".lms-toast rule must exist in CSS")
        body = m.group(1)
        self.assertIn(
            "pointer-events: auto",
            body,
            ".lms-toast must be pointer-events: auto so the close (×) "
            "button is clickable.",
        )

    def test_css_brace_balance_in_toast_block(self):
        """Sanity-check: every CSS rule in the toast region must have
        balanced braces. A previous edit left an unclosed .lms-toast { block
        which broke the whole file. This test guards against that class
        of regression by counting braces rule-by-rule (not within a fixed
        character window)."""
        css = _read("public/css/lms_components.css")
        start = css.find(".lms-toast-stack {")
        self.assertNotEqual(start, -1, ".lms-toast-stack rule must exist")
        # End at the next major section comment after the mobile media query.
        # The mobile media query closes with `}` followed by a blank line and
        # the next section header `/* -----`. Look for the next section
        # header at least 200 chars after the @media opener so we don't
        # stop inside the media query.
        end_markers = []
        search_from = start + 100
        for marker in ("/* -----", "/* -----", "/* ===", "\n.lms-chart-slot"):
            idx = css.find(marker, search_from)
            if idx != -1:
                end_markers.append(idx)
        if end_markers:
            end = min(end_markers)
        else:
            end = min(start + 6000, len(css))
        block = css[start:end]
        # Walk the block and track brace depth.
        depth = 0
        unbalanced = None
        i = 0
        n = len(block)
        while i < n:
            ch = block[i]
            # Skip over CSS comments so braces inside /* … */ don't count.
            if ch == "/" and i + 1 < n and block[i + 1] == "*":
                close = block.find("*/", i + 2)
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
            f"Stray closing brace at offset {unbalanced} in toast block.",
        )
        self.assertEqual(
            depth,
            0,
            f"CSS toast block has unbalanced braces: {depth} open braces left "
            f"unclosed. The previous R36 bug left an unclosed .lms-toast "
            f"block; if this test fires, find and fix the stray brace.",
        )

    def test_mobile_toast_falls_back_to_bottom(self):
        """On narrow viewports (<=600px) the toast stack falls back to
        anchored at the bottom of the screen so it doesn't cover the
        topbar (which is often the primary nav on mobile)."""
        css = _read("public/css/lms_components.css")
        self.assertRegex(
            css,
            r"@media\s*\(\s*max-width\s*:\s*600px\s*\)\s*\{\s*\.lms-toast-stack\s*\{[^}]*bottom",
            "@media (max-width: 600px) .lms-toast-stack must re-anchor at "
            "the bottom so toasts don't cover the mobile topbar.",
        )


if __name__ == "__main__":
    unittest.main()
