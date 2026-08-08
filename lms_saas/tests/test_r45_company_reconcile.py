"""R45 company-reconcile regression tests.

Three regressions were filed 2026-08-08:

- **R45-C1**: live deploy flipped ``lms_currency`` to ZAR because
  the live site was bootstrapped with Company "Kesari" (currency=ZAR).
  ``_sync_site_config_currency`` faithfully read that Company currency
  and wrote ZAR to site_config — but the real bug was the Company
  itself. ``reconcile_company_name()`` is the surgical fix.

- **R45-C2**: ``fresh_install.run`` step 4 had no rename path — it
  only updated currency/country on an existing Company, never the
  name/abbr. So calling fresh_install with ``company="LMS Demo Co"``
  on a site whose Company was "Kesari" silently did nothing about
  the name mismatch. Now step 4 calls ``reconcile_company_name``
  first, which renames if requested.

- **R45-C3**: the deploy script ``frappe-cloud-update.sh`` had no
  way for an operator to request "rename Company + retag currency
  on this deploy" — the LMS_COMPANY_OVERRIDE env var now wires the
  reconcile step into the deploy pipeline.

These tests are source-level assertions. The point is to lock the
fixes in place so a future refactor can't regress the live↔local
company parity without test failure.
"""

import os
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
APP_ROOT = REPO_ROOT / "apps" / "lms_saas" / "lms_saas"
SCRIPTS_ROOT = REPO_ROOT / "apps" / "lms_saas" / "scripts"


def _read(rel_path):
    return (APP_ROOT / rel_path).read_text()


def _read_script(name):
    return (SCRIPTS_ROOT / name).read_text()


class TestR45CompanyReconcile(unittest.TestCase):
    """R45 company reconciliation source-level regression coverage."""

    # --------------------------------------------------------------
    # R45-C1: reconcile_company_name must exist in live_repair.py.
    # --------------------------------------------------------------
    def test_reconcile_company_name_defined_in_live_repair(self):
        """``reconcile_company_name()`` is the surgical one-shot that
        renames + retags the default Company on live. Without it,
        the only way to fix the live currency/name mismatch is
        manual DB surgery."""
        src = _read("setup/live_repair.py")
        self.assertRegex(
            src,
            r"def\s+reconcile_company_name\s*\(",
            msg="reconcile_company_name() must be defined in live_repair.py",
        )

    # --------------------------------------------------------------
    # R45-C1: reconcile_company_name must accept all 5 args
    # (company, abbr, currency, country, apply).
    # --------------------------------------------------------------
    def test_reconcile_company_name_signature_includes_apply(self):
        """The function must take ``apply`` as a kwarg so the operator
        can dry-run before writing."""
        src = _read("setup/live_repair.py")
        m = re.search(r"def\s+reconcile_company_name\s*\(([^)]*)\)", src)
        self.assertIsNotNone(m, msg="reconcile_company_name signature not found")
        sig = m.group(1)
        for arg in ("company", "abbr", "currency", "country", "apply"):
            self.assertIn(arg, sig, msg=f"reconcile_company_name must accept {arg!r}")

    # --------------------------------------------------------------
    # R45-C1: reconcile_company_name must call frappe.rename_doc so
    # the rename actually propagates everywhere Frappe links by name.
    # --------------------------------------------------------------
    def test_reconcile_company_name_uses_frappe_rename_doc(self):
        """A simple ``set_value(Company, current, {'company_name': new})``
        is a no-op because ``company_name`` is the primary key for
        DocType lookups. ``frappe.rename_doc`` is the only correct way."""
        src = _read("setup/live_repair.py")
        # Find the reconcile_company_name function header line, then
        # the next def / class / top-level decorator marks its end.
        start = src.find("def reconcile_company_name")
        self.assertNotEqual(start, -1, msg="reconcile_company_name() not defined")
        # Body = everything from the start line through the next top-level
        # `def ` / `class ` / `@frappe.whitelist()` marker (or EOF).
        end_candidates = [
            src.find("\ndef ", start + 1),
            src.find("\nclass ", start + 1),
            src.find("\n@frappe.whitelist", start + 1),
            src.find("\n# ---", start + 1),
        ]
        end_candidates = [e for e in end_candidates if e != -1]
        body = src[start:min(end_candidates) if end_candidates else len(src)]
        self.assertIn("frappe.rename_doc", body, msg="must use frappe.rename_doc, not set_value, to rename the Company")
        self.assertIn('"Company"', body, msg="must target the Company DocType")

    # --------------------------------------------------------------
    # R45-C1: reconcile_company_name must sync lms_currency into
    # site_config.json so the login page (no session) shows the right
    # symbol immediately.
    # --------------------------------------------------------------
    def test_reconcile_company_name_syncs_site_config_currency(self):
        """The whole point of R45 is that the login page must show USD
        (or whatever currency the operator requested) without waiting
        for a User session. That requires site_config.json update."""
        src = _read("setup/live_repair.py")
        start = src.find("def reconcile_company_name")
        self.assertNotEqual(start, -1)
        end_candidates = [
            src.find("\ndef ", start + 1),
            src.find("\nclass ", start + 1),
            src.find("\n@frappe.whitelist", start + 1),
            src.find("\n# ---", start + 1),
        ]
        end_candidates = [e for e in end_candidates if e != -1]
        body = src[start:min(end_candidates) if end_candidates else len(src)]
        self.assertIn('"lms_currency"', body, msg="must write lms_currency to site_config")
        self.assertIn("site_config.json", body, msg="must write to site_config.json")
        self.assertIn("frappe.clear_cache", body, msg="must clear_cache so the change takes effect immediately")

    # --------------------------------------------------------------
    # R45-C2: fresh_install.run step 4 must call reconcile_company_name
    # before the create-or-update block, so passing company="LMS Demo Co"
    # to a live site whose Company was "Kesari" actually renames it.
    # --------------------------------------------------------------
    def test_fresh_install_step4_calls_reconcile_company_name(self):
        """Without this call, fresh_install silently leaves the existing
        Company name untouched — which is exactly the bug that left
        live on "Kesari" / ZAR while local is on "LMS Demo Co" / USD."""
        src = _read("setup/fresh_install.py")
        # Find the step-4 block (Company create-or-update).
        # Step 4 is the only place ``frappe.db.exists("Company")`` appears
        # inside fresh_install.py.
        step4_match = re.search(
            r"# ── 4\..*?(?=# ── 4b|# ── 5\.)",
            src,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(step4_match, msg="step 4 block not found in fresh_install.py")
        step4 = step4_match.group(0)
        self.assertIn(
            "reconcile_company_name",
            step4,
            msg="fresh_install step 4 must call reconcile_company_name before create-or-update",
        )

    # --------------------------------------------------------------
    # R45-C3: frappe-cloud-update.sh must wire the LMS_COMPANY_OVERRIDE
    # env var into a reconcile_company_name bench execute call.
    # --------------------------------------------------------------
    def test_frappe_cloud_update_wires_lms_company_override(self):
        """Operators need a deploy-time knob to rename the Company. The
        LMS_COMPANY_OVERRIDE env var (comma-separated key=value) is the
        contract."""
        src = _read_script("frappe-cloud-update.sh")
        self.assertIn("LMS_COMPANY_OVERRIDE", src, msg="LMS_COMPANY_OVERRIDE env var must be wired in")
        self.assertIn(
            "reconcile_company_name",
            src,
            msg="reconcile_company_name must be invoked from frappe-cloud-update.sh",
        )

    # --------------------------------------------------------------
    # R45-C3: frappe-cloud-update.sh must guard reconcile_company_name
    # behind LMS_SKIP_CURRENCY_RESET so operators can opt out (e.g.
    # when the live Company name is intentional, not a drift bug).
    # --------------------------------------------------------------
    def test_frappe_cloud_update_guards_reconcile_under_skip_currency_reset(self):
        """If the operator already set LMS_SKIP_CURRENCY_RESET=1, the
        reconcile step must also be skipped — otherwise the gate is
        leaky."""
        src = _read_script("frappe-cloud-update.sh")
        # The LMS_COMPANY_OVERRIDE branch must live INSIDE the
        # LMS_SKIP_CURRENCY_RESET block. Find the offset of the
        # skip-currency guard open + close, and assert the
        # override branch sits between them.
        open_idx = src.find('if [[ "${LMS_SKIP_CURRENCY_RESET:-0}" != "1" ]]; then')
        close_idx = src.find('else', open_idx)
        close_idx_end = src.find('fi', close_idx)
        self.assertNotEqual(open_idx, -1)
        self.assertNotEqual(close_idx_end, -1)
        block = src[open_idx:close_idx_end]
        self.assertIn("LMS_COMPANY_OVERRIDE", block)
        self.assertIn("reconcile_company_name", block)


if __name__ == "__main__":
    unittest.main()
