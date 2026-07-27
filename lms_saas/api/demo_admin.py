"""LMS demo / sandbox admin helpers.

R18-1: exposes ``reset_demo_data`` so the LMS Admin help page can offer a
"Reset demo data" button. Restricted to System Manager / Administrator
because it wipes records.
"""

from __future__ import annotations

import frappe


@frappe.whitelist()
def reset_demo_data() -> dict:
	"""Wipe demo seed data and re-seed the canonical demo.

	Returns a small summary so the help-page toast can show what happened.
	Restricted to System Manager / Administrator.
	"""
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles.intersection({"System Manager", "Administrator"}):
		frappe.throw("Only System Managers can reset demo data.", frappe.PermissionError)

	from lms_saas.scripts.reset_demo_data import run as _run

	return _run()


@frappe.whitelist()
def sandbox_status() -> dict:
	"""Tell the UI whether the site is in sandbox mode (for the banner)."""
	from lms_saas.api.compliance_config import (
		is_sandbox_mode,
		is_production_mode,
		has_operator_profile,
	)

	return {
		"sandbox_mode": is_sandbox_mode(),
		"production_mode": is_production_mode(),
		"has_operator_profile": has_operator_profile(),
	}
