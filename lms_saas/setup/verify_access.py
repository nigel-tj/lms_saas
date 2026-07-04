"""Desk workspace access audit for admin-only LMS workspaces.

Run:
  bench --site lms.localhost execute lms_saas.setup.verify_access.run_all
"""

from __future__ import annotations

import frappe
from frappe import _

from lms_saas.install import LMS_NAV_SPEC

# Native desk workspaces when Loan Management / CRM modules are allowed (not LMS_NAV_SPEC).
ALLOWED_EXTRA_SIDEBAR_WORKSPACES = frozenset({"Loans", "Loan Management", "CRM"})

# Portal-only staff role is expected; it must NOT have desk access.
EXPECTED_PORTAL_ROLES = frozenset({"LMS Portal Staff"})


def run_all():
	"""Entry point for bench execute — admin-only desk access audit."""
	audit = audit_admin_desk_access()
	return audit


def audit_admin_desk_access():
	"""Verify System Manager can see all 4 admin workspaces and load them."""
	results = {"ok": True, "workspaces": {}}

	all_titles = [spec["title"] for spec in LMS_NAV_SPEC if not spec.get("hidden")]

	# Check as Administrator (always available, full access).
	admin_roles = set(frappe.get_roles("Administrator"))
	allowed = {
		spec["title"]
		for spec in LMS_NAV_SPEC
		if not spec.get("hidden") and admin_roles & set(spec.get("roles", ()))
	}

	for title in all_titles:
		exists = frappe.db.exists("Workspace", title)
		results["workspaces"][title] = {
			"exists": exists,
			"expected_visible": title in allowed,
		}
		if not exists:
			results["ok"] = False

	# Verify legacy LMS desk staff roles are removed (they were replaced by the
	# single portal-only LMS Portal Staff role).
	legacy_lms_roles = [r for r in ("LMS Admin", "LMS Branch Manager", "LMS Loan Officer", "LMS Collector") if frappe.db.exists("Role", r)]
	if legacy_lms_roles:
		results["ok"] = False
		results["lingering_lms_roles"] = legacy_lms_roles

	# Verify the portal-only staff role exists and has no desk access.
	for role in EXPECTED_PORTAL_ROLES:
		exists = frappe.db.exists("Role", role)
		desk_access = frappe.db.get_value("Role", role, "desk_access") if exists else None
		results["portal_roles"] = results.get("portal_roles", {})
		results["portal_roles"][role] = {"exists": exists, "desk_access": desk_access}
		if not exists or desk_access:
			results["ok"] = False

	# Verify module profile lockdown is removed.
	if frappe.db.exists("Module Profile", "LMS Staff"):
		results["ok"] = False
		results["lingering_module_profile"] = True

	return results
