"""Smoke tests for the live-site repair workflow."""

import frappe
from frappe.tests.utils import FrappeTestCase

from lms_saas.setup.live_repair import _repair_legacy_user_roles, LEGACY_LMS_ROLES


class TestLiveRepair(FrappeTestCase):
	def test_repair_removes_retired_role_rows_from_users(self):
		user_email = "repair-user@example.com"
		if not frappe.db.exists("User", user_email):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": user_email,
					"first_name": "Repair",
					"last_name": "User",
					"send_welcome_email": 0,
				}
			)
			user.insert(ignore_permissions=True)
		else:
			user = frappe.get_doc("User", user_email)

		legacy_role = LEGACY_LMS_ROLES[0]
		if not frappe.db.exists("Role", legacy_role):
			frappe.get_doc({"doctype": "Role", "role_name": legacy_role}).insert(ignore_permissions=True)

		if not any(row.role == legacy_role for row in user.get("roles") or []):
			user.append("roles", {"role": legacy_role})
			user.save(ignore_permissions=True)

		frappe.db.commit()
		result = _repair_legacy_user_roles()
		frappe.db.commit()

		self.assertGreaterEqual(result["removed_rows"], 1)
		user_after = frappe.get_doc("User", user_email)
		self.assertFalse(any(row.role == legacy_role for row in user_after.get("roles") or []))
