"""Release-gate install readiness (R11) — gate row 6.1.

Non-destructive check that the app would install cleanly on a fresh
site. Verifies required_apps, fixtures, patches, and a smoke import.
"""

from __future__ import annotations

import json

import frappe


def run() -> dict:
    """Check install readiness. Non-destructive — writes nothing."""
    result = {"ok": True, "checks": []}

    # 1. Required apps installed
    from lms_saas.hooks import required_apps
    for app in required_apps:
        installed = frappe.db.exists("Installed Application", {"app_name": app})
        result["checks"].append({
            "check": f"required_app:{app}",
            "ok": bool(installed),
        })
        if not installed:
            result["ok"] = False

    # 2. Fixtures resolve
    from lms_saas.hooks import fixtures
    for f in fixtures:
        dt = f.get("dt")
        exists = frappe.db.exists("DocType", dt)
        result["checks"].append({
            "check": f"fixture:{dt}",
            "ok": bool(exists),
        })
        if not exists:
            result["ok"] = False

    # 3. Patches importable
    from pathlib import Path
    patches_file = Path(frappe.get_app_path("lms_saas")) / "patches.txt"
    if patches_file.exists():
        for line in patches_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("["):
                continue
            try:
                __import__(line)
                result["checks"].append({"check": f"patch:{line}", "ok": True})
            except Exception as e:
                result["checks"].append({"check": f"patch:{line}", "ok": False, "error": str(e)})
                result["ok"] = False

    # 4. Smoke import key modules
    for mod in ("lms_saas.api.manager", "lms_saas.api.portal", "lms_saas.utils.calculations"):
        try:
            __import__(mod)
            result["checks"].append({"check": f"import:{mod}", "ok": True})
        except Exception as e:
            result["checks"].append({"check": f"import:{mod}", "ok": False, "error": str(e)})
            result["ok"] = False

    print(json.dumps(result, indent=2))
    return result
