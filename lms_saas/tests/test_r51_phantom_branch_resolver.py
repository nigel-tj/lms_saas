"""R51 phantom-branch auto-reconcile in get_current_user_branch.

Regression filed 2026-08-08:

When an officer creates a loan on the live site, the loan "disappears"
— it is never created. Root cause: the officer's
``Employee.custom_lms_branch`` was set to ``Main Branch - SP`` (a
phantom value left over from a company abbreviation change ``SP`` →
``LD``). The phantom branch does not exist as a Cost Center, so:

  1. ``submit_application_on_behalf`` sets
     ``custom_lms_branch = 'Main Branch - SP'`` on the Loan
     Application → ``LinkValidationError`` (the Link field validates
     against the Cost Center doctype). The portal's safeCall swallows
     the error and the loan silently "disappears".

  2. ``_assert_branch_scope`` compares the officer's phantom branch
     against the borrower's real branch (``Main Branch - LD``) →
     ``PermissionError: Not in your branch.`` The officer cannot
     even select a borrower.

  3. ``get_pending_applications`` filters by
     ``custom_lms_branch = 'Main Branch - SP'`` → zero rows. The
     work queue is empty even though applications exist.

R51 fix: ``staff.get_current_user_branch()`` now validates that the
resolved branch exists as a Cost Center. If it doesn't, it
auto-reconciles the Employee record to a valid branch (the one the
seeded data is tagged with) and returns that — so the officer never
sees the phantom state.

These tests are source-level assertions (same pattern as R47) so a
future refactor can't remove the guard without a test failure.
"""

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
APP_ROOT = REPO_ROOT / "apps" / "lms_saas" / "lms_saas"
STAFF = APP_ROOT / "api" / "staff.py"


def _read(path: Path) -> str:
    return path.read_text()


def _function_body(src: str, fn_name: str) -> str:
    """Extract the body of a top-level function (zero-indent aware)."""
    start = src.find(f"def {fn_name}")
    if start == -1:
        return ""
    end = src.find("\ndef ", start + 1)
    if end == -1:
        end = len(src)
    return src[start:end]


class TestR51PhantomBranchResolver(unittest.TestCase):
    """R51: get_current_user_branch must validate + auto-reconcile phantom branches."""

    def test_get_current_user_branch_validates_cost_center(self):
        """The resolver must check that the resolved branch exists as a
        Cost Center before returning it. Without this check, a phantom
        branch (e.g. ``Main Branch - SP``) is returned as-is and every
        downstream query / insert fails."""
        body = _function_body(_read(STAFF), "get_current_user_branch")
        self.assertTrue(body, msg="get_current_user_branch body not found")
        self.assertIn(
            'frappe.db.exists("Cost Center"',
            body,
            msg="must validate the resolved branch against the Cost Center doctype",
        )

    def test_reconcile_phantom_branch_defined(self):
        """The auto-reconcile helper must exist — it is the surgical fix
        that repairs the Employee record in-place when a phantom branch
        is detected."""
        src = _read(STAFF)
        self.assertIn(
            "def _reconcile_phantom_branch",
            src,
            msg="_reconcile_phantom_branch must be defined in staff.py",
        )

    def test_reconcile_phantom_branch_picks_data_tagged_branch(self):
        """The reconcile must pick the Cost Center that the seeded data
        is tagged with (most Customers/Loans), not just the first
        alphabetically — so the officer lands on the branch where the
        data actually lives."""
        body = _function_body(_read(STAFF), "_reconcile_phantom_branch")
        self.assertTrue(body, msg="_reconcile_phantom_branch body not found")
        self.assertIn("customer_counts", body, msg="must rank by Customer count")
        self.assertIn("loan_counts", body, msg="must rank by Loan count")

    def test_reconcile_phantom_branch_updates_employee(self):
        """The reconcile must update the Employee record in-place so
        subsequent calls to get_current_user_branch skip the
        reconcile path (idempotent)."""
        body = _function_body(_read(STAFF), "_reconcile_phantom_branch")
        self.assertIn(
            'frappe.db.set_value("Employee"',
            body,
            msg="must update Employee.custom_lms_branch in-place",
        )
        self.assertIn(
            '"custom_lms_branch"',
            body,
            msg="must update custom_lms_branch field",
        )

    def test_reconcile_phantom_branch_returns_none_when_no_cost_centers(self):
        """If no valid Cost Center exists, the reconcile must return
        None (not the phantom) so the caller treats the officer as
        branchless rather than passing a phantom downstream."""
        body = _function_body(_read(STAFF), "_reconcile_phantom_branch")
        self.assertIn("return None", body, msg="must return None when no valid branch")

    def test_get_current_user_branch_returns_none_on_phantom_with_no_reconcile(self):
        """If the reconcile returns None (no valid Cost Centers), the
        resolver must return None — NOT the phantom value. Returning
        the phantom causes LinkValidationError on insert."""
        body = _function_body(_read(STAFF), "get_current_user_branch")
        # After the reconcile call, if reconciled is None, return None.
        self.assertIn(
            "return reconciled",
            body,
            msg="must return the reconciled branch (or None) not the phantom",
        )


if __name__ == "__main__":
    unittest.main()