"""R29 regression tests — Manager + Borrower portal flows.

These tests cover EXPERT_BOARD_REPORT_R29_MANAGER_BORROWER.md.
"""

from __future__ import annotations

import unittest
from unittest import mock

import frappe
from frappe.utils import flt

from lms_saas.api import manager as mgr


MANAGER_EMAIL = "manager@kesari.africa"
BRANCH = "Main Branch - LMS"
COMPANY = "LMS Demo Co"


def _set_user(user: str) -> None:
	frappe.set_user(user)


def _make_borrower(suffix: str) -> str:
	"""Create a Customer + LMS Borrower Compliance (KYC cleared)."""
	stamp = frappe.utils.now_datetime().strftime("%H%M%S%f")
	name = f"R29 Manager Test {suffix} {stamp}"
	cust = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Individual",
			"customer_group": "Individual",
			"territory": "All Territories",
			"custom_lms_branch": BRANCH,
			"custom_national_id_number": "8501011234089",
		}
	)
	cust.flags.ignore_permissions = True
	cust.insert()
	comp = frappe.get_doc(
		{
			"doctype": "LMS Borrower Compliance",
			"customer": cust.name,
			"kyc_status": "Approved",
			"aml_status": "Clear",
			"consent_given": 1,
			"consent_date": frappe.utils.today(),
			"national_id_number": "8501011234089",
			"id_document_proof": "NID",
			"proof_of_address": "UTILITY",
		}
	)
	comp.flags.ignore_permissions = True
	comp.insert()
	return cust.name


def _ensure_branch() -> None:
	"""Ensure the Cost Center exists so branch-scope resolves."""
	if not frappe.db.exists("Branch", "Main Branch"):
		b = frappe.new_doc("Branch")
		b.branch = "Main Branch"
		b.flags.ignore_permissions = True
		b.insert()


def _ensure_manager() -> str:
	"""Make sure the manager user has branch + Employee.

	The Manager user already exists (seeded by the dev bench); we
	only ensure the Employee record links to it with the right branch
	and persona. We skip the ``update_user`` password-strength trip
	by saving with ``ignore_version=True`` and using ``db_set`` for
	the fields we'd otherwise bounce.
	"""
	_set_user("Administrator")
	emp_name = frappe.db.get_value("Employee", {"user_id": MANAGER_EMAIL}, "name")
	if not emp_name:
		emp = frappe.new_doc("Employee")
		emp.employee_id = "EMP-MGR-R29"
		emp.first_name = "Test"
		emp.last_name = "Manager"
		emp.user_id = MANAGER_EMAIL
		emp.status = "Active"
		emp.company = COMPANY
		emp.date_of_joining = frappe.utils.today()
		emp.gender = "Male"
		emp.flags.ignore_permissions = True
		emp.insert()
		emp_name = emp.name
	# Patch fields via db_set to avoid the password-strength path
	# that runs on User.save() triggered by Employee.on_update.
	frappe.db.set_value(
		"Employee",
		emp_name,
		{
			"user_id": MANAGER_EMAIL,
			"status": "Active",
			"company": COMPANY,
			"custom_lms_persona": "Branch Manager"
			if frappe.get_meta("Employee").has_field("custom_lms_persona")
			else None,
			"custom_lms_branch": BRANCH
			if frappe.get_meta("Employee").has_field("custom_lms_branch")
			else None,
		},
		update_modified=True,
	)
	return emp_name


def _ensure_user_permission(email: str, branch: str) -> None:
	"""Ensure the user has a Cost Center User Permission."""
	ex = frappe.db.get_value(
		"User Permission",
		{"user": email, "allow": "Cost Center", "for_value": branch},
		"name",
	)
	if ex:
		return
	p = frappe.new_doc("User Permission")
	p.user = email
	p.allow = "Cost Center"
	p.for_value = branch
	p.apply_to_all_doctypes = 1
	p.flags.ignore_permissions = True
	p.insert()


def _make_loan_application(employee: str, customer: str) -> str:
	prod = frappe.db.get_value(
		"Loan Product", {"product_code": "LMS-STD"}, "name"
	)
	if not prod:
		prod = frappe.new_doc("Loan Product")
		prod.product_code = "LMS-STD"
		prod.product_name = "LMS Standard"
		prod.company = COMPANY
		prod.rate_of_interest = 18
		prod.flags.ignore_permissions = True
		prod.insert()
		prod = prod.name
	la = frappe.get_doc(
		{
			"doctype": "Loan Application",
			"applicant_type": "Customer",
			"applicant": customer,
			"company": COMPANY,
			"loan_product": prod,
			"loan_amount": 3000,
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
	return la.name


# ---------------------------------------------------------------------------
# F1 — branch_overview: aggregate dict syntax (not raw SQL string)
# ---------------------------------------------------------------------------


class TestR29BranchOverview(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_ensure_branch()

	def test_branch_overview_returns_today_collections(self):
		"""F1: ``sum(amount_paid) as total`` raised ``ValidationError: SQL
		functions are not allowed as strings in SELECT``. Now uses dict
		syntax ``{"SUM": "amount_paid", "as": "total"}``."""
		frappe.set_user(MANAGER_EMAIL)
		frappe.flags.ignore_permissions = True
		frappe.clear_cache()
		out = mgr.get_branch_overview()
		self.assertIn("branch", out)
		self.assertIn("today_collections", out)
		self.assertIn("pending_approvals", out)
		self.assertIn("team", out)


# ---------------------------------------------------------------------------
# F5 — collections_report + loan_statement: docstatus not status
# ---------------------------------------------------------------------------


class TestR29CollectionsReport(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_ensure_branch()

	def test_collections_report_uses_docstatus(self):
		"""F5: ``get_collections_report`` previously requested
		``Loan Repayment.status`` which doesn't exist → 500. Now
		requests docstatus and synthesises a friendly state."""
		frappe.set_user(MANAGER_EMAIL)
		frappe.flags.ignore_permissions = True
		frappe.clear_cache()
		out = mgr.get_collections_report()
		self.assertIn("repayments", out)
		self.assertIn("by_officer", out)
		self.assertIn("total_collected", out)


class TestR29LoanStatement(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_ensure_branch()

	def test_loan_statement_uses_docstatus_and_date_window(self):
		"""F5: ``get_loan_statement`` previously requested
		``Loan Repayment.status`` which doesn't exist → 500. Now uses
		docstatus via the helper, and the date window doesn't clobber."""
		# Find a disbursed loan with valid customer
		loan = None
		for ln in frappe.get_all(
			"Loan",
			filters={
				"docstatus": 1,
				"status": ("in", ["Disbursed", "Active"]),
				"custom_lms_branch": BRANCH,
			},
			fields=["name", "applicant"],
			limit_page_length=20,
		):
			if frappe.db.exists("Customer", ln["applicant"]):
				loan = ln["name"]
				break
		if not loan:
			self.skipTest("No clean loan to test against")
		frappe.set_user(MANAGER_EMAIL)
		frappe.flags.ignore_permissions = True
		frappe.clear_cache()
		out = mgr.get_loan_statement(loan_name=loan)
		self.assertIn("transactions", out)
		self.assertIn("opening_balance", out)
		self.assertIn("closing_balance", out)


# ---------------------------------------------------------------------------
# F8 — record_repayment: over-payment guard
# ---------------------------------------------------------------------------


class TestR29RecordRepaymentOverpayment(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_ensure_branch()
		cls.manager_employee = _ensure_manager()
		_ensure_user_permission(MANAGER_EMAIL, BRANCH)
		# Find any active loan in our branch with a valid Customer
		loan = None
		for ln in frappe.get_all(
			"Loan",
			filters={
				"docstatus": 1,
				"status": ("in", ["Disbursed", "Active"]),
				"custom_lms_branch": BRANCH,
			},
			fields=["name", "applicant"],
			limit_page_length=20,
		):
			if frappe.db.exists("Customer", ln["applicant"]):
				loan = ln["name"]
				break
		if not loan:
			cls.skipTest(
				cls,
				"Test setUp needs a real active loan with a valid Customer on this site.",
			)
		cls.loan = loan

	def test_record_repayment_blocks_overpayment(self):
		"""F8: amount > 1.1 * outstanding AND amount > 100 should throw."""
		frappe.set_user(MANAGER_EMAIL)
		frappe.flags.ignore_permissions = True
		loan_doc = frappe.get_doc("Loan", self.loan)
		# Total outstanding ~ total_payment - total_amount_paid; multiply by 2
		# to definitely trigger the > 1.1 * outstanding guard.
		outstanding = flt(loan_doc.total_payment or 0) - flt(
			loan_doc.total_amount_paid or 0
		)
		big_amount = max(outstanding * 2, 1000)
		with self.assertRaises(frappe.exceptions.ValidationError) as cm:
			mgr.record_repayment(
				loan_name=self.loan, amount=big_amount, payment_mode="Cash"
			)
		self.assertIn(
			"overpayment_confirm",
			str(cm.exception),
			"Error must reference the bypass flag",
		)


# ---------------------------------------------------------------------------
# F9 — write_off_loan: reason required + audit event
# ---------------------------------------------------------------------------


class TestR29WriteOffRequiresReason(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_ensure_branch()
		_ensure_manager()
		_ensure_user_permission(MANAGER_EMAIL, BRANCH)
		cls.customer = _make_borrower("WRITEOFF")

	def test_write_off_rejects_empty_reason(self):
		"""F9: write-off must require a reason for the audit trail."""
		frappe.set_user(MANAGER_EMAIL)
		frappe.flags.ignore_permissions = True
		with self.assertRaises(frappe.exceptions.ValidationError):
			# Find any disbursed loan
			for ln in frappe.get_all(
				"Loan",
				filters={
					"docstatus": 1,
					"status": ("in", ["Disbursed", "Active"]),
					"custom_lms_branch": BRANCH,
				},
				fields=["name"],
				limit_page_length=1,
			):
				mgr.write_off_loan(loan_name=ln["name"], reason="")
				break


# ---------------------------------------------------------------------------
# F11 — reject_application: audit event emitted
# ---------------------------------------------------------------------------


class TestR29RejectApplicationAudit(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_ensure_branch()
		_ensure_manager()
		_ensure_user_permission(MANAGER_EMAIL, BRANCH)

	def test_reject_emits_lms_audit_event(self):
		"""F11: rejecting an application MUST emit an LMS Audit Event so
		the regulator's walk-through sees it."""
		customer = _make_borrower("REJECT")
		# Make a draft Loan Application assigned to a loan officer
		prod = frappe.db.get_value(
			"Loan Product", {"product_code": "LMS-STD"}, "name"
		)
		la = frappe.get_doc(
			{
				"doctype": "Loan Application",
				"applicant_type": "Customer",
				"applicant": customer,
				"company": COMPANY,
				"loan_product": prod,
				"loan_amount": 2000,
				"repayment_periods": 2,
				"rate_of_interest": 18,
				"posting_date": frappe.utils.today(),
				"status": "Approved",
				"custom_lms_branch": BRANCH,
			}
		)
		la.insert(ignore_permissions=True)
		app_name = la.name
		audit_before = len(
			frappe.get_all(
				"LMS Audit Event",
				filters={
					"event_type": "LoanApplication:Rejected",
					"reference_name": app_name,
				},
			)
		)
		frappe.set_user(MANAGER_EMAIL)
		frappe.flags.ignore_permissions = True
		res = mgr.reject_application(
			application_name=app_name, reason="R29-test rejection"
		)
		self.assertEqual(res.get("status"), "rejected")
		audit_after = len(
			frappe.get_all(
				"LMS Audit Event",
				filters={
					"event_type": "LoanApplication:Rejected",
					"reference_name": app_name,
				},
			)
		)
		self.assertGreaterEqual(
			audit_after,
			audit_before + 1,
			"F11: reject must emit LMS Audit Event row",
		)


# ---------------------------------------------------------------------------
# F15 — update_borrower: customer_name uniqueness pre-check
# ---------------------------------------------------------------------------


class TestR29UpdateBorrowerUniqueness(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_ensure_branch()
		_ensure_manager()
		_ensure_user_permission(MANAGER_EMAIL, BRANCH)

	def test_unique_name_rejected_with_friendly_error(self):
		"""F15: renaming Customer A to the same name as Customer B must
		surface a friendly error, not a DuplicateEntryError traceback."""
		a = _make_borrower("UNIQ_A")
		b = _make_borrower("UNIQ_B")
		# Try to rename A to B's name
		frappe.set_user(MANAGER_EMAIL)
		frappe.flags.ignore_permissions = True
		with self.assertRaises(frappe.exceptions.ValidationError) as cm:
			mgr.update_borrower(
				customer_name=a,
				customer_name_new=frappe.db.get_value("Customer", b, "customer_name"),
			)
		self.assertIn("already exists", str(cm.exception).lower())
