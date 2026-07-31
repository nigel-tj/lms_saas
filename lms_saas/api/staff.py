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
        return cost_center

    return None


def _is_admin() -> bool:
    """True for System Manager / Administrator (branch isolation bypass)."""
    user = frappe.session.user
    return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _assert_branch_scope(target_branch: str | None) -> None:
    """Fail-closed branch scoping for non-manager staff endpoints.

    Any staffer (helpdesk, collections, tasks, documents, CRM, savings staff)
    may only act on records in their own branch. Admins bypass. A staffer with
    no branch assigned is denied (fail closed). Mirrors the officer/manager
    variants but is role-neutral so it can be reused across all staff modules.
    """
    if _is_admin():
        return
    branch = get_current_user_branch()
    if not branch:
        frappe.throw("Not in your branch.", frappe.PermissionError)
    if target_branch and target_branch != branch:
        frappe.throw("Not in your branch.", frappe.PermissionError)
