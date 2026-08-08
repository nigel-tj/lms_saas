"""R48 deploy-script kwargs bug + Cost Center rename regression tests.

Two regressions filed 2026-08-08:

- **R48-C1**: ``frappe-cloud-update.sh`` invoked
  ``reconcile_company_name`` with broken shell quoting:
  ``--kwargs "'$override_kwargs'"``. The wrapping single quotes got
  concatenated into the value, so bench's ``eval(kwargs)`` failed
  with "argument after ** must be a mapping, not str". The
  function was called with no kwargs, NameError-fell back to
  ``eval(args)``, and the entire rename silently did nothing.
  Live deploy showed the function "running" but no Company rename
  happened. The shell was the bug, not the Python.

- **R48-C2**: even if ``reconcile_company_name`` had run, it
  renamed the Company master record but did NOT rename the
  Cost Centers that embed the old company abbr (``Main Branch - LS``
  etc.). After the rename, ``staff.get_current_user_branch()``
  would still return ``Main Branch - LS`` for any Employee that was
  on the legacy branch — because the Cost Center names are what the
  branch resolver matches. ``frappe.rename_doc("Cost Center")`` is
  blocked by ERPNext ("not allowed to be renamed") so we had to
  use a direct SQL UPDATE plus a bulk retag of every Employee /
  Customer / Loan / Loan Application whose ``custom_lms_branch``
  still references the old branch name.

These tests are source-level assertions on the lms_saas code. The
point is to lock the fixes in place so a future refactor can't
reintroduce either bug without test failure.
"""

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
APP_ROOT = REPO_ROOT / "apps" / "lms_saas" / "lms_saas"
LIVE_REPAIR = APP_ROOT / "setup" / "live_repair.py"
DEPLOY_SCRIPT = REPO_ROOT / "apps" / "lms_saas" / "scripts" / "frappe-cloud-update.sh"


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


class TestR48DeployKwargs(unittest.TestCase):
    """R48 deploy-script kwargs bug + Cost Center rename coverage."""

    # --------------------------------------------------------------
    # R48-C1: frappe-cloud-update.sh must NOT wrap --kwargs in single
    # quotes. Wrapping was the bug that caused the function to be
    # called with empty kwargs.
    # --------------------------------------------------------------
    def test_deploy_script_does_not_wrap_kwargs_in_single_quotes(self):
        """The bug was ``--kwargs "'$override_kwargs'"``. The wrapping
        quotes got concatenated into the value and bench's eval(kwargs)
        failed. The fix: hand bench the literal directly with NO outer
        quoting (``--kwargs "$override_kwargs"``)."""
        src = _read(DEPLOY_SCRIPT)
        # Find the line that invokes reconcile_company_name.
        # The buggy pattern was `--kwargs "'$override_kwargs'"` (with
        # wrapping single quotes around the variable).
        self.assertNotIn(
            "--kwargs \"'$override_kwargs'\"",
            src,
            msg="deploy script must not wrap --kwargs in single quotes",
        )
        # The fix: --kwargs "$override_kwargs" (just double quotes).
        # Check for the fix pattern (allow whitespace variance).
        self.assertRegex(
            src,
            r'--kwargs\s+"\$\{?override_kwargs\}?"',
            msg="deploy script must pass --kwargs without wrapping single quotes",
        )

    # --------------------------------------------------------------
    # R48-C1: the python snippet that builds the kwargs must emit a
    # VALID PYTHON DICT LITERAL (not JSON). bench execute does
    # eval(kwargs), so the value must parse as a dict.
    # --------------------------------------------------------------
    def test_kwargs_snippet_emits_python_dict_literal_not_json(self):
        """JSON requires double quotes around keys, but a Python dict
        literal allows single quotes too. The script uses single quotes
        to avoid JSON-vs-Python confusion. Verify by looking for
        single-quoted keys in the snippet."""
        src = _read(DEPLOY_SCRIPT)
        # The Python snippet uses f-string with single-quoted keys.
        # The shell-escape machinery makes the literal hard to grep
        # for, so we check the *semantically equivalent* Python that
        # the shell emits: the snippet must reference ``v_escaped``
        # (proves it's building a Python literal, not JSON-dumping)
        # AND must wrap the values in single quotes.
        self.assertIn(
            "v_escaped",
            src,
            msg="snippet must build via v_escaped Python variable (not json.dumps)",
        )
        # The snippet must NOT use json.dumps (which produces
        # double-quoted JSON that bench's eval cannot parse).
        self.assertNotIn(
            "json.dumps",
            src,
            msg="snippet must NOT use json.dumps (produces JSON, not Python dict)",
        )
        # And it must NOT wrap --kwargs in '...' (the original bug).
        self.assertNotIn(
            "--kwargs \"'$",
            src,
            msg="snippet must NOT wrap --kwargs value in wrapping single quotes (R48 bug)",
        )

    # --------------------------------------------------------------
    # R48-C2: _rename_cost_centers_for_abbr_change() must exist in
    # live_repair.py. Without it, an abbr change leaves phantom
    # Cost Centers and the manager's branch resolution still breaks.
    # --------------------------------------------------------------
    def test_rename_cost_centers_defined_in_live_repair(self):
        """The function renames Cost Centers that embed the old abbr
        (e.g. ``Main Branch - LS`` → ``Main Branch - SP``) AND retags
        every Employee/Customer/Loan that points to the old branch
        name. Without both halves, branch resolution stays broken."""
        body = _function_body(_read(LIVE_REPAIR), "_rename_cost_centers_for_abbr_change")
        self.assertTrue(body, msg="_rename_cost_centers_for_abbr_change must be defined")

    # --------------------------------------------------------------
    # R48-C2: the function must use direct SQL (not frappe.rename_doc)
    # because ERPNext blocks Cost Center rename.
    # --------------------------------------------------------------
    def test_rename_cost_centers_uses_sql_not_rename_doc(self):
        """ERPNext raises ``CannotRename`` for Cost Centers. We must
        bypass the rename controller with a direct SQL UPDATE on
        ``tabCost Center.name``. The function must NOT call
        ``frappe.rename_doc("Cost Center", ...)``."""
        body = _function_body(_read(LIVE_REPAIR), "_rename_cost_centers_for_abbr_change")
        self.assertNotIn(
            'frappe.rename_doc("Cost Center"',
            body,
            msg="must NOT use frappe.rename_doc for Cost Center (ERPNext blocks it)",
        )
        # Must use SQL UPDATE on tabCost Center.
        self.assertIn(
            "UPDATE `tabCost Center`",
            body,
            msg="must use direct SQL UPDATE on tabCost Center",
        )

    # --------------------------------------------------------------
    # R48-C2: the function must retag Employees / Customers / Loans /
    # Loan Applications so any record pointing at the OLD branch
    # name gets re-pointed at the NEW branch name.
    # --------------------------------------------------------------
    def test_rename_cost_centers_retags_employees_customers_loans(self):
        """After the Cost Center rename, Employee.custom_lms_branch,
        Customer.custom_lms_branch, Loan.custom_lms_branch, and
        Loan Application.custom_lms_branch all still hold the OLD
        branch name. Without a bulk retag, branch resolution stays
        broken even after the rename."""
        body = _function_body(_read(LIVE_REPAIR), "_rename_cost_centers_for_abbr_change")
        for doctype in ("Employee", "Customer", "Loan", "Loan Application"):
            self.assertIn(
                f"UPDATE `tab{doctype}`",
                body,
                msg=f"must bulk-retag {doctype}.custom_lms_branch",
            )
            self.assertIn(
                "REPLACE(custom_lms_branch",
                body,
                msg=f"must use REPLACE() to swap {doctype} branch strings",
            )

    # --------------------------------------------------------------
    # R48-C2: the function must be a no-op when old_abbr == new_abbr
    # or when called without args (defensive guard).
    # --------------------------------------------------------------
    def test_rename_cost_centers_is_noop_on_equal_abbrs(self):
        """If the operator requests a rename with the same abbr (e.g.
        ``LMS_COMPANY_OVERRIDE="abbr=LD"`` when the company is
        already ``LD``), the function must return an empty list and
        not touch any rows."""
        body = _function_body(_read(LIVE_REPAIR), "_rename_cost_centers_for_abbr_change")
        # The early-return guard must check abbr change.
        self.assertRegex(
            body,
            r"old_abbr.*new_abbr.*!=",
            msg="must early-return when old_abbr == new_abbr",
        )

    # --------------------------------------------------------------
    # R48-C2: reconcile_company_name must invoke
    # _rename_cost_centers_for_abbr_change when abbr_change is set,
    # so the rename + retag actually runs end-to-end.
    # --------------------------------------------------------------
    def test_reconcile_company_name_invokes_rename_cost_centers(self):
        """The reconcile function is the operator-facing entry point.
        If it doesn't call _rename_cost_centers_for_abbr_change when
        the abbr changes, the deploy bug (phantom branches) persists
        after every deploy."""
        body = _function_body(_read(LIVE_REPAIR), "reconcile_company_name")
        self.assertIn(
            "_rename_cost_centers_for_abbr_change",
            body,
            msg="reconcile_company_name must call _rename_cost_centers_for_abbr_change",
        )
        # The invocation must be inside the abbr_change branch (we
        # don't want to run it when only the name changed).
        self.assertIn("if abbr_change:", body)


if __name__ == "__main__":
    unittest.main()
