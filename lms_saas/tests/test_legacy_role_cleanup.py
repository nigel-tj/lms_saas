"""Phase 4.4 — legacy role cleanup test.

After the migrate patch runs (``patches/v15_1/migrate_legacy_role_perms``),
none of the legacy role names — LMS Admin, LMS Branch Manager, LMS Loan
Officer, LMS Collector — should remain on DocType perm rows, Report role
rows, or as live Role records.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from lms_saas.patches.v15_1.migrate_legacy_role_perms import (
	LEGACY_ROLES,
	execute as run_migration,
)


LEGACY_ROLE_SET = frozenset(LEGACY_ROLES)


class TestLegacyRoleCleanup(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Recreate the legacy roles + perm rows the migration should sweep.
		# We do this in setUpClass so each test method sees a fresh state.
		cls._seed_legacy_roles()

	@classmethod
	def _seed_legacy_roles(cls):
		"""Re-create a few legacy roles + perm rows so the migration has work."""
		# Make sure the LMS Portal Staff role exists (needed as the replacement).
		if not frappe.db.exists("Role", "LMS Portal Staff"):
			frappe.get_doc({"doctype": "Role", "role_name": "LMS Portal Staff"}).insert(
				ignore_permissions=True
			)
		for role in LEGACY_ROLES:
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role}).insert(
					ignore_permissions=True
				)
		# A Custom DocPerm row referencing one of the legacy roles.
		dt = "Customer"  # standard DocType, exists in every site
		for role in LEGACY_ROLES:
			if not frappe.db.exists("Custom DocPerm", {"parent": dt, "role": role}):
				frappe.get_doc(
					{
						"doctype": "Custom DocPerm",
						"parent": dt,
						"parenttype": "DocType",
						"parentfield": "permissions",
						"role": role,
						"read": 1,
					}
				).insert(ignore_permissions=True)
		frappe.db.commit()

	def test_legacy_roles_deleted_after_migration(self):
		# Pre: legacy roles exist.
		pre_existing = [r for r in LEGACY_ROLES if frappe.db.exists("Role", r)]
		self.assertTrue(pre_existing, "test setup: at least one legacy role should exist")

		# Run the migration.
		result = run_migration()
		frappe.db.commit()

		# Post: every legacy Role is gone.
		for role in LEGACY_ROLES:
			self.assertFalse(
				frappe.db.exists("Role", role),
				f"Legacy role {role} should be deleted by the migration",
			)
		self.assertGreaterEqual(result["roles_deleted"], 1)

	def test_legacy_perm_rows_rewritten(self):
		# Run again (idempotent).
		run_migration()
		frappe.db.commit()
		# No Custom DocPerm or DocPerm row should still reference a legacy role.
		for table in ("Custom DocPerm", "DocPerm"):
			rows = frappe.get_all(table, filters={"role": ("in", list(LEGACY_ROLES))}, pluck="role")
			self.assertFalse(rows, f"{table} still has legacy-role rows: {rows}")

	def test_legacy_report_role_rows_rewritten(self):
		# Pick one report (use the test data if present, else the seed).
		report_name = "Portfolio At Risk"
		if not frappe.db.exists("Report", report_name):
			self.skipTest("Report 'Portfolio At Risk' not present on this site")
		rows = frappe.get_all(
			"Has Role",
			filters={
				"parent": report_name,
				"parenttype": "Report",
				"role": ("in", list(LEGACY_ROLES)),
			},
			pluck="role",
		)
		self.assertFalse(rows, f"Report {report_name} still has legacy-role rows: {rows}")

	def test_legacy_user_role_refs_stripped(self):
		# No User-side Has Role should reference a legacy role name.
		rows = frappe.get_all(
			"Has Role",
			filters={"role": ("in", list(LEGACY_ROLES)), "parenttype": "User"},
			pluck="role",
		)
		self.assertFalse(rows, f"Users still have legacy-role rows: {rows}")
