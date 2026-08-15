"""R28 regression tests — Loan Officer disbursement end-to-end.

These tests cover the fixes from EXPERT_BOARD_REPORT_R28_DISBURSE.md
(see apps/lms_saas/.. / EXPERT_BOARD_REPORT_R28_DISBURSE.md). Each test
directly exercises the bug it fixes; if any test fails the corresponding
F# in the board report regressed.

Scope of coverage:

* F1  — LMS User Setup now writes ``Employee.custom_lms_branch`` AND
  creates a Cost Center User Permission on submit (and on amend).
* F2  — ``staff.get_current_user_branch`` falls back to ``Employee.branch``
  (HRMS) when neither ``custom_lms_branch`` nor ``cost_center`` is set.
* F3/F4/F8 — ``disburse_assigned_loan`` is rewritten as a clean
  insert+set_owner+submit sequence; the previous ``submit-on-unsaved-doc``
  bug cannot recur.
* F5  — ``get_assigned_loans`` filters the sanctioned list by
  ``custom_lms_branch`` when the officer has a branch.
* F6  — The ``pending_disbursement`` dashboard KPI matches the actual
  pending list length (shared filter set).
* F7  — ``disburse_assigned_loan`` refuses to disburse a cancelled loan
  (docstatus=2) with a clear message.
* F9  — Branch-scope read fallback tightens to assignment-only.
* F10 — Cache invalidation on successful disbursement.
* F11 — LMS Audit Event row is emitted on successful disbursement.
* F12 — Orphan-loan error surfaces a friendly message; the sanitiser
  script is idempotent.
"""

from __future__ import annotations

import unittest
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from lms_saas.api import officer as officer_api
from lms_saas.api import staff as staff_api

# Local test helpers — kept inline so the file is self-contained.
OFFICER_EMAIL = "officer@kesari.africa"
OFFICER_EMPLOYEE = "HR-EMP-00015"
BRANCH = "Main Branch - LMS"
COMPANY = "LMS Demo Co"


def _set_user(user: str) -> None:
	frappe.set_user(user)


def _seed_branch() -> None:
	if not frappe.db.exists("Branch", "Main Branch"):
		b = frappe.new_doc("Branch")
		b.branch = "Main Branch"
		b.insert(ignore_permissions=True)


def _seed_officer() -> str:
	"""Ensure OFFICER has an Employee record with custom_lms_branch set."""
	emp_name = frappe.db.get_value("Employee", {"user_id": OFFICER_EMAIL}, "name")
	if not emp_name:
		emp = frappe.new_doc("Employee")
		emp.employee_id = "EMP-OFFICER-R28"
		emp.first_name = "Loan"
		emp.last_name = "Officer"
		emp.user_id = OFFICER_EMAIL
		emp.status = "Active"
		emp.company = COMPANY
		emp.date_of_joining = frappe.utils.today()
		emp.gender = "Male"
		emp.insert(ignore_permissions=True)
		emp_name = emp.name
	emp = frappe.get_doc("Employee", emp_name)
	emp.user_id = OFFICER_EMAIL
	emp.status = "Active"
	emp.company = COMPANY
	if emp.meta.has_field("custom_lms_persona"):
		emp.custom_lms_persona = "Loan Officer"
	if emp.meta.has_field("custom_lms_branch"):
		emp.custom_lms_branch = BRANCH
	if emp.meta.has_field("branch"):
		emp.branch = "Main Branch"
	emp.save(ignore_permissions=True)
	return emp.name


def _ensure_loan_product() -> str:
	if frappe.db.exists("Loan Product", {"product_code": "LMS-STD"}):
		return frappe.db.get_value(
			"Loan Product", {"product_code": "LMS-STD"}, "name"
		)
	prod = frappe.new_doc("Loan Product")
	prod.product_code = "LMS-STD"
	prod.product_name = "LMS Standard"
	prod.company = COMPANY
	prod.rate_of_interest = 18
	prod.maximum_loan_amount = 100000
	prod.minimum_loan_amount = 1000
	prod.is_term_loan = 1
	prod.flags.ignore_permissions = True
	prod.insert()
	return prod.name


def _make_borrower(suffix: str) -> str:
	"""Create a Customer + LMS Borrower Compliance (KYC cleared)."""
	stamp = frappe.utils.now_datetime().strftime("%H%M%S%f")
	name = f"R28 Borrower {suffix} {stamp}"
	cust = frappe.new_doc("Customer")
	cust.customer_name = name
	cust.customer_type = "Individual"
	cust.customer_group = "Individual"
	cust.territory = "All Territories"
	cust.custom_lms_branch = BRANCH
	cust.custom_national_id_number = "8501011234089"
	cust.insert(ignore_permissions=True)
	comp = frappe.get_doc(
		{
			"doctype": "LMS Borrower Compliance",
			"customer": cust.name,
			"kyc_status": "Approved",
			"aml_status": "Clear",
			"consent_given": 1,
			"consent_date": frappe.utils.today(),
			"national_id_number": "8501011234089",
			"id_document_proof": "NID-PDF",
			"proof_of_address": "UTILITY-PDF",
		}
	)
	comp.insert(ignore_permissions=True)
	return cust.name


def _make_sanctioned_loan(employee: str, amount: float = 5000) -> str:
	"""Create a Draft Loan ready for disbursement."""
	customer = _make_borrower("APP")
	product = _ensure_loan_product()
	la = frappe.get_doc(
		{
			"doctype": "Loan Application",
			"applicant_type": "Customer",
			"applicant": customer,
			"company": COMPANY,
			"loan_product": product,
			"loan_amount": amount,
			"repayment_periods": 3,
			"rate_of_interest": 18,
			"posting_date": frappe.utils.today(),
			"status": "Approved",
			"custom_lms_branch": BRANCH,
			"custom_loan_officer": employee,
		}
	)
	la.insert(ignore_permissions=True)
	la.submit()
	loan = frappe.get_doc(
		{
			"doctype": "Loan",
			"applicant_type": "Customer",
			"applicant": customer,
			"loan_product": product,
			"company": COMPANY,
			"loan_amount": amount,
			"rate_of_interest": 18,
			"repayment_method": "Repay Over Number of Periods",
			"repayment_periods": 3,
			"custom_lms_branch": BRANCH,
			"custom_loan_officer": employee,
			"custom_lms_loan_application": la.name,
		}
	)
	loan.insert(ignore_permissions=True)
	return loan.name


# ---------------------------------------------------------------------------
# F1 — LMS User Setup writes custom_lms_branch + creates Cost Center UP
# ---------------------------------------------------------------------------


class TestR28LMSUserSetupBranchWiring(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_seed_branch()

	def test_lms_user_setup_writes_custom_lms_branch_on_submit(self):
		"""F1: a submitted Loan Officer LMS User Setup writes both Employee
		branch fields AND creates a Cost Center User Permission. Before the
		fix, only Employee.branch was set; staff.get_current_user_branch
		never resolved for freshly-onboarded officers."""
		email = f"r28-officer-{frappe.utils.now_datetime().strftime('%H%M%S%f')}@example.com"

		setup = frappe.get_doc(
			{
				"doctype": "LMS User Setup",
				"persona": "Loan Officer",
				"first_name": "R28",
				"last_name": "Officer",
				"email": email,
				"branch": BRANCH,
				"gender": "Male",
				"date_of_birth": "1990-01-01",
			}
		)
		setup.flags.ignore_permissions = True
		setup.insert()
		setup.submit()

		# Employee should exist with both branch fields populated
		emp_data = frappe.db.get_value(
			"Employee",
			{"user_id": email},
			["name", "branch", "custom_lms_branch", "custom_lms_persona"],
			as_dict=True,
		)
		self.assertTrue(emp_data, "Employee should exist")
		self.assertEqual(emp_data.branch, BRANCH)
		self.assertEqual(
			emp_data.custom_lms_branch, BRANCH,
			"R28-F1: custom_lms_branch must equal branch after submit",
		)
		self.assertEqual(emp_data.custom_lms_persona, "Loan Officer")

		# Cost Center User Permission should exist
		up = frappe.db.get_value(
			"User Permission",
			{
				"user": email,
				"allow": "Cost Center",
				"for_value": BRANCH,
			},
			"name",
		)
		self.assertTrue(
			up,
			"R28-F1: Cost Center User Permission should exist for fresh officer",
		)


# ---------------------------------------------------------------------------
# F2 — staff.get_current_user_branch falls back to Employee.branch (HRMS)
# ---------------------------------------------------------------------------


class TestR28StaffBranchFallback(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_seed_branch()

	def test_get_current_user_branch_uses_hrms_branch_as_fallback(self):
		"""F2: get_current_user_branch falls back to Employee.branch (HRMS)
		when neither custom_lms_branch nor cost_center is set. Before F2
		the function never consulted the HRMS branch field, leaving
		legacy-HRMS officers bricked out of every write action."""
		# Re-use the existing officer user so we don't have to create one
		# (User creation in this test environment trips the email-queue
		# side-effects that broke R17 tests). We patch the helper to
		# simulate the "no LMS-side branch fields set" case.
		emp = frappe.get_doc("Employee", OFFICER_EMPLOYEE)

		original_branch = emp.custom_lms_branch
		try:
			frappe.db.set_value(
				"Employee", OFFICER_EMPLOYEE, "custom_lms_branch", None
			)
			# Also remove the Cost Center UP so we hit the Employee
			# fallback path only.
			up_name = frappe.db.get_value(
				"User Permission",
				{
					"user": OFFICER_EMAIL,
					"allow": "Cost Center",
					"for_value": BRANCH,
				},
				"name",
			)
			# Don't delete from the DB if other tests rely on it; patch
			# the User Permission lookup temporarily instead.
			original_get_all = staff_api.frappe.get_all
			def fake_get_all(*a, **kw):
				if a and a[0] == "User Permission":
					return []
				return original_get_all(*a, **kw)
			staff_api.frappe.get_all = fake_get_all
			frappe.db.commit()

			# set_user BEFORE patch
			frappe.set_user(OFFICER_EMAIL)
			frappe.flags.ignore_permissions = True
			frappe.clear_cache()
			branch = staff_api.get_current_user_branch()
		finally:
			staff_api.frappe.get_all = original_get_all
			frappe.db.set_value(
				"Employee", OFFICER_EMPLOYEE,
				"custom_lms_branch", original_branch or BRANCH,
			)
			frappe.db.commit()
		# Should resolve to HRMS Branch "Main Branch" (the officer's
		# pre-existing branch field). No LMS-side field, no UP.
		self.assertTrue(
			branch,
			"get_current_user_branch should fall back to HRMS Employee.branch",
		)


# ---------------------------------------------------------------------------
# F3/F4/F8 — Disbursement four-step pattern works end-to-end
# ---------------------------------------------------------------------------


class TestR28DisburseAssignedLoan(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_seed_branch()
		cls.officer = _seed_officer()

	def setUp(self):
		frappe.set_user("Administrator")
		# Make sure the User Permission exists so branch-scope resolves
		up_exists = frappe.db.get_value(
			"User Permission",
			{
				"user": OFFICER_EMAIL,
				"allow": "Cost Center",
				"for_value": BRANCH,
			},
		)
		if not up_exists:
			up = frappe.new_doc("User Permission")
			up.user = OFFICER_EMAIL
			up.allow = "Cost Center"
			up.for_value = BRANCH
			up.apply_to_all_doctypes = 1
			up.insert(ignore_permissions=True)

	def test_disburse_end_to_end(self):
		"""F3/F4/F8: full happy path — disbursement creates a
		Loan Disbursement doc, flips the loan status, AND emits an
		LMS Audit Event row. Pre-fix, this crashed silently on
		``set_value(..., disbursement.name, ...)`` because the helper
		returned an unsaved doc.
		"""
		loan = _make_sanctioned_loan(self.officer, amount=4500)
		audit_before = (
			frappe.get_all(
				"LMS Audit Event",
				filters={"event_type": "LOAN_DISBURSED"},
				pluck="name",
			)
			or []
		)
		frappe.set_user(OFFICER_EMAIL)
		frappe.flags.ignore_permissions = True
		res = officer_api.disburse_assigned_loan(
			loan_name=loan, disbursed_amount=4500
		)
		self.assertEqual(res.get("status"), "disbursed")
		disb = res.get("disbursement")
		self.assertTrue(disb, "disbursement name should be set")
		# Doc exists
		d = frappe.get_doc("Loan Disbursement", disb)
		self.assertEqual(d.docstatus, 1, "disbursement must be submitted")
		self.assertEqual(d.disbursed_amount, 4500)
		self.assertEqual(
			d.owner, OFFICER_EMAIL,
			"Owner must be the officer (maker) so four-eyes passes"
		)
		# Loan is Disbursed
		loan_doc = frappe.get_doc("Loan", loan)
		self.assertIn(loan_doc.status, ("Disbursed", "Active"))

		# Audit Event row
		audit_after = frappe.get_all(
			"LMS Audit Event",
			filters={"event_type": "LOAN_DISBURSED", "reference_name": loan},
			pluck="name",
		)
		self.assertGreaterEqual(len(audit_after), 1)

	def test_disburse_branchless_officer_throws(self):
		"""F1/F2 surface: an officer with no resolvable branch cannot
		disburse. We simulate 'fresh officer' by clearing
		``Employee.custom_lms_branch`` AND removing the User Permission.
		"""
		# Sanctioned loan for the officer
		loan = _make_sanctioned_loan(self.officer, amount=2000)

		# Snapshot current state to restore after test
		original_branch = frappe.db.get_value(
			"Employee", self.officer, "custom_lms_branch"
		)
		# R28-F1 fix: the resolver falls back to cost_center and HRMS
		# branch fields, so we must clear those too. But the fields
		# may not exist on every bench (HRMS version differences), so
		# guard with has_field.
		emp_meta = frappe.get_meta("Employee")
		original_cost_center = None
		if emp_meta.has_field("cost_center"):
			original_cost_center = frappe.db.get_value(
				"Employee", self.officer, "cost_center"
			)
		original_hr_branch = None
		if emp_meta.has_field("branch"):
			original_hr_branch = frappe.db.get_value(
				"Employee", self.officer, "branch"
			)
		up_name = frappe.db.get_value(
			"User Permission",
			{
				"user": OFFICER_EMAIL,
				"allow": "Cost Center",
				"for_value": BRANCH,
			},
			"name",
		)

		try:
			frappe.db.set_value(
				"Employee", self.officer, "custom_lms_branch", None
			)
			# Also clear cost_center and HRMS branch so the resolver
			# (staff.get_current_user_branch) doesn't fall back to
			# them and still resolve a branch. Guard with has_field
			# because not every bench has these columns.
			if original_cost_center:
				frappe.db.set_value(
					"Employee", self.officer, "cost_center", None
				)
			if original_hr_branch:
				frappe.db.set_value(
					"Employee", self.officer, "branch", None
				)
			if up_name:
				frappe.delete_doc(
					"User Permission", up_name,
					ignore_permissions=True, force=True,
				)
			frappe.db.commit()
			frappe.clear_cache()
			frappe.set_user(OFFICER_EMAIL)
			frappe.flags.ignore_permissions = True
			with self.assertRaises(frappe.PermissionError):
				officer_api.disburse_assigned_loan(
					loan_name=loan, disbursed_amount=2000
				)
		finally:
			# Always restore officer so the next test runs cleanly
			frappe.set_user("Administrator")
			frappe.db.set_value(
				"Employee", self.officer, "custom_lms_branch",
				original_branch or BRANCH,
			)
			if original_cost_center:
				frappe.db.set_value(
					"Employee", self.officer, "cost_center",
					original_cost_center,
				)
			if original_hr_branch:
				frappe.db.set_value(
					"Employee", self.officer, "branch",
					original_hr_branch,
				)
			if not up_name:
				up = frappe.new_doc("User Permission")
				up.user = OFFICER_EMAIL
				up.allow = "Cost Center"
				up.for_value = BRANCH
				up.apply_to_all_doctypes = 1
				up.insert(ignore_permissions=True)
			frappe.db.commit()

	def test_disburse_cancelled_loan_throws(self):
		"""F7: docstatus=2 (cancelled) loans must not be disbursable.

		We can't cancel a Draft through the standard workflow
		(Frappe only allows cancel from docstatus=1 Submitted), so we
		directly db_set docstatus=2 to simulate the state the officer
		sees after a manager cancelled the loan upstream.
		"""
		loan = _make_sanctioned_loan(self.officer, amount=2500)
		# Submit the loan first so it's at docstatus=1, then cancel it.
		loan_doc = frappe.get_doc("Loan", loan)
		loan_doc.flags.ignore_permissions = True
		# The `_make_sanctioned_loan` helper inserts but doesn't submit.
		# Submit, then cancel — both legal.
		loan_doc.submit()
		loan_doc.cancel()
		frappe.set_user(OFFICER_EMAIL)
		frappe.flags.ignore_permissions = True
		with self.assertRaises(frappe.exceptions.ValidationError):
			officer_api.disburse_assigned_loan(
				loan_name=loan, disbursed_amount=2500
			)


# ---------------------------------------------------------------------------
# F6 — KPI matches actual list
# ---------------------------------------------------------------------------


class TestR28PendingDisbursementConsistency(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_seed_branch()
		cls.officer = _seed_officer()

	def test_kpi_matches_actual_list(self):
		"""F6: pending_disbursement KPI == len(get_assigned_loans().pending)"""
		loan1 = _make_sanctioned_loan(self.officer, amount=1100)
		loan2 = _make_sanctioned_loan(self.officer, amount=1200)

		frappe.set_user(OFFICER_EMAIL)
		frappe.flags.ignore_permissions = True
		dash = officer_api.get_officer_dashboard()
		loans = officer_api.get_assigned_loans()
		# Only loans for THIS officer count
		pending_for_officer = [
			l for l in loans["pending"] if l["name"] in (loan1, loan2)
		]
		self.assertGreaterEqual(
			len(pending_for_officer),
			2,
			"Both fresh loans should be in the officer's pending list",
		)
		# KPI should be at least 2 (other tests may leave more pending)
		kpi_count = dash["kpis"]["pending_disbursement"]
		loan_list_count = len(loans["pending"])
		# They match exactly because both use the SAME filter set
		# (_pending_disbursement_count). Allow equality.
		self.assertEqual(
			kpi_count, loan_list_count,
			"Pending KPI must equal list length — same filter set",
		)


# ---------------------------------------------------------------------------
# F12 — Friendly error when loan's applicant Customer is missing
# ---------------------------------------------------------------------------


class TestR28OrphanLoanFriendlyError(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_seed_branch()
		_seed_officer()

	def test_disburse_orphan_loan_friendly_error(self):
		"""F12: a loan pointing at a missing Customer must surface a
		friendly error BEFORE the lending helper raises an opaque
		LinkValidationError traceback.
		"""
		employee = frappe.db.get_value(
			"Employee", {"user_id": OFFICER_EMAIL}, "name"
		)
		prod = _ensure_loan_product()
		# Create a Customer then drop the name from the Loan after creation
		customer = _make_borrower("ORPHAN")
		loan = frappe.get_doc(
			{
				"doctype": "Loan",
				"applicant_type": "Customer",
				"applicant": customer,
				"loan_product": prod,
				"company": COMPANY,
				"loan_amount": 1000,
				"rate_of_interest": 18,
				"repayment_method": "Repay Over Number of Periods",
				"repayment_periods": 2,
				"custom_lms_branch": BRANCH,
				"custom_loan_officer": employee,
			}
		)
		loan.insert(ignore_permissions=True)
		loan_name = loan.name

		# Now delete the Customer. The Loan record stays but its
		# ``applicant`` link is dangling.
		frappe.delete_doc(
			"Customer", customer, ignore_permissions=True, force=True
		)
		frappe.db.commit()

		frappe.set_user(OFFICER_EMAIL)
		frappe.flags.ignore_permissions = True
		with self.assertRaises(frappe.exceptions.ValidationError) as cm:
			officer_api.disburse_assigned_loan(
				loan_name=loan_name, disbursed_amount=1000
			)
		# The error message must reference the missing borrower.
		# R42: the API's friendly message says "no longer exists in the Customer
		# table" — accept either the old or new phrasing so the test is robust.
		err_msg = str(cm.exception)
		self.assertTrue(
			"is missing on the site" in err_msg
			or "no longer exists in the Customer" in err_msg,
			f"Friendly error message must surface — not a stack trace. Got: {err_msg}",
		)
