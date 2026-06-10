import frappe
from frappe.tests.utils import FrappeTestCase


class TestComplianceGates(FrappeTestCase):
	def test_aml_config_defaults(self):
		from lms_saas.api.aml import _aml_config

		cfg = _aml_config()
		self.assertIn("enabled", cfg)
		self.assertIn("require_clear", cfg)

	def test_aml_normalize_status(self):
		from lms_saas.api.aml import _normalize_aml_status

		self.assertEqual(_normalize_aml_status("pass"), "Clear")
		self.assertEqual(_normalize_aml_status("Flagged"), "Flagged")

	def test_decisioning_compare(self):
		from lms_saas.api.decisioning import _compare

		self.assertTrue(_compare(700, ">=", 600))
		self.assertFalse(_compare(500, ">=", 600))

	def test_payment_adapters_registered(self):
		from lms_saas.api.payments.service import ADAPTERS

		self.assertIn("ecocash", ADAPTERS)
		self.assertIn("onemoney", ADAPTERS)
		self.assertIn("bank_transfer", ADAPTERS)
