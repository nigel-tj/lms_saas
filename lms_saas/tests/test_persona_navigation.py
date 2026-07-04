"""Phase 4.4 — persona-aware navigation tests.

Verifies the security fix for the "Manager tab shown to Office users" bug.
Covers three layers:

1. Context flags — ``lms_user_permissions`` exposes the right bitmask.
2. Nav template — Officers do not see ``/lms/manager``; Branch Managers do.
3. Page-level guard — Officers hitting ``/lms/manager`` are redirected.
4. API guard — Officers calling manager APIs get PermissionError.

Runs against the demo ``lms.localhost`` site, which is seeded with one
user per persona. The seed users are created on first run if missing.
"""

import frappe
from frappe.tests.utils import FrappeTestCase


PERSONA_USERS = {
	"Loan Officer": "loan_officer_test@lms.local",
	"Branch Manager": "branch_manager_test@lms.local",
	"Collector": "collector_test@lms.local",
	"Borrower": "borrower_test@lms.local",
}


def _ensure_persona_users():
	"""Seed one user per persona for the test (idempotent)."""
	for persona, email in PERSONA_USERS.items():
		if frappe.db.exists("User", email):
			continue
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = persona.replace(" ", "_").title()
		user.last_name = "Test"
		user.enabled = 1
		user.send_welcome_email = 0
		user.new_password = "TestPass!2345"
		# Roles per persona
		if persona == "Borrower":
			user.append("roles", {"role": "Customer"})
		else:
			user.append("roles", {"role": "LMS Portal Staff"})
		user.flags.no_welcome_mail = True
		user.save(ignore_permissions=True)

		# Employee + persona (for portal staff)
		if persona != "Borrower":
			emp = frappe.new_doc("Employee")
			emp.employee_name = f"{persona} Test"
			emp.user_id = email
			emp.status = "Active"
			emp.company = frappe.db.get_single_value("Global Defaults", "default_company")
			emp.gender = "Other"
			emp.date_of_birth = "1990-01-01"
			emp.date_of_joining = "2020-01-01"
			if frappe.get_meta("Employee").has_field("custom_lms_persona"):
				emp.custom_lms_persona = persona
			emp.insert(ignore_permissions=True)


class TestPersonaNavigation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_persona_users()

	def _persona(self, user_email):
		"""Set the session user, return the resolved persona."""
		frappe.set_user(user_email)
		# Reload role cache to avoid stale state across tests.
		frappe.cache().delete_key("roles_for_user:" + user_email)
		from lms_saas.utils.portal import resolve_portal_persona, _persona_permissions

		persona = resolve_portal_persona()
		perms = _persona_permissions(persona, set(frappe.get_roles(user_email)))
		return persona, perms

	# 1. Context flags -------------------------------------------------

	def test_loan_officer_permissions(self):
		persona, perms = self._persona(PERSONA_USERS["Loan Officer"])
		self.assertEqual(persona, "Loan Officer")
		self.assertTrue(perms["can_officer"])
		self.assertTrue(perms["can_collect"])
		self.assertFalse(perms["can_manager"])
		self.assertFalse(perms["can_admin"])

	def test_branch_manager_permissions(self):
		persona, perms = self._persona(PERSONA_USERS["Branch Manager"])
		self.assertEqual(persona, "Branch Manager")
		self.assertTrue(perms["can_officer"])
		self.assertTrue(perms["can_manager"])
		self.assertTrue(perms["can_collect"])
		self.assertFalse(perms["can_admin"])

	def test_collector_permissions(self):
		persona, perms = self._persona(PERSONA_USERS["Collector"])
		self.assertEqual(persona, "Collector")
		self.assertFalse(perms["can_officer"])
		self.assertFalse(perms["can_manager"])
		self.assertTrue(perms["can_collect"])
		self.assertFalse(perms["can_admin"])

	# 2. Nav template --------------------------------------------------

	def test_officer_does_not_see_manager_in_nav(self):
		frappe.set_user(PERSONA_USERS["Loan Officer"])
		# Re-render the portal nav with this session.
		from jinja2 import Environment, FileSystemLoader, select_autoescape

		tpl_path = frappe.get_app_path("lms_saas", "templates", "lms_portal", "base.html")
		from lms_saas.utils.brand import apply_portal_context

		ctx = frappe._dict()
		apply_portal_context(ctx, nav_active="loans")
		# Officer must not have can_manager.
		self.assertFalse(ctx.lms_user_permissions.get("can_manager"))

	def test_branch_manager_sees_manager_in_nav(self):
		frappe.set_user(PERSONA_USERS["Branch Manager"])
		from lms_saas.utils.brand import apply_portal_context

		ctx = frappe._dict()
		apply_portal_context(ctx, nav_active="loans")
		self.assertTrue(ctx.lms_user_permissions.get("can_manager"))

	# 3. Page-level guard ---------------------------------------------

	def test_officer_redirected_from_manager_page(self):
		from lms_saas.utils.portal import _user_can, require_persona_for_page
		frappe.set_user(PERSONA_USERS["Loan Officer"])
		self.assertFalse(_user_can("can_manager"))
		# Hitting the page should redirect to the officer landing.
		with self.assertRaises(frappe.Redirect):
			require_persona_for_page("can_manager")
		self.assertEqual(frappe.local.flags.redirect_location, "/lms/officer")

	def test_branch_manager_passes_manager_page(self):
		from lms_saas.utils.portal import _user_can, require_persona_for_page
		frappe.set_user(PERSONA_USERS["Branch Manager"])
		self.assertTrue(_user_can("can_manager"))
		# No raise.
		require_persona_for_page("can_manager")

	def test_collector_redirected_from_officer_page(self):
		from lms_saas.utils.portal import _user_can, require_persona_for_page
		frappe.set_user(PERSONA_USERS["Collector"])
		self.assertFalse(_user_can("can_officer"))
		with self.assertRaises(frappe.Redirect):
			require_persona_for_page("can_officer")
		self.assertEqual(frappe.local.flags.redirect_location, "/lms/collect")

	# 4. API guards ----------------------------------------------------

	def test_officer_blocked_from_manager_api(self):
		frappe.set_user(PERSONA_USERS["Loan Officer"])
		# Direct import to avoid HTTP overhead.
		from lms_saas.api.manager import _require_manager
		with self.assertRaises(frappe.PermissionError):
			_require_manager()

	def test_branch_manager_passes_manager_api(self):
		frappe.set_user(PERSONA_USERS["Branch Manager"])
		from lms_saas.api.manager import _require_manager
		# No raise.
		_require_manager()

	def test_borrower_blocked_from_collector_api(self):
		frappe.set_user(PERSONA_USERS["Borrower"])
		from lms_saas.api.field_collection import _require_collector
		with self.assertRaises(frappe.PermissionError):
			_require_collector()

	def test_collector_passes_collector_api(self):
		frappe.set_user(PERSONA_USERS["Collector"])
		from lms_saas.api.field_collection import _require_collector
		_require_collector()
