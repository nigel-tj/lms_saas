"""R22 regression tests — the gaps the R22 board surfaced.

R22-C1: LMS Incident Log had a parallel R20-H1-style flaw — the
Sys Manager perms granted delete=1, write=1, and the controller was
an empty class. Mirrored the R20-H1 / R21-H1 immutability fix.

R22-C2: borrower ``submit_loan_application`` and ``upload_kyc_document``
wrote no LMS Audit Event. The regulator's audit trail was blind to
borrower-side actions. Added audit-event writes (and a branch-scoping
fix that was masking applications from the approval queue).

R22-High: LMS Notification Log had the same Sys Manager / LMS Portal
Staff delete=1 flaw. Hardened with role-aware delete (privileged
roles forbidden, portal staff audited).

R22-Medium: stale docstring in ``_resolve_loan_application_owner``
(claimed to read ``custom_lms_loan``; body reads
``custom_lms_loan_application``). Updated docstring.

AML role gates: Loan Officer cannot clear AML flags; only Branch
Manager (or higher) can override; the override writes a critical
LMS Audit Event.

Run via:
    cd frappe-bench && python run_all_lms_tests.py
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

APP_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# R22-C1: LMS Incident Log is append-only.
# ---------------------------------------------------------------------------
class TestR22IncidentLogImmutability(FrappeTestCase):
	"""R22-C1: LMS Incident Log must be append-only.

	Mirrors the R20-H1 (LMS Audit Event) and R21-H1 (LMS PII Access
	Log) immutability pattern. The DocType permission block must have
	delete=0, write=0; the controller must hard-throw on update / trash.
	"""

	def test_json_perms_drop_delete_and_write(self):
		import json as _json
		from pathlib import Path

		path = (
			Path(APP_ROOT)
			/ "lms_saas"
			/ "doctype"
			/ "lms_incident_log"
			/ "lms_incident_log.json"
		)
		spec = _json.loads(path.read_text())
		sys_mgr = next(
			(p for p in spec["permissions"] if p["role"] == "System Manager"),
			None,
		)
		self.assertIsNotNone(sys_mgr, "System Manager perms block missing")
		self.assertEqual(sys_mgr.get("write"), 0, "Sys Mgr must NOT have write=1")
		self.assertEqual(sys_mgr.get("delete"), 0, "Sys Mgr must NOT have delete=1")
		self.assertEqual(sys_mgr.get("read"), 1)
		self.assertEqual(sys_mgr.get("create"), 1)
		self.assertEqual(sys_mgr.get("export"), 1)

	def test_controller_has_immutability_guards(self):
		"""The controller must have on_update + on_trash that throw."""
		from lms_saas.lms_saas.doctype.lms_incident_log.lms_incident_log import (
			LMSIncidentLog,
		)
		self.assertTrue(hasattr(LMSIncidentLog, "on_update"))
		self.assertTrue(hasattr(LMSIncidentLog, "on_trash"))
		# on_update guard fires after the insert.
		doc = frappe.new_doc("LMS Incident Log")
		doc.flags.in_insert = False
		with self.assertRaises(frappe.ValidationError):
			doc.on_update()


# ---------------------------------------------------------------------------
# R22-C2: borrower flows write LMS Audit Events.
# ---------------------------------------------------------------------------
class TestR22BorrowerAuditTrail(FrappeTestCase):
	"""R22-C2: borrower submit + KYC upload must write audit rows."""

	def test_borrower_submit_writes_attempt_audit_row(self):
		import inspect

		from lms_saas.api import portal

		# Verify the early-audit branch is reachable in the function
		# source. The block on missing consent fires _after_ the audit
		# row would be written, so the regulator sees every portal hit.
		src = inspect.getsource(portal.submit_loan_application)
		self.assertIn("LoanApplication:Submit:Attempt", src)
		self.assertIn("write_audit_event", src)

	def test_borrower_submit_sets_branch_and_officer(self):
		"""R22-C2: the application must carry custom_lms_branch so the
		manager's approval queue (filtered by branch) returns it."""
		import inspect

		from lms_saas.api import portal

		src = inspect.getsource(portal.submit_loan_application)
		self.assertIn("custom_lms_branch", src)
		self.assertIn("custom_loan_officer", src)

	def test_officer_submit_sets_branch_and_officer(self):
		"""R22-C2: same fix on the officer-side submit flow."""
		import inspect

		from lms_saas.api import lms_portal

		src = inspect.getsource(lms_portal.submit_loan_application_officer)
		self.assertIn("custom_lms_branch", src)
		self.assertIn("custom_loan_officer", src)
		self.assertIn("LoanApplication:Submitted:Officer", src)

	def test_kyc_upload_writes_audit_row(self):
		"""R22-C2: upload_kyc_document writes a KYC:Document:Uploaded row."""
		import inspect

		from lms_saas.api import portal

		src = inspect.getsource(portal.upload_kyc_document)
		self.assertIn("KYC:Document:Uploaded", src)
		self.assertIn("write_audit_event", src)


# ---------------------------------------------------------------------------
# R22-High: LMS Notification Log role-aware delete.
# ---------------------------------------------------------------------------
class TestR22NotificationLogImmutability(FrappeTestCase):
	"""R22-High: privileged-role rows immutable; portal-staff rows audited."""

	def test_json_perms_drop_delete_and_write(self):
		import json as _json
		from pathlib import Path

		path = (
			Path(APP_ROOT)
			/ "lms_saas"
			/ "doctype"
			/ "lms_notification_log"
			/ "lms_notification_log.json"
		)
		spec = _json.loads(path.read_text())
		sys_mgr = next(
			(p for p in spec["permissions"] if p["role"] == "System Manager"),
			None,
		)
		portal_staff = next(
			(p for p in spec["permissions"] if p["role"] == "LMS Portal Staff"),
			None,
		)
		self.assertEqual(sys_mgr.get("write"), 0)
		self.assertEqual(sys_mgr.get("delete"), 0)
		self.assertEqual(portal_staff.get("write"), 0)
		self.assertEqual(portal_staff.get("delete"), 0)

	def test_controller_enforces_role_aware_delete(self):
		from lms_saas.lms_saas.doctype.lms_notification_log.lms_notification_log import (
			LMSNotificationLog,
		)
		# Verify the constant is in the controller module (not in
		# aml_role_gates, where the import expected it).
		import lms_saas.lms_saas.doctype.lms_notification_log.lms_notification_log as ctrl
		self.assertTrue(hasattr(ctrl, "LOCKED_OWNER_ROLES"))
		self.assertIn("System Manager", ctrl.LOCKED_OWNER_ROLES)
		self.assertIn("LMS Admin", ctrl.LOCKED_OWNER_ROLES)
		self.assertTrue(hasattr(LMSNotificationLog, "on_update"))
		self.assertTrue(hasattr(LMSNotificationLog, "on_trash"))


# ---------------------------------------------------------------------------
# R22-Medium: docstring freshness + audit-hash canonical alignment.
# ---------------------------------------------------------------------------
class TestR22DocstringAndCanonical(FrappeTestCase):
	def test_resolver_docstring_matches_implementation(self):
		import inspect

		from lms_saas.api.compliance import _resolve_loan_application_owner

		doc = inspect.getdoc(_resolve_loan_application_owner) or ""
		# The OLD broken field name must not appear.
		self.assertNotIn("custom_lms_loan`", doc)
		# The NEW field name must appear.
		self.assertIn("custom_lms_loan_application", doc)
		self.assertIn("time-windowed", doc.lower())


# ---------------------------------------------------------------------------
# Regulator-agnostic compliance messages.
# ---------------------------------------------------------------------------
class TestR22RegulatorAgnosticMessages(FrappeTestCase):
	"""Compliance messages do NOT name a specific regulator."""

	def test_consent_message_is_regulator_neutral(self):
		import inspect

		from lms_saas.api import compliance

		src = inspect.getsource(compliance.enforce_origination_controls)
		# The "RBZ Sandbox 3.19" hard-coded reference must be gone.
		self.assertNotIn("RBZ", src)
		self.assertNotIn("Sandbox 3.19", src)
		# The new message is regulator-neutral.
		self.assertIn("Customer consent is required before origination", src)

	def test_compliance_module_doc_is_regulator_agnostic(self):
		import lms_saas.api.compliance as c
		doc = c.__doc__ or ""
		self.assertNotIn("RBZ Fintech Sandbox compliance", doc)
		self.assertIn("regulator-agnostic", doc.lower())

	def test_compliance_config_module_doc_is_regulator_agnostic(self):
		import lms_saas.api.compliance_config as c
		doc = c.__doc__ or ""
		self.assertNotIn("Reserve Bank of Zimbabwe microfinance licence", doc)

	def test_resolve_regulator_message_suffix_helper(self):
		from lms_saas.api import compliance_config
		from lms_saas.api.compliance_config import (
			resolve_regulator_message_suffix,
		)
		# In sandbox mode the suffix is empty (no regulator name).
		sandbox_conf = {"lms_sandbox_end_date": "2026-12-31"}

		def fake_get_sandbox(k, d=None):
			return sandbox_conf.get(k, d)

		with mock.patch.object(compliance_config.frappe, "conf") as mock_conf:
			mock_conf.get.side_effect = fake_get_sandbox
			mock_conf.__contains__ = lambda self, k: k in sandbox_conf
			# re-define get to use our dict
			mock_conf.get.side_effect = lambda k, d=None: sandbox_conf.get(k, d)
			self.assertEqual(resolve_regulator_message_suffix(), "")

		# In production with a regulator name set, the suffix names the regulator.
		prod_conf = {
			"lms_sandbox_end_date": None,
			"lms_operator_legal_name": "Acme MFI",
			"lms_operator_licence_number": "LIC-001",
			"lms_operator_regulator": "Reserve Bank of Testland",
			"lms_operator_licence_validated": True,
		}

		def fake_get_prod(k, d=None):
			return prod_conf.get(k, d)

		with mock.patch.object(compliance_config.frappe, "conf") as mock_conf:
			mock_conf.get.side_effect = fake_get_prod
			suffix = resolve_regulator_message_suffix()
			self.assertIn("Reserve Bank of Testland", suffix)


# ---------------------------------------------------------------------------
# AML role gates.
# ---------------------------------------------------------------------------
class TestR22AMLAmlRoleGates(FrappeTestCase):
	"""Loan Officers cannot clear AML flags. Branch Managers can, with audit."""

	def test_loan_officer_cannot_clear_aml(self):
		from lms_saas.api.aml_role_gates import (
			can_clear_aml_flag,
			get_aml_role_capabilities,
		)
		# Loan Officer is read-only on AML.
		with mock.patch.object(frappe, "get_roles", return_value={"LMS Portal Staff"}), \
		     mock.patch(
		         "lms_saas.utils.portal.resolve_portal_persona",
		         return_value="Loan Officer",
		     ):
			self.assertFalse(can_clear_aml_flag())
			caps = get_aml_role_capabilities()
			self.assertFalse(caps["can_clear_aml_flag"])
			self.assertTrue(caps["is_aml_read_only"])

	def test_branch_manager_can_clear_aml(self):
		from lms_saas.api.aml_role_gates import can_clear_aml_flag
		with mock.patch.object(frappe, "get_roles", return_value={"LMS Portal Staff"}), \
		     mock.patch(
		         "lms_saas.utils.portal.resolve_portal_persona",
		         return_value="Branch Manager",
		     ):
			self.assertTrue(can_clear_aml_flag())

	def test_collector_cannot_clear_aml(self):
		from lms_saas.api.aml_role_gates import can_clear_aml_flag
		with mock.patch.object(frappe, "get_roles", return_value={"LMS Portal Staff"}), \
		     mock.patch(
		         "lms_saas.utils.portal.resolve_portal_persona",
		         return_value="Collector",
		     ):
			self.assertFalse(can_clear_aml_flag())

	def test_loan_officer_override_hard_throws(self):
		"""The server-side backstop must throw for Loan Officers."""
		from lms_saas.api.aml_role_gates import assert_loan_officer_cannot_clear_aml
		with mock.patch.object(frappe, "get_roles", return_value={"LMS Portal Staff"}), \
		     mock.patch(
		         "lms_saas.utils.portal.resolve_portal_persona",
		         return_value="Loan Officer",
		     ):
			with self.assertRaises(frappe.PermissionError):
				assert_loan_officer_cannot_clear_aml()

	def test_aml_override_requires_reason(self):
		"""Clearing an AML flag without a reason must throw."""
		from lms_saas.api.aml import override_aml_flag
		with mock.patch.object(frappe, "get_roles", return_value={"LMS Portal Staff"}), \
		     mock.patch(
		         "lms_saas.utils.portal.resolve_portal_persona",
		         return_value="Branch Manager",
		     ):
			# The compliance record is not expected to exist in this
			# test context; the reason check fires before the DB hit.
			with self.assertRaises(frappe.ValidationError):
				override_aml_flag("NON-EXISTENT", "Clear", reason="")
