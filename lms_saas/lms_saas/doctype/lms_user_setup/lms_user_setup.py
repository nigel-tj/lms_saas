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

		self._send_welcome_if_requested(user)
		self.db_update()

	# ------------------------------------------------------------------ helpers
	def _validate_persona(self):
		if self.persona not in PERSONA_CONFIG:
			frappe.throw(_("Invalid persona {0}").format(self.persona))

	def _validate_email_unique(self):
		if frappe.db.exists("User", self.email):
			frappe.throw(_("A User with email {0} already exists").format(self.email))
		if self.persona == "Borrower" and frappe.db.exists("Customer", {"email_id": self.email}):
			frappe.throw(_("A Customer with email {0} already exists").format(self.email))

	def _validate_branch_for_staff(self):
		config = PERSONA_CONFIG.get(self.persona) or {}
		if config.get("create_employee") and not self.branch:
			frappe.throw(_("Branch is required for staff personas"))

	def _validate_national_id_for_borrower(self):
		"""Borrowers need a National ID for KYC. Staff personas don't."""
		if self.persona == "Borrower" and not (self.national_id or "").strip():
			frappe.throw(_("National ID is required for the Borrower persona (used for KYC)"))

	def _validate_officer_scope(self):
		"""Loan Officers may only onboard Borrowers (separation of duties)."""
		roles = set(frappe.get_roles(frappe.session.user))
		if self.persona != "Borrower" and "LMS Loan Officer" in roles:
			if "LMS Branch Manager" not in roles and "LMS Admin" not in roles and "System Manager" not in roles:
				frappe.throw(_("Loan Officers may only create Borrower accounts"))

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
		# The before_validate User hook (lms_saas.api.staff.apply_lms_module_profile)
		# auto-applies the LMS Staff module profile for desk personas — no extra code.
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
			from lms_saas.utils.email import send_branded_email

			# Generate a one-time reset key link so first-login users can set
			# a password without being asked for an old one.
			user_doc = frappe.get_doc("User", user)
			reset_url = user_doc._reset_password(send_email=False)

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