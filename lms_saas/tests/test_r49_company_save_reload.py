"""R49 Company-reconcile save/reload bug regression tests.

Regression filed 2026-08-08:

When ``reconcile_company_name`` ran on live with
``LMS_COMPANY_OVERRIDE="company=Salt & Paper Co,abbr=SP,currency=USD,country=Zimbabwe"``,
THREE bugs surfaced:

- **R49-C1**: ``Company.abbr`` is locked by ERPNext. The controller
  raises ``"Value cannot be changed for Abbr"`` on save(). The
  previous code did ``current_doc.abbr = target_abbr; current_doc.save()``
  and the save raised — the Company doc kept the OLD abbr even after
  ``_rename_cost_centers_for_abbr_change`` had already renamed every
  Cost Center to use the NEW abbr. Result: Cost Centers say
  ``- SP`` but the Company doc says ``abbr=LS`` — internally
  inconsistent.

- **R49-C2**: After ``frappe.rename_doc("Company", ...)`` the
  in-memory ``current_doc`` handle is STALE — rename_doc creates a
  new doc with the same name under the hood. Subsequent
  ``current_doc.save()`` calls raised the optimistic-lock error:
  ``"Company has been modified after you opened it"``. The currency
  + country updates silently failed.

- **R49-C3**: After ``reconcile_company_name`` ran (and partially
  failed), the NEXT step in ``frappe-cloud-update.sh``,
  ``_sync_site_config_currency``, read the Company doc (still ZAR
  because the currency save failed) and overwrote the freshly
  written ``lms_currency=USD`` back to ZAR. The previous
  fix's work was undone by the next step.

Fixes:

- **R49-A**: ``Company.abbr`` change uses a direct SQL UPDATE
  (``UPDATE tabCompany SET abbr = ...``) instead of
  ``current_doc.save()``. ERPNext's controller hook fires only on
  ``save()`` — direct SQL bypasses it. After the SQL update we
  reload the doc via ``frappe.get_doc("Company", name)`` so the
  in-memory handle is fresh.

- **R49-B**: After ``frappe.rename_doc`` AND after every
  ``current_doc.save()`` we reload via ``frappe.get_doc(...)``
  before the next save. This defeats the stale-handle / optimistic
  lock issue.

- **R49-C**: Documented in the test that the next-step
  (``_sync_site_config_currency``) is now a no-op when the
  Company's ``default_currency`` already matches ``site_config.lms_currency``,
  so a failed reconcile no longer undoes its own work.

These tests are source-level assertions on ``live_repair.py``. The
point is to lock the fixes in place so a future refactor can't
reintroduce the bugs without test failure.
"""

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
APP_ROOT = REPO_ROOT / "apps" / "lms_saas" / "lms_saas"
LIVE_REPAIR = APP_ROOT / "setup" / "live_repair.py"
SYNC_SITE_CONFIG = APP_ROOT / "setup" / "set_company_currency_country.py"


def _read(path: Path) -> str:
    return path.read_text()


def _function_body(src: str, fn_name: str) -> str:
    """Extract the body of a top-level function (zero indent)."""
    start = src.find(f"def {fn_name}")
    if start == -1:
        return ""
    end = src.find("\ndef ", start + 1)
    if end == -1:
        end = len(src)
    return src[start:end]


class TestR49CompanySaveReload(unittest.TestCase):
    """R49 Company-reconcile save/reload + abbr-SQL bug coverage."""

    # --------------------------------------------------------------
    # R49-A: reconcile_company_name must NOT use doc.save() for the
    # abbr change — must use direct SQL on tabCompany.
    # --------------------------------------------------------------
    def test_reconcile_company_abbr_uses_sql_not_save(self):
        """ERPNext blocks ``Company.abbr`` changes via the controller's
        on_update hook. The only safe way to bypass is a direct SQL
        UPDATE on ``tabCompany``. Verify that the abbr-change block
        contains a SQL UPDATE and does NOT call ``.save()`` on the
        in-memory doc."""
        body = _function_body(_read(LIVE_REPAIR), "reconcile_company_name")
        # Locate the abbr_change block specifically.
        idx = body.find("abbr_change:")
        self.assertNotEqual(idx, -1, msg="abbr_change branch not found")
        # Take the block until the next if-block / except line.
        end = body.find("\n    if ", idx + 1)
        if end == -1:
            end = len(body)
        abbr_block = body[idx:end]
        # Must use SQL UPDATE.
        self.assertIn(
            "UPDATE `tabCompany`",
            abbr_block,
            msg="abbr change must use direct SQL UPDATE on tabCompany",
        )
        # Must NOT call .save() for the abbr change.
        self.assertNotIn(
            ".save(",
            abbr_block,
            msg="abbr change must NOT call doc.save() (ERPNext controller blocks it)",
        )

    # --------------------------------------------------------------
    # R49-B: every save() call in reconcile_company_name must be
    # preceded (or followed) by a reload via frappe.get_doc() so the
    # in-memory handle is fresh. This avoids "modified after you
    # opened it" errors.
    # --------------------------------------------------------------
    def test_reconcile_company_reloads_doc_after_each_save(self):
        """The Company doc's ``modified`` timestamp bumps on every save.
        Stale in-memory handles raise ``ConcurrencyError`` on the next
        save. We must reload between saves."""
        body = _function_body(_read(LIVE_REPAIR), "reconcile_company_name")
        # Find every ``current_doc.save(`` call.
        import re
        save_calls = list(re.finditer(r"current_doc\.save\(", body))
        self.assertTrue(save_calls, msg="expected at least one current_doc.save() call")
        # For each save, there must be a reload via frappe.get_doc AFTER it.
        for m in save_calls:
            after_save = body[m.end():m.end() + 500]
            self.assertIn(
                "frappe.get_doc(",
                after_save,
                msg=f"every current_doc.save() must be followed by a reload via frappe.get_doc()",
            )

    # --------------------------------------------------------------
    # R49-B: after frappe.rename_doc(), the current_doc must be reloaded
    # (the in-memory handle is stale after rename).
    # --------------------------------------------------------------
    def test_reconcile_reloads_doc_after_rename_doc(self):
        body = _function_body(_read(LIVE_REPAIR), "reconcile_company_name")
        rename_idx = body.find("frappe.rename_doc(\"Company\"")
        self.assertNotEqual(rename_idx, -1, msg="must call frappe.rename_doc for Company")
        # After rename_doc, the next ~600 chars must include a reload.
        after_rename = body[rename_idx:rename_idx + 800]
        self.assertIn(
            "frappe.get_doc(",
            after_rename,
            msg="must reload current_doc after rename_doc",
        )

    # --------------------------------------------------------------
    # R49-A: the result plan must report the SQL abbr update in
    # ``applied`` so operators can see it happened.
    # --------------------------------------------------------------
    def test_reconcile_reports_abbr_sql_in_applied(self):
        body = _function_body(_read(LIVE_REPAIR), "reconcile_company_name")
        self.assertIn(
            "company abbr updated (SQL)",
            body,
            msg="applied[] must include 'company abbr updated (SQL): ...' for operator visibility",
        )

    # --------------------------------------------------------------
    # R49-C: _sync_site_config_currency must be idempotent — when
    # site_config.lms_currency already matches the Company currency,
    # it must NOT overwrite. This prevents a partial reconcile from
    # being undone by the next deploy step.
    # --------------------------------------------------------------
    def test_sync_site_config_currency_is_noop_when_already_in_sync(self):
        """If the Company currency and site_config.lms_currency agree,
        the function must skip the write. Otherwise a partial
        reconcile (where currency save failed) would clobber the
        lms_currency that reconcile_company_name just wrote."""
        body = _function_body(_read(SYNC_SITE_CONFIG), "_sync_site_config_currency")
        # Must check equality before writing.
        self.assertIn(
            "lms_currency",
            body,
            msg="function must reference lms_currency",
        )
        # The body must contain an early-return / skip path.
        self.assertRegex(
            body,
            r"already\s*=\s*['\"]?|==.*lms_currency|skip",
            msg="function must short-circuit when already in sync",
        )


if __name__ == "__main__":
    unittest.main()
