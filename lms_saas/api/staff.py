"""Staff onboarding hooks.

Routes LMS desk users onto the locked-down `LMS Staff` module profile so new or
edited staff automatically get the focused Loan Management sidebar, with zero
per-user setup. The actual logic lives in `lms_saas.install` (single source of
truth for the lockdown); this module is the thin doc_event entry point.

Also exposes ``get_current_user_branch`` (whitelisted) so the LMS User Setup
form can default the Branch field to the signed-in user's branch without the
client having to know how branches are resolved (Employee → Cost Center, or a
User Permission on Cost Center).
"""

import frappe

from lms_saas.install import apply_lms_module_profile as _apply_lms_module_profile


def apply_lms_module_profile(doc, method=None):
    _apply_lms_module_profile(doc, method=method)


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
    for branch_field in ("branch", "cost_center", "custom_lms_branch"):
        if not employee_meta.has_field(branch_field):
            continue
        employee_branch = frappe.db.get_value("Employee", employee_filters, branch_field)
        if employee_branch:
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
