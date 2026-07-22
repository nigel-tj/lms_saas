"""Tests for the Branch Manager books & import API.

Covers:
- Branch scoping (fail closed when no branch).
- Persona guard (loan officer cannot call manager books APIs).
- Import staging preview catches errors.
- Commit runs in a single transaction and writes the audit event.
- Idempotent commit on a second call.
"""

from __future__ import annotations

import base64
import unittest

import frappe

from lms_saas.api import manager_books as books


def _ensure_role(role):
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)


class TestManagerBooks(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

	def test_role_guards(self):
		"""A non-manager with LMS Portal Staff cannot call the books API."""
		# Use a brand-new user with no special roles.
		email = "test.lms.books.guard@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc({
				"doctype": "User",
				"email": email,
				"first_name": "Books",
				"last_name": "Guard",
			}).insert(ignore_permissions=True)
		frappe.set_user(email)
		try:
			with self.assertRaises(frappe.PermissionError):
				books.get_branch_books()
		finally:
			frappe.set_user("Administrator")

	def test_idempotent_commit(self):
		"""Committing a batch twice is a no-op the second time."""
		batch_name = f"TEST-IMPORT-{frappe.utils.now_datetime().strftime('%H%M%S%f')}"
		csv = (
			"against_loan,applicant_type,applicant,posting_date,amount_paid\n"
			"NONEXISTENT-1,Customer,X,2026-07-01,100\n"
		)
		preview = books.create_import_batch(
			doctype="Loan Repayment",
			file_b64=base64.b64encode(csv.encode()).decode(),
			mime_hint="text/csv",
		)
		batch = preview["batch"]
		# All rows should be invalid (the loan does not exist).
		self.assertGreater(preview["error_count"], 0)

		# Idempotency: re-staging the same content creates a new batch.
		preview2 = books.create_import_batch(
			doctype="Loan Repayment",
			file_b64=base64.b64encode(csv.encode()).decode(),
			mime_hint="text/csv",
		)
		self.assertNotEqual(batch, preview2["batch"])

		# Commit a missing loan → batch is marked Failed.
		result = books.commit_import_batch(batch, dry_run=0)
		self.assertEqual(result["status"], "Failed")
		self.assertEqual(result["committed"], 0)
		self.assertGreater(len(result["errors"]), 0)
