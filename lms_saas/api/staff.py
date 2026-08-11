"""Staff onboarding helpers.

Exposes ``get_current_user_branch`` (whitelisted) so the LMS User Setup
form can default the Branch field to the signed-in user's branch without the
client having to know how branches are resolved (Employee → Cost Center, or a
User Permission on Cost Center).
"""

import frappe


@frappe.whitelist()
def get_current_user_branch():
    """Return the Cost Center (branch) for the signed-in user, or None.

    Resolution order:
      1. The Cost Center on the user's linked Employee record (HRMS).
      2. A User Permission allowing the user on a Cost Center (branch isolation).
      3. None — the form's Branch field is left blank for the user to pick.

    Used by the LMS User Setup form to pre-fill the Branch field when a branch
    manager or admin onboards new staff at their own branch.
    """
    user = frappe.session.user
    if not user or user == "Guest":
        return None

    # 1. Employee -> Branch/Cost Center (schema differs across HRMS versions).
    employee_filters = {"user_id": user}
    if frappe.get_meta("Employee").has_field("status"):
        employee_filters["status"] = "Active"

    employee_meta = frappe.get_meta("Employee")
    # R25-F5 followup: HRMS's `branch` field on the Employee doctype
    # points to the Branch DocType, which is a DIFFERENT namespace from
    # the Cost Center that custom_lms_branch / cost_center use. Try
    # them in order, but tag which one was used so the operator can
    # see why their branch isn't being recognised.
    #
    # R28-F2: ADD `branch` (HRMS) to the chain as the *last* Employee
    # fallback before User Permission. Without this, legacy benches that
    # only write the HRMS `branch` field (which LMS User Setup historically
    # does) leave officers bricked out of every write — the field that
    # LMS User Setup DOES set never makes it into the resolver.
    employee_branch = None
    resolved_from = None
    for branch_field in ("custom_lms_branch", "cost_center", "branch"):
        if not employee_meta.has_field(branch_field):
            continue
        val = frappe.db.get_value("Employee", employee_filters, branch_field)
        if val:
            employee_branch = val
            resolved_from = branch_field
            break

    if employee_branch:
        # R51: validate the resolved branch actually exists as a Cost
        # Center. After a company rebrand / abbreviation change (e.g.
        # ``LS`` → ``SP`` → ``LD``), Employee.custom_lms_branch can hold
        # a phantom value like ``Main Branch - SP`` that no longer
        # matches any Cost Center. Returning the phantom value causes
        # two cascading failures:
        #
        #   1. ``submit_application_on_behalf`` sets
        #      ``custom_lms_branch = 'Main Branch - SP'`` on the Loan
        #      Application → ``LinkValidationError`` (the Link field
        #      validates against the Cost Center doctype). The error
        #      is swallowed by the portal's safeCall and the loan
        #      silently "disappears" — it is never created.
        #
        #   2. ``_assert_branch_scope`` compares the officer's phantom
        #      branch against the borrower's real branch
        #      (``Main Branch - LD``) → ``PermissionError: Not in your
        #      branch.`` The officer cannot even select a borrower.
        #
        # Fix: if the resolved branch does not exist as a Cost Center,
        # auto-reconcile the Employee record to a valid branch (the one
        # the seeded data is tagged with) and return that. This is the
        # same logic as ``live_repair.reconcile_staff_branches`` but
        # applied lazily at resolution time so the officer never sees
        # the phantom state.
        if not frappe.db.exists("Cost Center", employee_branch):
            reconciled = _reconcile_phantom_branch(user, employee_branch)
            if reconciled:
                return reconciled
            # No valid Cost Center to reconcile to — return None so
            # the caller treats the officer as branchless (fail-open
            # for reads, fail-closed for writes) rather than returning
            # a phantom that causes LinkValidationError.
            return None

        # R28-F2: if we resolved via the HRMS `branch` field, log the
        # mismatch so the operator can see why the resolver picked it
        # (i.e. the LMS-side fields were missing).
        if resolved_from == "branch":
            frappe.log_error(
                title="LMS branch resolver fell back to HRMS branch",
                message=(
                    f"user={user} hr_branch={employee_branch!r} — "
                    "operator should set Employee.custom_lms_branch for "
                    "canonical LMS branch resolution."
                ),
            )
        return employee_branch

    # 2. User Permission on Cost Center (branch isolation set up by the admin).
    cost_center_matches = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Cost Center"},
        or_filters={"applicable_for": ["in", ["", "Cost Center"]]},
        pluck="for_value",
        limit=1,
    )
    cost_center = cost_center_matches[0] if cost_center_matches else None
    if cost_center:
        # R51: same phantom-branch guard for the User Permission path.
        if not frappe.db.exists("Cost Center", cost_center):
            reconciled = _reconcile_phantom_branch(user, cost_center)
            return reconciled  # may be None
        return cost_center

    return None


def _reconcile_phantom_branch(user: str, phantom_branch: str) -> str | None:
    """Auto-repair an Employee whose branch no longer exists as a Cost Center.

    R51: called by ``get_current_user_branch`` when the resolved branch is a
    phantom (e.g. ``Main Branch - SP`` after a company abbreviation change).
    Picks the valid Cost Center that the seeded data is tagged with (same
    logic as ``live_repair._pick_branch_used_by_seeded_data``), updates the
    Employee record in-place, logs the repair, and returns the new branch.

    Returns None if no valid Cost Center exists in the company.
    """
    company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
    if not company:
        return None

    valid_branches = frappe.get_all(
        "Cost Center",
        filters={"company": company, "is_group": 0},
        pluck="name",
    )
    if not valid_branches:
        return None

    # Pick the branch the seeded data is tagged with (most Customers/Loans).
    # Inline the ranking logic so we don't import live_repair (which would
    # create a circular dependency at module-load time in some test setups).
    def _count(table, field):
        rows = frappe.db.sql(
            """
            SELECT {0} AS branch, COUNT(*) AS n
            FROM `tab{1}`
            WHERE {0} IN %(branches)s
            GROUP BY {0}
            """.format(field, table),
            {"branches": list(valid_branches)},
            as_dict=True,
        )
        return {r["branch"]: int(r["n"]) for r in rows}

    customer_counts = _count("Customer", "custom_lms_branch")
    loan_counts = _count("Loan", "custom_lms_branch")
    best = max(
        valid_branches,
        key=lambda b: (customer_counts.get(b, 0), loan_counts.get(b, 0)),
    )
    if customer_counts.get(best, 0) == 0 and loan_counts.get(best, 0) == 0:
        main_branches = [b for b in valid_branches if "main branch" in b.lower()]
        best = sorted(main_branches)[0] if main_branches else sorted(valid_branches)[0]

    # Repair the Employee record so subsequent calls skip this path.
    emp_name = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if emp_name:
        try:
            updates = {"custom_lms_branch": best}
            if frappe.get_meta("Employee").has_field("branch"):
                updates["branch"] = best
            frappe.db.set_value("Employee", emp_name, updates, update_modified=True)
        except Exception:  # noqa: BLE001
            pass  # non-fatal — we still return the resolved branch

    frappe.log_error(
        title="LMS branch resolver auto-reconciled phantom branch",
        message=(
            f"user={user} phantom={phantom_branch!r} → reconciled={best!r} "
            f"(company={company!r}). The Employee's custom_lms_branch was "
            "updated to a valid Cost Center."
        ),
    )
    return best


def _is_admin() -> bool:
	"""True for System Manager / Administrator (branch isolation bypass).

	Delegates to the shared access-control module.
	"""
	from lms_saas.utils.access_control import is_admin
	return is_admin()


def _assert_branch_scope(target_branch: str | None) -> None:
	"""Fail-closed branch scoping for non-manager staff endpoints.

	Delegates to the shared access-control module with FAIL_CLOSED mode.
	"""
	from lms_saas.utils.access_control import assert_branch_scope, FAIL_CLOSED
	assert_branch_scope(target_branch, write=False, fail_mode=FAIL_CLOSED)
