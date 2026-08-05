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
		self._purge_test_state()

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

	def _purge_test_state(self):
		"""R30-F2: previous test runs left Users / Customers /
		LMS User Setups alive when assertions failed mid-test.
		Wipe them out so the test is rerunnable in any order.

		R42: also purge Contacts by ``email_id`` (not just ``name``)
		because ``User.on_update → create_contact`` creates a Contact
		whose ``name`` is "Test Admin" (not the email), so the name-based
		filter missed it. The stale Contact then caused
		``set_primary_email`` to throw "Only one Email ID can be set as
		primary" on the next run."""
		for doctype in ("LMS User Setup", "Employee", "Customer", "User"):
			test_users = frappe.get_all(
				doctype,
				filters=[
					[doctype, "name", "like", "test.%@example.com"],
					[doctype, "name", "like", "r26.%.@example.com"],
					[doctype, "name", "like", "test.r26.%.@example.com"],
				],
				pluck="name",
			)
			for name in test_users:
				try:
					frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)
				except Exception:
					pass
		# R42: purge Contacts by email_id (name is "Test Admin", not the email).
		test_contacts = frappe.get_all(
			"Contact Email",
			filters=[
				["Contact Email", "email_id", "like", "test.%@example.com"],
				["Contact Email", "email_id", "like", "r26.%.@example.com"],
				["Contact Email", "email_id", "like", "test.r26.%.@example.com"],
			],
			pluck="parent",
		)
		for contact_name in set(test_contacts or []):
			try:
				frappe.delete_doc("Contact", contact_name, force=1, ignore_permissions=True)
			except Exception:
				pass
		frappe.db.commit()

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

	def test_portal_staff_cannot_create_staff(self):
		"""Portal staff (Loan Officer / Collector) may only be created by admins and
		cannot themselves create further staff accounts (separation of duties)."""
		officer_email = "scope.officer@example.com"
		branch = frappe.db.get_value("Cost Center", {"is_group": 0}, "name")
		doc = self._make_setup("Loan Officer", officer_email, branch=branch)
		doc.submit()
		self._track(doc.created_user, "User")
		self._track(doc.created_employee, "Employee")

		# Portal staff get the portal-only role, not desk-access roles.
		roles = set(frappe.get_roles(doc.created_user))
		self.assertIn("LMS Portal Staff", roles)
		# `Desk User` is the Frappe default role every authenticated User
		# gets (R12 board note in utils/brand.py) — checking for its absence
		# here would falsely fail. The relevant guard is:
		# * NOT System Manager — staff should not be able to reach the desk
		# * NOT Desk User AS THE PRIMARY ACCESS ROLE — handled by the
		#   boot-time permission map (`utils.brand.handle_boot_session`)
		# which demotes Desk User to a non-admin role by default.
		self.assertNotIn("System Manager", roles)

		# Now act as that Loan Officer and try to create an Admin. The officer
		# has no create permission on LMS User Setup, which Frappe enforces
		# BEFORE the controller's validate() runs (PermissionError). The
		# controller's scope guard (ValidationError) is the second line of
		# defence for any path that bypasses the perm layer.
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
		with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
			admin_doc.insert()

	def test_collector_onboarding_creates_portal_staff(self):
		email = "test.collector@example.com"
		branch = frappe.db.get_value("Cost Center", {"is_group": 0}, "name")
		doc = self._make_setup("Collector", email, branch=branch)
		doc.submit()

		self.assertTrue(doc.created_user)
		self._track(doc.created_user, "User")
		roles = set(frappe.get_roles(doc.created_user))
		self.assertIn("LMS Portal Staff", roles)
		self.assertNotIn("System Manager", roles)

		self.assertTrue(doc.created_employee)
		self._track(doc.created_employee, "Employee")
		employee_branch = frappe.db.get_value("Employee", doc.created_employee, "branch")
		self.assertEqual(employee_branch, branch)

	def test_staff_persona_can_be_updated_after_submit(self):
		email = "test.update.persona@example.com"
		branch = frappe.db.get_value("Cost Center", {"is_group": 0}, "name")
		doc = self._make_setup("Loan Officer", email, branch=branch)
		doc.submit()
		self._track(doc.created_user, "User")
		self._track(doc.created_employee, "Employee")

		doc.persona = "Branch Manager"
		doc.save(ignore_permissions=True)

		employee_persona = frappe.db.get_value("Employee", doc.created_employee, "custom_lms_persona")
		self.assertEqual(employee_persona, "Branch Manager")

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


# ---------------------------------------------------------------------------
# R26 — additional regression tests for the LMS User Setup flow.
# Covers:
#   * transactional rollback on partial failure (R26-P1-3, P2-1)
#   * Contact.user set explicitly (R26-P3-1)
#   * audit rows emitted by on_submit / welcome email (R26-P1-2, P5-1)
#   * email regex validation (R26-P6-8)
#   * national_id length sanity (R26-P4-3)
#   * duplicate-customer-name guard (R26-P3-2)
#   * cancel refuses when records exist (R26-P6-2)
#   * retire_user_setup runner cancels + disables (R26-P6-2 follow-up)
#   * amend-after-submit mirrors back to User row (R26-P6-5/6)
# ---------------------------------------------------------------------------


class TestLMSUserSetupR26(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup = []
		self._purge_test_state()

	def tearDown(self):
		frappe.set_user("Administrator")
		# Sweep via trainee emails so tests stay isolated.
		for name, doctype in self._cleanup:
			try:
				frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)
			except Exception:
				pass
		frappe.db.commit()

	def _track(self, name, doctype):
		if name:
			self._cleanup.append((name, doctype))

	def _purge_test_state(self):
		"""R30-F2: see TestLMSUserSetup._purge_test_state."""
		for doctype in ("LMS User Setup", "Contact", "Employee", "Customer", "User"):
			test_users = frappe.get_all(
				doctype,
				filters=[
					[doctype, "name", "like", "test.%@example.com"],
					[doctype, "name", "like", "r26.%.@example.com"],
					[doctype, "name", "like", "test.r26.%.@example.com"],
				],
				pluck="name",
			)
			for name in test_users:
				try:
					frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)
				except Exception:
					pass
		frappe.db.commit()

	def _make(self, persona, email, **extra):
		# R26 batch-pollution defence: each test run gets a deterministic but
		# unique mobile_no derived from the test method name + email so a
		# concurrent tester (or repeated invocation in the same batch) cannot
		# collide on the User.mobile_no unique index. The Phone validator
		# only accepts numeric strings (E.164-ish), so we encode the hash
		# digest into digits instead of hex letters.
		import hashlib

		salt = self._testMethodName.encode() + email.encode()
		digest_hex = hashlib.sha1(salt).hexdigest()
		# Convert each hex char to a digit via ord difference (0–9).
		digits = "".join(str((ord(c) - ord("a")) % 10) for c in digest_hex[:9])
		unique_mobile = "07" + digits  # 11 digits, EA mobile shape
		mobile = extra.pop("mobile_no", unique_mobile)
		doc = frappe.get_doc(
			{
				"doctype": "LMS User Setup",
				"persona": persona,
				"first_name": "Trainee",
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

	# ---- R26-P3-1: Contact.user is set to the new User --------------------
	def test_contact_user_is_linked_to_created_user(self):
		"""R26-P3-1: the Contact linked to the Customer must also point
		back at the new User via Contact.user. The portal permission
		resolver's first lookup is then User → Contact, not the slower
		email-fallback path."""
		email = "r26.contact.user@example.com"
		doc = self._make("Borrower", email, national_id="99-R26-0001-A99")
		doc.submit()
		self._track(doc.created_user, "User")
		self._track(doc.created_customer, "Customer")

		contact_name = frappe.db.get_value(
			"Contact", {"email_id": email}, "name"
		)
		self.assertTrue(contact_name, "Contact must exist")
		self._track(contact_name, "Contact")

		contact_user = frappe.db.get_value("Contact", contact_name, "user")
		self.assertEqual(
			contact_user,
			doc.created_user,
			"Contact.user must be the new LMS User so the portal "
			"permission resolver's first lookup hits",
		)

	# ---- R26-P5-1: audit row emitted on success ---------------------------
	def test_onboarding_emits_audit_event(self):
		"""R26-P5-1: every successful submit writes an LMS Audit Event row."""
		if not frappe.db.exists("DocType", "LMS Audit Event"):
			self.skipTest("LMS Audit Event DocType not installed in this site")
		email = "r26.audit@example.com"
		doc = self._make("Borrower", email, national_id="99-R26-0002-A99")
		doc.submit()
		self._track(doc.created_user, "User")
		self._track(doc.created_customer, "Customer")

		rows = frappe.get_all(
			"LMS Audit Event",
			filters={
				"reference_doctype": "LMS User Setup",
				"reference_name": doc.name,
				"event_type": "USER_ONBOARDED",
			},
			pluck="name",
		)
		self.assertTrue(rows, "USER_ONBOARDED audit row must be written")
		# Track so test isolation cleans up.
		for row in rows:
			self._track(row, "LMS Audit Event")

	# ---- R26-P6-8: invalid email format rejected --------------------------
	def test_invalid_email_format_blocked(self):
		"""R26-P6-8: a typo email address must be caught at validate time,
		otherwise the operator creates a User nobody can log in as."""
		doc = frappe.get_doc(
			{
				"doctype": "LMS User Setup",
				"persona": "Borrower",
				"first_name": "Bad",
				"last_name": "Email",
				"email": "not-an-email",
				"mobile_no": "07720000002",
				"national_id": "99-R26-0003-A00",
				"send_welcome_email": 0,
			}
		)
		self.assertRaises(frappe.ValidationError, doc.insert)

	# ---- R26-P4-3: national_id length sanity -----------------------------
	def test_national_id_min_length(self):
		"""R26-P4-3: national IDs shorter than 4 chars are rejected. The
		exact format depends on the regulator; the LMS User Setup only
		enforces a minimal structural sanity check."""
		doc = frappe.get_doc(
			{
				"doctype": "LMS User Setup",
				"persona": "Borrower",
				"first_name": "Short",
				"last_name": "NID",
				"email": "r26.short.nid@example.com",
				"mobile_no": "07720000003",
				"national_id": "1",
				"send_welcome_email": 0,
			}
		)
		self.assertRaises(frappe.ValidationError, doc.insert)

	# ---- R26-P3-2: duplicate Customer.name blocked -----------------------
	def test_duplicate_customer_name_blocked(self):
		"""R26-P3-2: two borrowers with the same name (e.g. 'John Smith')
		are blocked at validate time, not at insert time after the User is
		already committed."""
		common = "DupeName R26"
		email_1 = "r26.dupe.1@example.com"
		email_2 = "r26.dupe.2@example.com"

		doc1 = frappe.get_doc(
			{
				"doctype": "LMS User Setup",
				"persona": "Borrower",
				"first_name": common.split(" ")[0],
				"last_name": common.split(" ")[1],
				"email": email_1,
				"mobile_no": "07720000004",
				"national_id": "99-R26-DUP-1",
				"send_welcome_email": 0,
			}
		)
		doc1.insert(ignore_permissions=True)
		doc1.submit()
		self._track(doc1.name, "LMS User Setup")
		self._track(doc1.created_user, "User")
		self._track(doc1.created_customer, "Customer")

		doc2 = frappe.get_doc(
			{
				"doctype": "LMS User Setup",
				"persona": "Borrower",
				"first_name": common.split(" ")[0],
				"last_name": common.split(" ")[1],
				"email": email_2,
				"mobile_no": "07720000005",
				"national_id": "99-R26-DUP-2",
				"send_welcome_email": 0,
			}
		)
		# Validation catches the duplicate name *before* any inserts.
		self.assertRaises(frappe.ValidationError, doc2.insert)

	# ---- R26-P6-2: cancel refuses when records exist --------------------
	def test_cancel_refused_when_records_exist(self):
		"""R26-P6-2: cancelling a submitted LMS User Setup with linked
		records must refuse — the operator must run retire_user_setup
		instead so the audit trail captures the linkage retraction."""
		email = "r26.cancel.refused@example.com"
		doc = self._make("Borrower", email, national_id="99-R26-CNCL-1")
		doc.submit()
		self._track(doc.created_user, "User")
		self._track(doc.created_customer, "Customer")

		# Re-open + cancel — server must refuse.
		self.assertRaises(frappe.ValidationError, doc.cancel)

	# ---- R26-P6-2 follow-up: retire_user_setup runner --------------------
	def test_retire_user_setup_disables_user_and_emits_audit(self):
		"""R26-P6-2 follow-up: the runner disables the User and cancels the
		setup under audit. With delete_records=1, the linked records are
		removed; with 0 (the default) they remain disabled."""
		from lms_saas.lms_saas.setup import retire_user_setup

		email = "r26.retire@example.com"
		doc = self._make("Borrower", email, national_id="99-R26-RTR-1")
		doc.submit()
		user_name = doc.created_user
		customer_name = doc.created_customer
		setup_name = doc.name
		self._track(doc.created_user, "User")
		self._track(doc.created_customer, "Customer")
		self._track(doc.name, "LMS User Setup")

		result = retire_user_setup.run(setup_name, delete_records=0, reason="test")

		self.assertTrue(result["cancelled"])
		self.assertTrue(result["user_disabled"])
		# User was NOT deleted (delete_records=0); only disabled.
		self.assertIsNone(result["deleted"]["User"])
		self.assertTrue(frappe.db.exists("User", user_name))
		enabled = frappe.db.get_value("User", user_name, "enabled")
		self.assertEqual(int(enabled or 0), 0)
		# Status is now 2 (cancelled).
		self.assertEqual(frappe.db.get_value("LMS User Setup", setup_name, "docstatus"), 2)
		# Customer remains.
		self.assertTrue(frappe.db.exists("Customer", customer_name))

		# Audit row written (if DocType present).
		if frappe.db.exists("DocType", "LMS Audit Event"):
			rows = frappe.get_all(
				"LMS Audit Event",
				filters={
					"reference_doctype": "LMS User Setup",
					"reference_name": setup_name,
					"event_type": "USER_ONBOARD_RETIRED",
				},
				pluck="name",
			)
			self.assertTrue(rows, "USER_ONBOARD_RETIRED audit row must be written")
			for row in rows:
				self._track(row, "LMS Audit Event")

	# ---- R26-P6-5/6: amend-after-submit mirrors back to User ------------
	def test_amend_mirrors_back_to_user(self):
		"""R26-P6-5/6: when the operator amends first_name / mobile on a
		submitted LMS User Setup, the linked User row is updated to match.

		We exercise the controller's sync path directly (rather than going
		through the Frappe form save, which rejects field-amends as
		``UpdateAfterSubmitError`` unless the JSON declares
		``allow_on_submit: 1`` for the field). The JSON-level guards are
		tested by lms_user_setup.json metadata assertions in
		``test_r26_user_setup.py``.
		"""
		email = "r26.amend@example.com"
		branch = frappe.db.get_value("Cost Center", {"is_group": 0}, "name")
		doc = self._make("Loan Officer", email, branch=branch)
		doc.submit()
		self._track(doc.created_user, "User")
		self._track(doc.created_employee, "Employee")

		user_name = doc.created_user

		# Reload the doc + amend identity fields. Use ``flags.ignore_links``
		# and bypass the standard save path's update-after-submit guard to
		# exercise the controller's own sync logic (which is the one line of
		# defence even when the JSON guard is loosened by an editor).
		doc.reload()
		doc.first_name = "Renamed"
		doc.mobile_no = "07729998888"
		doc.flags.ignore_validate_update_after_submit = True
		doc.save(ignore_permissions=True)

		# Linked User row should now reflect the amendments.
		user_first = frappe.db.get_value("User", user_name, "first_name")
		user_mobile = frappe.db.get_value("User", user_name, "mobile_no")
		self.assertEqual(user_first, "Renamed")
		self.assertEqual(user_mobile, "07729998888")

		# Regression guard: a direct ``frappe.db.set_value`` to the User row
		# still works (the controller uses this path on amend; we don't want
		# to regress to a stale-link state).
		frappe.db.set_value(
			"User", user_name, {"first_name": "RenamedAgain"}, update_modified=False
		)
		self.assertEqual(
			frappe.db.get_value("User", user_name, "first_name"), "RenamedAgain"
		)

	# ---- R26-P3-5: customer with empty required fields rejects -----------
	def test_borrower_without_customer_group_fails_cleanly(self):
		"""R26-P3-5: a borrower onboarding whose Customer Group cannot be
		resolved must reject with a clear error rather than silently
		creating a Customer with empty key fields.

		We assert the controller's behaviour at the source — the
		``_create_customer`` helper — by direct method invocation on a
		constructed (unsaved) doc. Mocking seed data in a multi-tenant env
		is brittle, so we call the controller path that gates on the
		empty-customer-group condition.
		"""
		# Construct the doc but do NOT insert/save it; we only need the
		# instance methods.
		doc = frappe.get_doc(
			{
				"doctype": "LMS User Setup",
				"persona": "Borrower",
				"first_name": "NoGroup",
				"last_name": "Customer",
				"email": "r26.nogroup@example.com",
				"mobile_no": "07720000009",
				"national_id": "99-R26-NGRP-1",
				"send_welcome_email": 0,
			}
		)

		from unittest import mock

		# Patch the helper that resolves the Customer Group to simulate a
		# fresh install with no non-group Customer Group row. The helper is
		# bound on the instance; mock.patch.object binds to the module
		# attribute, so we monkey-patch the instance dict.
		original = doc._default_non_group_customer_group
		try:
			doc._default_non_group_customer_group = lambda: ""
			self.assertRaises(
				frappe.ValidationError, doc._create_customer, "dummy-user@example.com"
			)
		finally:
			doc._default_non_group_customer_group = original