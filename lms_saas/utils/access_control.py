"""Access-control module — single source of truth for guards.

Consolidates the 18+ copies of ``_is_admin()``, 3 divergent
``_assert_branch_scope()`` implementations, and 15+ one-liner
``_require_*()`` persona guards that were copy-pasted across every
API module.

Interface (small, deep):

- :func:`is_admin` — True for System Manager / Administrator.
- :func:`current_branch` — resolve the caller's branch (Cost Center).
- :func:`current_persona` — resolve the caller's LMS persona.
- :func:`require_persona` — throw if the caller's persona is not in
  the allowed set (admins always pass).
- :func:`assert_branch_scope` — enforce branch isolation with a
  configurable fail mode (``"open_read"``, ``"closed"``, ``"diagnostic"``).

Every API module that previously had its own ``_is_admin``,
``_require_*``, ``_assert_branch_scope``, or ``_*_branch`` should
import from here instead.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cstr

# ---------------------------------------------------------------------------
# Admin check — one implementation, not 18.
# ---------------------------------------------------------------------------

def is_admin() -> bool:
	"""True for System Manager / Administrator (branch isolation bypass)."""
	user = frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(frappe.get_roles()).intersection({"System Manager", "Administrator"}))


# ---------------------------------------------------------------------------
# Branch resolution — one implementation, not 4.
# ---------------------------------------------------------------------------

def current_branch() -> str | None:
	"""Resolve the caller's branch (Cost Center) for query scoping.

	Delegates to ``lms_saas.api.staff.get_current_user_branch`` — the
	same resolution used by every module.  Top-level import so tests can
	monkey-patch ``staff.get_current_user_branch`` via the module
	reference (R12 board feedback: late imports defeat the monkey-patch).
	"""
	import lms_saas.api.staff as _staff

	return _staff.get_current_user_branch()


def current_employee() -> str | None:
	"""Return the Employee name linked to the current user, or None."""
	user = frappe.session.user
	filters = {"user_id": user}
	if frappe.get_meta("Employee").has_field("status"):
		filters["status"] = "Active"
	return frappe.db.get_value("Employee", filters, "name")


# ---------------------------------------------------------------------------
# Persona resolution — one implementation, not 3.
# ---------------------------------------------------------------------------

def current_persona() -> str | None:
	"""Resolve the caller's LMS persona (Loan Officer / Branch Manager / Collector / Borrower).

	Delegates to the existing persona resolver in ``utils.portal``.
	"""
	from lms_saas.utils.portal import resolve_portal_persona

	return resolve_portal_persona()


# ---------------------------------------------------------------------------
# Persona guard — replaces every ``_require_*`` copy.
# ---------------------------------------------------------------------------

def require_persona(
	*allowed: str,
	guest_msg: str | None = None,
) -> None:
	"""Throw PermissionError if the caller's persona is not in *allowed*.

	Admins (System Manager / Administrator) always pass.

	Args:
		*allowed: persona labels that may call the endpoint
			(e.g. ``"Loan Officer"``, ``"Branch Manager"``).
		guest_msg: custom message for unauthenticated callers
			(defaults to ``"Please log in"``).

	Sets ``frappe.flags.ignore_permissions = True`` after a successful
	staff-persona check — portal staff roles don't have row-level
	permissions on Loan / Loan Application / Customer, but the API
	scopes by branch via custom_lms_branch filters, so bypassing
	row-level permissions is safe and necessary.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(guest_msg or _("Please log in"), frappe.PermissionError)

	if is_admin():
		return

	persona = current_persona()
	allowed_set = set(allowed)
	if persona and persona in allowed_set:
		# Portal staff roles lack read permission on Loan / Loan
		# Application / Customer.  The API scopes by branch via
		# custom_lms_branch filters, so bypassing row-level
		# permissions is safe and necessary for dashboards, lists,
		# and detail views to return data.
		frappe.flags.ignore_permissions = True
		return

	frappe.throw(_("Not permitted"), frappe.PermissionError)


# ---------------------------------------------------------------------------
# Branch-scope guard — one implementation with a configurable fail mode.
# ---------------------------------------------------------------------------

# Fail-mode constants — replace the three divergent copies:
#   officer.py  → fail-open-read (branchless caller can read with soft log)
#   manager.py  → fail-open-read + diagnostic (same, but with extra detail)
#   staff.py    → fail-closed (branchless caller is denied, even for reads)
FAIL_OPEN_READ = "open_read"      # branchless caller: read OK (soft log), write denied
FAIL_CLOSED = "closed"            # branchless caller: always denied
FAIL_DIAGNOSTIC = "diagnostic"    # like FAIL_OPEN_READ but with extra detail on write


def assert_branch_scope(
	target_branch: str | None,
	*,
	write: bool = False,
	fail_mode: str = FAIL_OPEN_READ,
) -> None:
	"""Enforce branch isolation on a single action.

	Args:
		target_branch: the branch (Cost Center) of the record being
			accessed.  ``None`` means the record has no branch
			(legacy data).
		write: ``True`` if the action mutates data (disburse, repay,
			update).  ``False`` for reads.
		fail_mode: what to do when the caller has no branch assigned:

			``FAIL_OPEN_READ`` — branchless caller can read
			(with a soft log) but cannot write.  Use for officer
			and manager endpoints.

			``FAIL_CLOSED`` — branchless caller is always denied,
			even for reads.  Use for staff endpoints (helpdesk,
			tasks, documents, etc.).

			``FAIL_DIAGNOSTIC`` — like ``FAIL_OPEN_READ`` but the
			write-denial error includes a diagnostic block showing
			exactly which Employee fields were checked.  Use for
			manager write endpoints where the operator needs the
			detail to fix the assignment.

	Policy (all fail modes):
		- Admins bypass entirely.
		- Caller has a branch + target has a branch + differ → throw.
		- Target has no branch → allow with a soft log (legacy data).
	"""
	if is_admin():
		return

	branch = current_branch()

	if not branch:
		if write:
			_throw_branchless_write(fail_mode)
		if fail_mode == FAIL_CLOSED:
			frappe.throw(_("Not in your branch."), frappe.PermissionError)
		# FAIL_OPEN_READ / FAIL_DIAGNOSTIC: soft log, allow read.
		frappe.log_error(
			title="LMS branch-scope: caller has no branch (read fallback)",
			message=(
				f"user={frappe.session.user} action=read "
				f"target_branch={target_branch or '<empty>'}"
			),
		)
		return

	if not target_branch:
		frappe.log_error(
			title="LMS branch-scope: target has no branch",
			message=(
				f"user={frappe.session.user} branch={branch} "
				f"target_branch=<empty>"
			),
		)
		return

	if target_branch != branch:
		frappe.throw(_("Not in your branch."), frappe.PermissionError)


def _throw_branchless_write(fail_mode: str) -> None:
	"""Throw the branchless-write error, with optional diagnostic detail."""
	if fail_mode == FAIL_DIAGNOSTIC:
		# Manager variant: include the Employee fields checked so the
		# operator can see exactly what's missing.
		emp_meta = frappe.get_meta("Employee")
		emp_filters = {"user_id": frappe.session.user}
		if emp_meta.has_field("status"):
			emp_filters["status"] = "Active"
		emp_name = frappe.db.get_value("Employee", emp_filters, "name")
		fields_checked = []
		if emp_meta.has_field("custom_lms_branch"):
			fields_checked.append(
				"custom_lms_branch="
				+ repr(frappe.db.get_value("Employee", emp_filters, "custom_lms_branch"))
			)
		if emp_meta.has_field("cost_center"):
			fields_checked.append(
				"cost_center="
				+ repr(frappe.db.get_value("Employee", emp_filters, "cost_center"))
			)
		diagnostic = (
			f"Employee={emp_name or '<none>'}; "
			f"checked fields: {', '.join(fields_checked) or 'no branch fields on Employee'}; "
			f"User Permission on Cost Center: "
			f"{frappe.get_all('User Permission', filters={'user': frappe.session.user, 'allow': 'Cost Center'}, pluck='for_value') or '<none>'}"
		)
		frappe.throw(
			_(
				"Your account is not assigned to a branch. Contact your HR / "
				"system manager before performing write actions. Diagnostic: {0}"
			).format(diagnostic),
			frappe.PermissionError,
		)

	# Default (FAIL_OPEN_READ): plain message.
	frappe.throw(
		_(
			"Your account is not assigned to a branch. Contact your HR / "
			"system manager before performing write actions."
		),
		frappe.PermissionError,
	)