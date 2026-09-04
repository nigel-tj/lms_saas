"""R59 — icon registry consistency guards.

The app has TWO icon registries that must never drift:

1. ``lms_icons._PATHS``      (public/js/lms_icons.js)  — JS-rendered surfaces
2. ``brand._LMS_ICON_PATHS`` (utils/brand.py)          — server-rendered sidebar

Both must resolve the same glyph for the same key, and every icon key
referenced by portal code (``titleIcon``/``icon``/``.icon()``/``.empty()``)
must exist — otherwise the silent fallback renders a misleading diamond
glyph in modal headers and empty states (R59 lesson).
"""

import os
import re
import unittest

APP_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
JS_DIR = os.path.join(APP_ROOT, "lms_saas", "public", "js")
BRAND_PY = os.path.join(APP_ROOT, "lms_saas", "utils", "brand.py")


def _js_registry_keys():
    src = open(os.path.join(JS_DIR, "lms_icons.js"), encoding="utf-8").read()
    match = re.search(r"_PATHS\s*=\s*\{(.*?)\n\};", src, re.S)
    if not match:
        return set()
    # Keys may be quoted ("bar-chart":) or bare (wallet:) — match both.
    return set(re.findall(r'"([^"]+)"\s*:', match.group(1))) | set(
        re.findall(r"(?:^|\n)\s*([a-z][a-z0-9\-]+)\s*:", match.group(1))
    )


def _python_registry_keys():
    src = open(BRAND_PY, encoding="utf-8").read()
    match = re.search(r"_LMS_ICON_PATHS\s*=\s*\{(.*?)\n\}", src, re.S)
    if not match:
        return set()
    return set(re.findall(r'"([^"]+)"\s*:', match.group(1))) | set(
        re.findall(r"(?:^|\n)\s*([a-z][a-z0-9\-]+)\s*:", match.group(1))
    )


def _portal_referenced_icon_keys():
    """Icon keys referenced by portal JS via the documented call shapes."""
    patterns = [
        re.compile(r'titleIcon:\s*"([^"]+)"'),
        re.compile(r"\bicon:\s*\"([a-z][a-z0-9\-]+)\""),
        re.compile(r'\.icon\("([^"]+)"'),
        re.compile(r'\.empty\("([^"]+)"'),
    ]
    keys = set()
    for fname in os.listdir(JS_DIR):
        if not fname.endswith(".js") or fname == "lms_icons.js":
            continue
        text = open(os.path.join(JS_DIR, fname), encoding="utf-8").read()
        for pattern in patterns:
            keys.update(pattern.findall(text))
    # Keep plausible icon keys only; the desk (lms_desk.js) uses Frappe's
    # separate `es-line-*` sprite system rendered via <use href>, which is
    # intentionally outside the LMS stroke registry.
    return {
        k
        for k in keys
        if re.match(r"^[a-z][a-z0-9\-]+$", k) and not k.startswith("es-line-")
    }


class TestR59IconRegistryConsistency(unittest.TestCase):
    """Pin the two icon registries + referenced keys together (R59)."""

    def test_js_registry_is_not_empty(self):
        keys = _js_registry_keys()
        self.assertGreater(len(keys), 40, "lms_icons._PATHS should hold a real registry")

    def test_python_mirror_keys_subset_of_js(self):
        """Server mirror must not contain keys the JS registry lacks (drift guard)."""
        js = _js_registry_keys()
        py = _python_registry_keys()
        self.assertEqual(
            py - js,
            set(),
            "brand._LMS_ICON_PATHS drifted from lms_icons._PATHS — sync them",
        )

    def test_referenced_icon_keys_exist_in_js_registry(self):
        """Every titleIcon/icon key used by portal code must resolve —
        unknown names silently render the diamond fallback."""
        missing = _portal_referenced_icon_keys() - _js_registry_keys()
        self.assertEqual(
            missing,
            set(),
            "Portal code references icon keys missing from lms_icons._PATHS "
            "(they render as diamond): " + ", ".join(sorted(missing)),
        )


if __name__ == "__main__":
    unittest.main()