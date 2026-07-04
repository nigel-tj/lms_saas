"""End-to-end tests for the LMS User Setup onboarding form.

Verifies that a single submitted LMS User Setup record creates every linked
record the selected persona needs (User + roles, Customer + Contact for
borrowers, Employee for staff) — the DRY, one-screen onboarding flow.
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestLMSUserSetup(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for name, doctype in self._cleanup:
			try:
				frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)
			except Exception:
				pass
		frappe.db.commit()

	def _track(self, name, doctype):
		if name:
			self._cleanup.append((name, doctype))

	def _make_setup(self, persona, email, **extra):
		# User.mobile_no is unique — derive a distinct number per email so parallel
		# tests don't collide on the mobile_no index.
		mobile = extra.pop("mobile_no", "0772" + str(abs(hash(email)) % 10000000).zfill(7))
		doc = frappe.get_doc(
			{
				"doctype": "LMS User Setup",
				"persona": persona,
				"first_name": "Test",
				"last_name": persona.replace(" ", ""),
				"email": email,
				"mobile_no": mobile,
				"send_welcome_email": 0,
				**extra,
			}
		)
		doc.insert(ignore_permissions=True)
		self._track(doc.name, "LMS User Setup")
		return doc

	def test_borrower_onboarding_creates_user_customer_contact(self):
		email = "test.borrower@example.com"
		doc = self._make_setup("Borrower", email, national_id="99-000000-A99")
		doc.submit()

		# User created with Customer role
		self.assertTrue(doc.created_user)
		self._track(doc.created_user, "User")
		roles = set(frappe.get_roles(doc.created_user))
		self.assertIn("Customer", roles)

		# Customer created with matching email
		self.assertTrue(doc.created_customer)
		self._track(doc.created_customer, "Customer")
		customer_email = frappe.db.get_value("Customer", doc.created_customer, "email_id")
		self.assertEqual(customer_email, email)

		# Contact linked to Customer so portal permission resolution works
		contact = frappe.db.get_value("Contact", {"email_id": email}, "name")
		self.assertTrue(contact)
		self._track(contact, "Contact")
		links = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Contact", "parent": contact, "link_doctype": "Customer"},
			pluck="link_name",
		)
		self.assertIn(doc.created_customer, links)

	def test_admin_onboarding_creates_user(self):
		email = "test.admin@example.com"
		doc = self._make_setup("Admin", email, gender="Male", date_of_birth="1990-01-01")
		doc.submit()

		# User created with System Manager + Desk User roles
		self.assertTrue(doc.created_user)
		self._track(doc.created_user, "User")
		roles = set(frappe.get_roles(doc.created_user))
		self.assertIn("System Manager", roles)
		self.assertIn("Desk User", roles)

	def test_duplicate_email_blocked(self):
		email = "test.dup@example.com"
		doc = self._make_setup("Borrower", email, national_id="99-111111-A11")
		doc.submit()
		self._track(doc.created_user, "User")
		self._track(doc.created_customer, "Customer")

		# Second setup with same email must fail validation on insert (validate runs
		# before submit, so the duplicate is caught early — before any records are
		# created on submit).
		dup = frappe.get_doc(
			{
				"doctype": "LMS User Setup",
				"persona": "Borrower",
				"first_name": "Dup",
				"last_name": "Test",
				"email": email,
				"mobile_no": "07729999999",
				"national_id": "99-222222-A22",
				"send_welcome_email": 0,
			}
		)
		self.assertRaises(frappe.ValidationError, dup.insert)

	def test_non_admin_cannot_create_admin(self):
		"""Only administrators may create staff/admin accounts; a Borrower cannot."""
		borrower_email = "scope.borrower@example.com"
		doc = self._make_setup("Borrower", borrower_email, national_id="99-444444-A44")
		doc.submit()
		self._track(doc.created_user, "User")
		self._track(doc.created_customer, "Customer")

		# Act as the newly created borrower and try to create an Admin. The borrower
		# has no System Manager role, so the scope guard in validate must block it.
		frappe.set_user(doc.created_user)
		admin_doc = frappe.get_doc(
			{
				"doctype": "LMS User Setup",
				"persona": "Admin",
				"first_name": "Sneaky",
				"last_name": "Admin",
				"email": "sneaky.admin@example.com",
				"mobile_no": "07728888888",
				"send_welcome_email": 0,
			}
		)
		# Bypass Frappe permission checks so we can test the application-level
		# scope guard in validate, not the role-based create permission.
		admin_doc.flags.ignore_permissions = True
		# The scope guard fires in validate, which runs on insert.
		self.assertRaises(frappe.ValidationError, admin_doc.insert)

	def test_borrower_requires_national_id(self):
		"""A Borrower without a National ID must be blocked at validate time."""
		doc = frappe.get_doc(
			{
				"doctype": "LMS User Setup",
				"persona": "Borrower",
				"first_name": "No",
				"last_name": "ID",
				"email": "test.noid@example.com",
				"mobile_no": "07720000001",
				"send_welcome_email": 0,
			}
		)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_borrower_seeds_compliance_with_national_id(self):
		"""Onboarding a Borrower with a National ID stores it on the Customer
		(custom_national_id_number) so it carries over to the LMS Borrower
		Compliance record when KYC is completed — no retyping needed."""
		email = "test.compliance@example.com"
		doc = self._make_setup("Borrower", email, national_id="99-333333-A33")
		doc.submit()
		self._track(doc.created_user, "User")
		self._track(doc.created_customer, "Customer")

		national_id = frappe.db.get_value(
			"Customer", doc.created_customer, "custom_national_id_number"
		)
		self.assertEqual(national_id, "99-333333-A33")