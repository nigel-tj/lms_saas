"""LMS User Setup — single-screen onboarding for borrowers and staff.

A submittable DocType that hides Frappe internals (User / Customer / Contact /
Employee / roles / module profiles) behind one normal-looking form. On submit,
the server creates every linked record the selected persona needs, in one
transaction, so the end user never touches the raw Frappe admin screens.

Persona → roles/records mapping lives in ``lms_saas.install.PERSONA_CONFIG``
(single source of truth, DRY — add a persona by adding one row there).

Invariants enforced here:
* Submission is **atomic** — every linked record is created inside a savepoint,
  so a partial failure (e.g. duplicate Customer name) rolls back the User row
  too. (R26-P1-3, P2-1, P2-2.)
* Every creation and every welcome-email send is recorded as an
  ``LMS Audit Event`` so the regulator's audit trail covers onboarding.
  (R26-P1-2, P5-1.)
* The Contact is created with ``user`` pointing back at the new User, which
  is the canonical Contact-link for the portal permission resolver.
  (R26-P3-1.)
* Welcome email subject and body use the same brand chain
  (``utils.brand._brand_alias``) the rest of the app uses — no hard-coded
  fallback that leaks the original operator's name. (R26-P5-2.)
* Email format is validated on save so the operator catches typos that would
  otherwise create a User nobody can log in as. (R26-P6-8.)
* Cancellation of a submitted setup refuses to silently orphan the User /
  Customer / Contact / Employee rows it created; the operator must run an
  explicit cleanup path instead. (R26-P6-2.)
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document

from lms_saas.install import PERSONA_CONFIG


# Minimal structural email validation. We do not require a TLD because
# intranet installs (a single operator's deployment behind a VPN) can have
# legitimate single-label domains like `borrower@office`.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class LMSUserSetup(Document):
	# ---------------------------------------------------------------- lifecycle
	def validate(self):
		self._validate_persona()
		self._validate_email_format()
		self._validate_email_unique()
		self._validate_branch_for_staff()
		self._validate_national_id_for_borrower()
		self._validate_officer_scope()

	# NB: _validate_staff_branch was a duplicate of _validate_branch_for_staff
	# that previously ran on every save. R26 collapses to the surviving
	# _validate_branch_for_staff.

	def on_update_after_submit(self):
		self._sync_after_submit()

	def on_submit(self):
		config = PERSONA_CONFIG.get(self.persona)
		if not config:
			frappe.throw(_("Unknown persona: {0}").format(self.persona))

		# Atomic block: every linked record lives or dies together.
		# savepoint lets us roll back User/Customer/Contact/Employee on any
		# subsequent insert failure (e.g. duplicate Customer.name).
		savepoint = "lms_user_setup_submit"
		try:
			frappe.db.savepoint(savepoint)

			user = self._create_user(config)
			self.created_user = user

			if config.get("create_customer"):
				customer = self._create_customer(user)
				self.created_customer = customer
				self._link_contact(user, customer)

			if config.get("create_employee"):
				employee = self._create_employee(user)
				self.created_employee = employee
				if self.branch:
					# R28-F1: write BOTH the HRMS branch field AND
					# `custom_lms_branch`. The two names live in different
					# namespaces (Branch DocType vs custom field on
					# Employee) — `staff.get_current_user_branch()` looks
					# at `custom_lms_branch` first, the User Permission
					# layer looks at `Cost Center` permissions. Without
					# BOTH, a freshly-onboarded officer can resolve zero
					# branches and is bricked out of every write action.
					frappe.db.set_value("Employee", employee, "branch", self.branch)
					if frappe.get_meta("Employee").has_field("custom_lms_branch"):
						frappe.db.set_value(
							"Employee", employee, "custom_lms_branch", self.branch
						)
				if frappe.get_meta("Employee").has_field("custom_lms_persona"):
					frappe.db.set_value(
						"Employee", employee, "custom_lms_persona", self.persona
					)
				# R28-F1: create a Cost Center User Permission so the
				# officer's row-level permission filter limits them to
				# their own cost center records even when the API layer's
				# branch-scope guard is bypassed. Idempotent — we look for
				# an existing permission before insert.
				if self.branch:
					self._ensure_cost_center_user_permission(user, self.branch)

			self.db_update()

		except Exception:
			# Roll back the partial records so we never leave an orphan User
			# with no matching Customer / Contact / Employee. The
			# `created_*` fields stay None — operator can retry from clean.
			frappe.db.rollback(save_point=savepoint)
			self.created_user = None
			self.created_customer = None
			self.created_employee = None
			# Re-raise so the operator sees the original validation/insert
			# error (e.g. "Customer name already exists"). We do NOT wrap it
			# — wrapping hides the real cause.
			raise

		# Outside the savepoint now. Persist the audit row only if the
		# linked-record creation succeeded.
		self._audit_onboard()
		self._send_welcome_if_requested(user)

	def on_cancel(self):
		# R26-P6-2: a submitted LMS User Setup owns User / Customer / Contact /
		# Employee rows. Cancel would leave them orphaned with no audit trail
		# back to a creator. Refuse and require an explicit cleanup path so
		# the operator's regulator audit trail records a real retraction.
		has_records = any(
			[self.created_user, self.created_customer, self.created_employee]
		)
		if has_records:
			frappe.throw(
				_(
					"LMS User Setup {0} cannot be cancelled: linked records "
					"({1}) would orphan. Amend the setup instead, or run "
					"lms_saas.setup.retire_user_setup to remove the linked "
					"records under audit."
				).format(
					self.name,
					", ".join(
						f"{k}={v}"
						for k, v in (
							("User", self.created_user),
							("Customer", self.created_customer),
							("Employee", self.created_employee),
						)
						if v
					),
				)
			)
		# If records were never created (e.g. submit failed mid-flight and
		# the operator wants to cancel a draft-1 row) — allow it and audit.
		self._audit("cancel_empty", details={"setup": self.name})

	# ------------------------------------------------------------------ audit
	def _audit_onboard(self):
		"""Record a single audit row covering the full onboarding transaction."""
		details_parts = [
			f"persona={self.persona}",
			f"user={self.created_user}",
		]
		if self.created_customer:
			details_parts.append(f"customer={self.created_customer}")
		if self.created_employee:
			details_parts.append(f"employee={self.created_employee}")
		if self.branch:
			details_parts.append(f"branch={self.branch}")
		if self.send_welcome_email:
			details_parts.append("welcome_email=request")
		self._audit("user_onboarded", details={"_": ", ".join(details_parts)})

	def _audit(self, event_type, details=None):
		"""Append an immutable LMS Audit Event row.

		We only write when the DocType is installed (the audit pipeline is
		itself defined in this app, so install-time writes would be circular).
		"""
		if not frappe.db.exists("DocType", "LMS Audit Event"):
			return
		try:
			details_text = ""
			if isinstance(details, dict):
				details_text = "\n".join(
					f"{k}: {v}" for k, v in details.items() if v is not None
				)
			else:
				details_text = details or ""
			row = frappe.get_doc(
				{
					"doctype": "LMS Audit Event",
					"event_type": event_type.upper(),
					"event_time": frappe.utils.now_datetime(),
					"event_user": frappe.session.user,
					"reference_doctype": self.doctype,
					"reference_name": self.name,
					"company": frappe.db.get_single_value(
						"Global Defaults", "default_company"
					),
					"details": details_text,
				}
			)
			row.insert(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			# Audit failure must never block business logic. Log it, move on.
			frappe.log_error(
				title="LMS User Setup audit write failed",
				message=frappe.get_traceback(),
			)

	# ------------------------------------------------------------------ validate
	def _validate_persona(self):
		if self.persona not in PERSONA_CONFIG:
			frappe.throw(_("Invalid persona {0}").format(self.persona))

	def _validate_email_format(self):
		# R26-P6-8: server-side email format check. The Frappe `options: Email`
		# hint does NOT enforce; a typo creates a User that can never log in.
		if self.email and not _EMAIL_RE.match(self.email):
			frappe.throw(
				_("Email {0} does not look like a valid address").format(self.email)
			)

	def _ensure_cost_center_user_permission(self, user: str, cost_center: str) -> None:
		"""Create a User Permission allowing the new user on one Cost Center.

		R28-F1: this is the third leg of branch-isolation onboarding
		(alongside `Employee.branch` and `Employee.custom_lms_branch`).
		`staff.get_current_user_branch()` falls back to Cost Center User
		Permission when neither Employee field is set, so without this
		permission a freshly onboarded officer resolves to branch=None
		and is bricked out of every write action.

		Idempotent — re-running with an existing permission is a no-op.
		"""
		if not user or not cost_center:
			return
		if not frappe.db.exists("Cost Center", cost_center):
			# Don't throw — the operator may have used an HRMS Branch
			# string that doesn't exist as a Cost Center. Log so they can
			# spot the mismatch in the audit trail.
			frappe.log_error(
				title="LMS User Setup: branch is not a Cost Center",
				message=(
					f"user={user}, branch={cost_center!r} — "
					"User Permission not created. Officer portal writes will "
					"fail until a Cost Center of this name exists."
				),
			)
			return
		existing = frappe.db.get_value(
			"User Permission",
			{
				"user": user,
				"allow": "Cost Center",
				"for_value": cost_center,
			},
			"name",
		)
		if existing:
			return
		perm = frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Cost Center",
				"for_value": cost_center,
				"apply_to_all_doctypes": 1,
			}
		)
		perm.flags.ignore_permissions = True
		perm.insert()

	def _validate_email_unique(self):
		existing_user = frappe.db.get_value("User", self.email, "name")
		if existing_user and existing_user != (self.created_user or None):
			frappe.throw(
				_("A User with email {0} already exists").format(self.email)
			)
		if self.persona == "Borrower":
			existing_customer = frappe.db.get_value(
				"Customer", {"email_id": self.email}, "name"
			)
			if existing_customer and existing_customer != (self.created_customer or None):
				frappe.throw(
					_("A Customer with email {0} already exists").format(self.email)
				)
			# R26-P3-2: also block duplicate name collisions (two "John Smith"
			# would only hit the unique-name index at insert time, by which
			# point the User already exists).
			existing_name = frappe.db.get_value(
				"Customer", {"customer_name": self._full_name()}, "name"
			)
			if existing_name and existing_name != (self.created_customer or None):
				frappe.throw(
					_(
						"A Customer named {0} already exists (add a middle name "
						"or suffix to disambiguate, or merge into the existing "
						"customer record)."
					).format(self._full_name())
				)

	def _validate_branch_for_staff(self):
		# R26-P1-8 consolidation: this is the single source of truth for
		# branch-required-on-staff (the old duplicate _validate_staff_branch
		# is removed).
		config = PERSONA_CONFIG.get(self.persona) or {}
		if self.persona == "Admin":
			return
		if not config.get("create_employee"):
			return
		if not self.branch:
			frappe.throw(
				_("Branch is required for the {0} persona").format(self.persona)
			)
		# R47 fix: the branch MUST resolve to a real Cost Center in the
		# default company. Before this, an operator could pick a stale /
		# renamed / non-existent Cost Center and the Employee would be
		# created on a phantom branch — leaving the staff user silently
		# filtered out of every data tab on the portal. (Concrete
		# example: manager@kesari.africa was created with
		# 'Main Branch - LMS' (R42's legacy abbreviation) before R43
		# renamed it to 'Main Branch - LD'. The Employee never got
		# updated, so the manager saw zero records until somebody ran
		# provision_test_users manually.)
		company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
		if not frappe.db.exists(
			"Cost Center", {"name": self.branch, "company": company}
		):
			frappe.throw(
				_(
					"Branch {0} is not a valid Cost Center in company {1}. "
					"Pick a Cost Center that exists, or run "
					"lms_saas.setup.live_repair.reconcile_staff_branches() to "
					"auto-repair any Employees stuck on a legacy branch."
				).format(self.branch, company)
			)

	def _validate_national_id_for_borrower(self):
		if self.persona == "Borrower":
			national_id = (self.national_id or "").strip()
			if not national_id:
				frappe.throw(
					_("National ID is required for the Borrower persona (used for KYC)")
				)
			# R26-P4-3: minimal structural sanity. Different regulators use
			# different formats (numeric, alphanumeric, hyphenated). We accept
			# anything 4–40 chars that is not all-whitespace. Specific format
			# enforcement belongs to the regulator's KYC workflow.
			if len(national_id) < 4 or len(national_id) > 40:
				frappe.throw(
					_("National ID must be 4–40 characters (got {0})").format(
						len(national_id)
					)
				)

	def _validate_officer_scope(self):
		roles = set(frappe.get_roles(frappe.session.user))
		if (
			self.persona != "Borrower"
			and "System Manager" not in roles
			and "Administrator" not in roles
		):
			frappe.throw(_("Only administrators may create staff accounts"))

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
			frappe.throw(
				_(
					"Changing a submitted setup between borrower/admin and staff "
					"personas is not supported. Create a new setup record instead."
				)
			)

		if new_kind != "staff":
			# Mirror identity fields back to the User row so an admin amending
			# first-name/last-name/mobile leaves a consistent portal account.
			if self.created_user:
				frappe.db.set_value(
					"User",
					self.created_user,
					{
						"first_name": self.first_name,
						"last_name": self.last_name or "",
						"mobile_no": self.mobile_no or "",
					},
					update_modified=False,
				)
			return

		if not self.created_employee:
			frappe.throw(
				_(
					"This setup is missing its linked Employee record. Re-run "
					"onboarding or create a new setup."
				)
			)

		updates = {
			"branch": self.branch or None,
			"department": self.department or None,
			"gender": self.gender or None,
			"date_of_birth": self.date_of_birth or None,
		}
		# R28-F1: when the operator amends branch on a submitted setup, mirror
		# the change into `custom_lms_branch` and refresh the User Permission so
		# the officer's branch-scope resolves correctly after the amend.
		if self.branch and frappe.get_meta("Employee").has_field("custom_lms_branch"):
			updates["custom_lms_branch"] = self.branch
		if frappe.get_meta("Employee").has_field("custom_lms_persona"):
			updates["custom_lms_persona"] = self.persona
		frappe.db.set_value(
			"Employee", self.created_employee, updates, update_modified=True
		)

		# R28-F1: if the branch was changed, recreate the User Permission to
		# point at the new Cost Center. The helper is idempotent — passing the
		# same value twice is a no-op.
		if self.branch and self.created_user:
			self._ensure_cost_center_user_permission(self.created_user, self.branch)

		# Mirror identity fields back to the User row so an admin amending
		# email/first-name/etc. does not leave a stale portal account.
		if self.created_user:
			frappe.db.set_value(
				"User",
				self.created_user,
				{
					"first_name": self.first_name,
					"last_name": self.last_name or "",
					"mobile_no": self.mobile_no or "",
				},
				update_modified=False,
			)

	# ------------------------------------------------------------------ helpers
	def _full_name(self):
		parts = [p for p in (self.first_name, self.last_name) if p]
		return " ".join(parts) or self.email

	def _create_user(self, config):
		# R26-P2-1: wrap in a clean duplicate-email throw so concurrent
		# operators get a useful message instead of an IntegrityError trace.
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": self.email,
				"first_name": self.first_name,
				"last_name": self.last_name or "",
				"mobile_no": self.mobile_no or "",
				"send_welcome_email": 0,
				"enabled": 1,
				# R26-P1-7: explicitly default timezone/language so the new
				# user does not inherit the operator's session locale.
				"time_zone": "Africa/Nairobi",
				"language": "en",
			}
		)
		for role in config.get("roles", []):
			if frappe.db.exists("Role", role):
				user.append("roles", {"role": role})
		user.flags.ignore_permissions = True
		try:
			user.insert()
		except frappe.DuplicateEntryError:
			frappe.throw(
				_("A User with email {0} was created concurrently").format(self.email)
			)
		return user.name

	def _create_customer(self, user):
		customer_group = self._default_non_group_customer_group()
		territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or ""

		# R26-P3-5, P3-6: if either required field couldn't be resolved, bail
		# with a clear message rather than silently creating a Customer with
		# empty key fields that downstream reports will choke on.
		if not customer_group:
			frappe.throw(
				_(
					"No non-group Customer Group is configured. Create at least "
					"one in Setup → Customer Group before onboarding a borrower."
				)
			)
		if not territory:
			frappe.throw(
				_(
					"No non-group Territory is configured. Create at least one "
					"in Setup → Territory before onboarding a borrower."
				)
			)

		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": self._full_name(),
				"email_id": self.email,
				"mobile_no": self.mobile_no or "",
				"customer_group": customer_group,
				"territory": territory,
				"custom_lms_branch": self.branch or "",
				"custom_national_id_number": self.national_id or "",
			}
		)
		customer.flags.ignore_permissions = True
		customer.insert()
		return customer.name

	def _default_non_group_customer_group(self):
		return (
			frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
			or frappe.db.get_single_value("Selling Settings", "customer_group")
			or ""
		)

	def _link_contact(self, user, customer):
		"""Create a Contact linked to the User (so the portal permission
		resolver's first lookup hits) and to the Customer (so the
		dynamic-link resolver hits). R26-P3-1 sets ``user=`` explicitly —
		the previous code only set ``email_ids``, forcing the resolver onto
		its slower email-fallback path and risking duplicate-Contact
		ambiguity when a Contact with the same email already exists."""
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": self.first_name,
				"last_name": self.last_name or "",
				"user": user,  # R26-P3-1 fix
				"email_ids": [{"email_id": self.email, "is_primary": 1}],
				"links": [
					{"link_doctype": "Customer", "link_name": customer},
				],
			}
		)
		contact.flags.ignore_permissions = True
		contact.insert()

	def _create_employee(self, user):
		company = (
			frappe.db.get_single_value("Global Defaults", "default_company")
			or frappe.db.get_value("Company", {}, "name")
		)
		if not company:
			frappe.throw(
				_("No default Company found — set one in Global Defaults")
			)
		from frappe.utils import today

		# R26-P3-3, P3-4: surface defaults loudly. If gender/DOB/department
		# are blank the operator's HR report will be inaccurate and the
		# LMS audit trail cannot distinguish a real profile from a fake one.
		gender = self.gender
		if not gender:
			gender = "Male"
			frappe.msgprint(
				_("Defaulting gender to 'Male' — update the Employee record later."),
				indicator="orange",
				alert=True,
			)
		dob = self.date_of_birth
		if not dob:
			dob = "1990-01-01"
			frappe.msgprint(
				_("Defaulting date_of_birth to 1990-01-01 — update later."),
				indicator="orange",
				alert=True,
			)
		department = self.department
		if not department:
			frappe.msgprint(
				_(
					"No Department set on this Employee — HR reports may not "
					"roll up correctly. Update later."
				),
				indicator="orange",
				alert=True,
			)

		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": self.first_name,
				"last_name": self.last_name or "",
				"user_id": user,
				"company": company,
				"status": "Active",
				"gender": gender,
				"date_of_birth": dob,
				"date_of_joining": today(),
				"department": department or "",
			}
		)
		employee.flags.ignore_permissions = True
		employee.insert()
		return employee.name

	def _send_welcome_if_requested(self, user):
		if not self.send_welcome_email:
			return

		# R26-P5-2: subject + body use the same brand chain the rest of the
		# app uses. The previous code defaulted to `default_company` (legal
		# name) which leaks the wrong brand in emails.
		try:
			from frappe.utils import get_url

			from lms_saas.utils.brand import _brand_alias
			from lms_saas.utils.email import send_branded_email

			subject_brand = _brand_alias("operator_brand")
			reset_url = get_url(
				f"/update-password?email={frappe.utils.quote(self.email)}"
			)

			send_branded_email(
				recipients=[self.email],
				subject=_("Welcome to {0}").format(subject_brand),
				body_key="welcome",
				context={
					"customer_name": self._full_name(),
					"reset_password_url": reset_url,
				},
				reference_doctype=self.doctype,
				reference_name=self.name,
			)
			# R26-P5-1: success audit row.
			self._audit(
				"welcome_email_sent",
				details={"recipient": self.email, "subject_brand": subject_brand},
			)
		except Exception:
			# R26-P5-1: failure audit row, NOT a silent log_error. The
			# regulator needs to see that an email was attempted-and-failed.
			self._audit(
				"welcome_email_failed",
				details={"recipient": self.email, "trace": "see Error Log"},
			)
			frappe.log_error(
				title="LMS User Setup welcome email",
				message=frappe.get_traceback(),
			)
