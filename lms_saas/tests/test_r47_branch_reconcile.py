"""R47 staff-branch reconciliation regression tests.

Regression filed 2026-08-08:

After a clean fresh install on the live bench (Company renamed
``Kesari`` → ``LMS Demo Co``, currency switched ``ZAR`` → ``USD``),
the manager logged in and saw an empty dashboard. Root cause: the
manager's ``Employee.custom_lms_branch`` was still set to the
R42-era legacy name ``Main Branch - LMS`` (which no longer exists
as a Cost Center after R43 renamed everything to ``- LD``). The
manager's branch resolved to a phantom value, every data query
returned zero rows, and the operator concluded "all the data is
missing".

Two complementary fixes:

- **R47-A**: ``lms_saas.setup.live_repair.reconcile_staff_branches()``
  detects Employees whose ``custom_lms_branch`` doesn't match any
  Cost Center in the company and reassigns them to the fallback
  branch (the one most existing records are tagged with).

- **R47-B**: ``LMSUserSetup._validate_branch_for_staff()`` now
  refuses to submit if the chosen branch is not a real Cost Center
  in the default company. Prevents the bug at the source.

- **R47-C**: ``repair_live_site_state()`` now invokes
  ``reconcile_staff_branches()`` so every deploy on the live bench
  picks up any drift.

These tests are source-level assertions on the lms_saas code. The
point is to lock the fixes in place so a future refactor can't
reintroduce the phantom-branch bug without test failure.
"""

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
APP_ROOT = REPO_ROOT / "apps" / "lms_saas" / "lms_saas"
LIVE_REPAIR = APP_ROOT / "setup" / "live_repair.py"
LMS_USER_SETUP = APP_ROOT / "lms_saas" / "doctype" / "lms_user_setup" / "lms_user_setup.py"


def _read(path: Path) -> str:
    return path.read_text()


def _function_body(src: str, fn_name: str) -> str:
    """Extract the body of a top-level function.

    Top-level Python functions are at zero indent. The body runs
    until the next top-level ``def ``/``class `` or EOF. This is
    robust against nested defs (helpers inside other functions) and
    decorators (e.g. ``@frappe.whitelist``).
    """
    start = src.find(f"def {fn_name}")
    if start == -1:
        return ""
    end = src.find("\ndef ", start + 1)
    if end == -1:
        end = len(src)
    return src[start:end]


class TestR47BranchReconcile(unittest.TestCase):
    """R47 staff-branch reconciliation source-level regression coverage."""

    # --------------------------------------------------------------
    # R47-A: reconcile_staff_branches() must exist in live_repair.py.
    # --------------------------------------------------------------
    def test_reconcile_staff_branches_defined_in_live_repair(self):
        """The function is the surgical fix for phantom-branch drift.
        Without it, the manager would stay stuck on the legacy
        ``Main Branch - LMS`` even after multiple deploys."""
        src = _read(LIVE_REPAIR)
        self.assertIn(
            "def reconcile_staff_branches",
            src,
            msg="reconcile_staff_branches() must be defined in live_repair.py",
        )

    # --------------------------------------------------------------
    # R47-A: reconcile_staff_branches() must use the company-scoped
    # Cost Center lookup (not a global one) so cross-company
    # contamination cannot reintroduce the bug.
    # --------------------------------------------------------------
    def test_reconcile_filters_cost_centers_by_company(self):
        """A stale cross-company branch (e.g. ``Main - K`` from a previous
        bench install) was part of the original bug surface. The
        reconcile must filter ``Cost Center.company = current_company``."""
        body = _function_body(_read(LIVE_REPAIR), "reconcile_staff_branches")
        self.assertTrue(body, msg="reconcile_staff_branches body not found")
        self.assertIn('"company": company', body, msg="must filter Cost Centers by company")
        self.assertIn('"is_group": 0', body, msg="must exclude group Cost Centers")

    # --------------------------------------------------------------
    # R47-A: reconcile_staff_branches() must write BOTH
    # Employee.branch AND Employee.custom_lms_branch so the fix
    # matches what LMS User Setup.on_submit writes (R28-F1 invariant).
    # --------------------------------------------------------------
    def test_reconcile_writes_both_branch_and_custom_lms_branch(self):
        """``staff.get_current_user_branch()`` looks at custom_lms_branch
        FIRST, but Employee.branch is the HRMS canonical field. Both
        must be updated for consistency with the original write path."""
        body = _function_body(_read(LIVE_REPAIR), "reconcile_staff_branches")
        self.assertIn('"custom_lms_branch"', body)
        self.assertIn('"branch"', body)
        self.assertIn('"to_branch": fallback', body)

    # --------------------------------------------------------------
    # R47-A: reconcile_staff_branches() must be idempotent and safe
    # to re-run. The function must return an ``ok`` field so the
    # caller can detect failures.
    # --------------------------------------------------------------
    def test_reconcile_returns_idempotent_summary(self):
        """Operators run this on every deploy, so it must report
        what it did — without that, a silent no-op looks identical
        to a successful repair."""
        body = _function_body(_read(LIVE_REPAIR), "reconcile_staff_branches")
        self.assertIn('"ok"', body)
        self.assertIn('"fallback_branch"', body)
        self.assertIn('"repaired"', body)
        self.assertIn("already_valid", body, msg="must track already-valid Employees")
        self.assertIn("valid_branches", body, msg="must build a valid_branches set")

    # --------------------------------------------------------------
    # R47-C: repair_live_site_state() must invoke
    # reconcile_staff_branches() so every deploy on live picks up
    # any drift. Without this wire-up the fix is dormant.
    # --------------------------------------------------------------
    def test_repair_live_site_state_invokes_reconcile_staff_branches(self):
        """The reconcile function is useless if nothing calls it.
        ``repair_live_site_state()`` is the canonical live-deploy
        entry point — it must invoke the reconcile so every live
        deploy auto-heals branch drift."""
        body = _function_body(_read(LIVE_REPAIR), "repair_live_site_state")
        self.assertTrue(body, msg="repair_live_site_state body not found")
        self.assertIn(
            "reconcile_staff_branches",
            body,
            msg="repair_live_site_state must invoke reconcile_staff_branches",
        )
        # The result must be reported in the return so operators see it.
        self.assertIn(
            "branch_repair",
            body,
            msg="return value must include branch_repair so operators see drift detection",
        )

    # --------------------------------------------------------------
    # R47-B: LMS User Setup._validate_branch_for_staff() must
    # refuse to submit if the chosen branch is not a real Cost Center.
    # --------------------------------------------------------------
    def test_lms_user_setup_validates_branch_exists(self):
        """The fix at the source: prevent the bug from being created
        in the first place. Without this validation, every future
        install can re-create the phantom-branch state by typing a
        wrong branch on the LMS User Setup form."""
        body = _function_body(_read(LMS_USER_SETUP), "_validate_branch_for_staff")
        self.assertTrue(body, msg="_validate_branch_for_staff body not found")
        # Must check that the branch is a Cost Center in the company.
        self.assertIn('"Cost Center"', body, msg="must check the branch against Cost Center")
        self.assertIn("company", body, msg="must scope the check to the default company")
        # Must throw on failure (not just warn).
        self.assertIn("frappe.throw", body, msg="must refuse submission on phantom branch")


if __name__ == "__main__":
    unittest.main()
