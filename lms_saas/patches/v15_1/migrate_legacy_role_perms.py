"""Phase 4.4 — retire legacy LMS staff role names on existing installs.

Before Phase 4, the codebase carried four legacy role names (LMS Admin,
LMS Branch Manager, LMS Loan Officer, LMS Collector). The new design
uses a single ``LMS Portal Staff`` role plus ``Employee.custom_lms_persona``
to differentiate Loan Officer / Collector / Branch Manager.

This patch:

1. Rewrites every DocType ``permissions`` row that referenced a legacy
   role so it points at ``LMS Portal Staff`` (or ``System Manager`` for
   the Admin-only one).
2. Rewrites every Report ``roles`` row the same way.
3. Strips the legacy role from each affected ``User`` / ``Has Role`` row.
4. Deletes the legacy ``Role`` records and the matching ``Custom DocPerm`` rows.

The patch is idempotent — safe to re-run on every migrate.
"""

from __future__ import annotations

import frappe

LEGACY_ROLES = ("LMS Admin", "LMS Branch Manager", "LMS Loan Officer", "LMS Collector")
REPLACEMENT_ROLE = "LMS Portal Staff"

# Admin-only legacy role gets rewritten to System Manager; portal staff roles
# get rewritten to LMS Portal Staff (the persona is the differentiator now).
_LEGACY_TO_NEW = {
	"LMS Admin": "System Manager",
	"LMS Branch Manager": REPLACEMENT_ROLE,
	"LMS Loan Officer": REPLACEMENT_ROLE,
	"LMS Collector": REPLACEMENT_ROLE,
}


def _rewrite_doctype_perms():
	"""DocPerm rows (Custom DocPerm + standard DocPerm) — swap legacy role."""
	updated = 0
	for legacy in LEGACY_ROLES:
		# Custom DocPerm rows live in tabCustom DocPerm keyed by parent + role.
		for name in frappe.get_all(
			"Custom DocPerm", filters={"role": legacy}, pluck="name"
		):
			frappe.db.set_value("Custom DocPerm", name, "role", _LEGACY_TO_NEW[legacy])
			updated += 1
		# Standard DocPerm rows on the Lending / LMS modules.
		for name in frappe.get_all(
			"DocPerm", filters={"role": legacy}, pluck="name"
		):
			frappe.db.set_value("DocPerm", name, "role", _LEGACY_TO_NEW[legacy])
			updated += 1
	return updated


def _rewrite_report_roles():
	"""Has Role rows on Report — swap legacy role to LMS Portal Staff."""
	updated = 0
	for legacy in LEGACY_ROLES:
		rows = frappe.get_all(
			"Has Role",
			filters={"role": legacy, "parenttype": "Report"},
			pluck="name",
		)
		for name in rows:
			# Has Role is a child table — we replace the row rather than mutate
			# the column, because Frappe's child-table contract requires a delete
			# + insert to keep `idx` consistent.
			row = frappe.get_doc("Has Role", name)
			new_role = _LEGACY_TO_NEW[legacy]
			exists = frappe.db.exists(
				"Has Role",
				{
					"parent": row.parent,
					"parenttype": "Report",
					"parentfield": "roles",
					"role": new_role,
				},
			)
			if exists:
				row.delete()
			else:
				frappe.db.set_value("Has Role", name, "role", new_role)
			updated += 1
	return updated


def _strip_user_role_refs():
	"""Strip legacy role refs from User.role_profile + Has Role on User.

	``User.role`` is a virtual / read-only field populated from Has Role
	(child table on User). Deleting the matching child rows is enough.
	"""
	stripped = 0
	for legacy in LEGACY_ROLES:
		for name in frappe.get_all(
			"Has Role", filters={"role": legacy, "parenttype": "User"}, pluck="name"
		):
			frappe.delete_doc("Has Role", name, ignore_permissions=True, force=True)
			stripped += 1
	return stripped


def _delete_legacy_roles():
	"""Delete Custom DocPerm rows then the Role records themselves."""
	deleted = 0
	for role in LEGACY_ROLES:
		# Custom DocPerm rows for this role — purge before deleting the Role.
		frappe.db.delete("Custom DocPerm", {"role": role})
		if frappe.db.exists("Role", role):
			frappe.delete_doc("Role", role, ignore_permissions=True, force=True)
			deleted += 1
	return deleted


def execute():
	doctype_perms = _rewrite_doctype_perms()
	report_roles = _rewrite_report_roles()
	user_role_refs = _strip_user_role_refs()
	deleted = _delete_legacy_roles()
	frappe.db.commit()
	return {
		"doctype_perms_rewritten": doctype_perms,
		"report_roles_rewritten": report_roles,
		"user_role_refs_stripped": user_role_refs,
		"roles_deleted": deleted,
	}
