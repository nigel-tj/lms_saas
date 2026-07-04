"""LMS User Setup — single-screen onboarding for borrowers and staff.

A submittable DocType that hides Frappe internals (User / Customer / Contact /
Employee / roles / module profiles) behind one normal-looking form. On submit,
the server creates every linked record the selected persona needs, in one
transaction, so the end user never touches the raw Frappe admin screens.

Persona → roles/records mapping lives in ``lms_saas.install.PERSONA_CONFIG``
(single source of truth, DRY — add a persona by adding one row there).
"""

import frappe
from frappe import _
from frappe.model.document import Document

from lms_saas.install import PERSONA_CONFIG


class LMSUserSetup(Document):
	def validate(self):
		self._validate_persona()
		self._validate_email_unique()
		self._validate_branch_for_staff()
		self._validate_national_id_for_borrower()
		self._validate_officer_scope()
		self._validate_staff_branch()

	def on_update_after_submit(self):
		self._sync_after_submit()

	def on_submit(self):
		config = PERSONA_CONFIG.get(self.persona)
		if not config:
			frappe.throw(_("Unknown persona: {0}").format(self.persona))

		user = self._create_user(config)
		self.created_user = user

		if config.get("create_customer"):
			customer = self._create_customer(user)
			self.created_customer = customer
			self._link_contact(user, customer)

		if config.get("create_employee"):
			employee = self._create_employee(user)
			self.created_employee = employee
			# Tag the Employee with the selected branch so the collector PWA can
			# resolve branch scope from the user record.
			if self.branch:
				frappe.db.set_value("Employee", employee, "branch", self.branch)
			# Tag the Employee with the persona so boot.py can route to the
			# correct portal page (officer / manager / collector).
			if frappe.get_meta("Employee").has_field("custom_lms_persona"):
				frappe.db.set_value("Employee", employee, "custom_lms_persona", self.persona)

		self._send_welcome_if_requested(user)
		self.db_update()

	# ------------------------------------------------------------------ helpers
	def _validate_persona(self):
		if self.persona not in PERSONA_CONFIG:
			frappe.throw(_("Invalid persona {0}").format(self.persona))

	def _validate_email_unique(self):
		existing_user = frappe.db.get_value("User", self.email, "name")
		if existing_user and existing_user != (self.created_user or existing_user):
			frappe.throw(_("A User with email {0} already exists").format(self.email))
		if self.persona == "Borrower":
			existing_customer = frappe.db.get_value("Customer", {"email_id": self.email}, "name")
			if existing_customer and existing_customer != (self.created_customer or existing_customer):
				frappe.throw(_("A Customer with email {0} already exists").format(self.email))

	def _validate_branch_for_staff(self):
		"""Admins do not need a branch; portal staff personas do."""
		config = PERSONA_CONFIG.get(self.persona) or {}
		if self.persona == "Admin":
			return
		if config.get("create_employee") and not self.branch:
			frappe.throw(_("Branch is required for staff personas"))

	def _validate_national_id_for_borrower(self):
		"""Borrowers need a National ID for KYC. Staff personas don't."""
		if self.persona == "Borrower" and not (self.national_id or "").strip():
			frappe.throw(_("National ID is required for the Borrower persona (used for KYC)"))

	def _validate_officer_scope(self):
		"""Only admins (System Manager) may onboard staff; anyone can onboard borrowers."""
		roles = set(frappe.get_roles(frappe.session.user))
		if self.persona != "Borrower" and "System Manager" not in roles and "Administrator" not in roles:
			frappe.throw(_("Only administrators may create staff accounts"))

	def _validate_staff_branch(self):
		"""Loan Officers and Collectors must be assigned to a branch."""
		from lms_saas.install import PERSONA_CONFIG

		config = PERSONA_CONFIG.get(self.persona) or {}
		if config.get("create_employee") and not self.branch:
			frappe.throw(_("Branch is required for the {0} persona").format(self.persona))

	def _persona_kind(self, persona=None):
		persona = persona or self.persona
		config = PERSONA_CONFIG.get(persona) or {}
		if config.get("create_employee"):
			return "staff"
		if config.get("create_customer"):
			return "borrower"
		return "admin"

	def _sync_after_submit(self):
		previous = None
		if hasattr(self, "get_doc_before_save"):
			previous = self.get_doc_before_save()
		old_persona = getattr(previous, "persona", None) if previous else None
		old_kind = self._persona_kind(old_persona)
		new_kind = self._persona_kind()

		if old_kind != new_kind:
			frappe.throw(_("Changing a submitted setup between borrower/admin and staff personas is not supported. Create a new setup record instead."))

		if new_kind != "staff":
			return

		if not self.created_employee:
			frappe.throw(_("This setup is missing its linked Employee record. Re-run onboarding or create a new setup."))

		updates = {
			"branch": self.branch or None,
			"department": self.department or None,
			"gender": self.gender or None,
			"date_of_birth": self.date_of_birth or None,
		}
		if frappe.get_meta("Employee").has_field("custom_lms_persona"):
			updates["custom_lms_persona"] = self.persona
		frappe.db.set_value("Employee", self.created_employee, updates, update_modified=True)

	def _full_name(self):
		parts = [p for p in (self.first_name, self.last_name) if p]
		return " ".join(parts) or self.email

	def _create_user(self, config):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": self.email,
				"first_name": self.first_name,
				"last_name": self.last_name or "",
				"mobile_no": self.mobile_no or "",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		)
		for role in config.get("roles", []):
			if frappe.db.exists("Role", role):
				user.append("roles", {"role": role})
		user.flags.ignore_permissions = True
		user.insert()
		return user.name

	def _create_customer(self, user):
		customer_group = self._default_non_group_customer_group()
		territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or ""
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": self._full_name(),
				"email_id": self.email,
				"mobile_no": self.mobile_no or "",
				"customer_group": customer_group or "",
				"territory": territory,
				"custom_lms_branch": self.branch or "",
				"custom_national_id_number": self.national_id or "",
			}
		)
		customer.flags.ignore_permissions = True
		customer.insert()
		return customer.name

	def _default_non_group_customer_group(self):
		"""Return the first non-group Customer Group (ERPNext rejects group-type groups)."""
		return frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or frappe.db.get_single_value("Selling Settings", "customer_group") or ""

	def _link_contact(self, user, customer):
		"""Create a Contact linked to the Customer so portal permission resolution
		(lms_saas.permissions._portal_customer) can walk User → Contact → Customer."""
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": self.first_name,
				"last_name": self.last_name or "",
				"email_ids": [{"email_id": self.email}],
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		)
		contact.flags.ignore_permissions = True
		contact.insert()

	def _create_employee(self, user):
		company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value("Company", {}, "name")
		if not company:
			frappe.throw(_("No default Company found — set one in Global Defaults"))
		from frappe.utils import today

		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": self.first_name,
				"last_name": self.last_name or "",
				"user_id": user,
				"company": company,
				"status": "Active",
				"gender": self.gender or "Male",
				"date_of_birth": self.date_of_birth or "1990-01-01",
				"date_of_joining": today(),
				"department": self.department or "",
			}
		)
		employee.flags.ignore_permissions = True
		employee.insert()
		return employee.name

	def _send_welcome_if_requested(self, user):
		if not self.send_welcome_email:
			return
		try:
			from frappe.utils import get_url

			from lms_saas.utils.email import send_branded_email

			# Generate a password-reset link so the new user can set their
			# initial password from the email itself (Frappe's reset_key flow).
			reset_url = get_url(f"/update-password?email={frappe.utils.quote(self.email)}")

			send_branded_email(
				recipients=[self.email],
				subject=_("Welcome to {0}").format(
					frappe.db.get_single_value("Global Defaults", "default_company") or "Kesari"
				),
				body_key="welcome",
				context={
					"customer_name": self._full_name(),
					"reset_password_url": reset_url,
				},
				reference_doctype=self.doctype,
				reference_name=self.name,
			)
		except Exception:
			# Welcome email is best-effort; never block onboarding on it.
			frappe.log_error(title="LMS User Setup welcome email", message=frappe.get_traceback())