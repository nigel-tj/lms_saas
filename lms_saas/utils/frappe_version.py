"""Frappe major-version helpers (v15 /app vs v16 /desk routing)."""

from __future__ import annotations


def get_major_version() -> int:
	import frappe

	version = getattr(frappe, "__version__", "0.0.0") or "0.0.0"
	try:
		return int(str(version).split(".", maxsplit=1)[0])
	except (TypeError, ValueError):
		return 0


def is_v16_or_later() -> bool:
	return get_major_version() >= 16


def desk_prefix() -> str:
	return "/desk" if is_v16_or_later() else "/app"


def desk_url(path: str = "") -> str:
	"""Build a desk path for the active Frappe major version."""
	path = (path or "").strip()
	if not path:
		return desk_prefix()
	if path.startswith("http://") or path.startswith("https://"):
		return path
	for legacy in ("/app/", "/desk/"):
		if path.startswith(legacy):
			path = path[len(legacy) :]
			break
	path = path.lstrip("/")
	return f"{desk_prefix()}/{path}" if path else desk_prefix()


def rewrite_desk_path(path: str) -> str:
	"""Normalize legacy /app/… or bare paths to the current desk prefix."""
	return desk_url(path)


# Native Frappe Lending module workspace (slug "lending", not "loans").
# NOTE: in v15/v16 the actual desk route Frappe renders is `/desk/<workspace-label>`,
# not `/desk/lending`. The hooks.py ``add_to_apps_screen`` route below is what is
# pointed at `/desk/lending` historically, but that URL never matched a real
# Workspace in v15+ and produced "Page lending not found" on login (issues #24
# and #26). The fix: this app does NOT own `/desk/lending`. The hook below
# points at the operator's actual landing workspace.
LENDING_HOME_SLUG = "lending"

# LMS operator-defined desk landing workspace name (title-cased; slug is the
# workspace's ``label`` field). Used by lending_home_url() to build a route
# that always resolves to a real Frappe Workspace.
#
# NOTE: historically this constant was "Lending" — but Frappe v15+ removed
# the legacy `/desk/<app-slug>` redirect table, so claiming `/desk/lending`
# for lms_saas produced "Page lending not found" on every login (#24).
# Renaming to the lms_saas-owned workspace avoids the slug collision with
# the Frappe ``lending`` app's own native "Lending" workspace.
LMS_HOME_WORKSPACE_TITLE = "Loan Management"


def lending_home_url() -> str:
	"""Staff desk home — operator-configured Loan Management workspace.

	The native ``/desk/lending`` URL is reserved by the Frappe ``lending``
	app (its own Workspace has label "Lending"). lms_saas cannot register
	itself at that URL — ``add_to_apps_screen`` historically did, which
	caused "Page lending not found" on every portal login (issues #24 &
	#26). Point at the actual lms_saas Workspace instead, resolving the
	label dynamically so renamed workspaces still work.
	"""
	import frappe
	try:
		if frappe.db.exists("Workspace", LMS_HOME_WORKSPACE_TITLE):
			ws = frappe.get_cached_doc("Workspace", LMS_HOME_WORKSPACE_TITLE)
			label = (ws.get("label") or ws.get("title") or LMS_HOME_WORKSPACE_TITLE).strip()
			return desk_url(frappe.scrub(label))
	except Exception:
		pass
	# Fallback to the legacy slug so we never return an unusable bare path.
	return desk_url(LENDING_HOME_SLUG)
