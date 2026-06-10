import frappe
from frappe.tests.utils import FrappeTestCase


class TestPortalPermissions(FrappeTestCase):
	def test_portal_api_surface(self):
		from lms_saas.api import portal

		for fn in (
			"get_my_loans",
			"submit_loan_application",
			"upload_kyc_document",
			"initiate_repayment",
			"get_apply_context",
		):
			self.assertTrue(callable(getattr(portal, fn, None)), fn)

	def test_guest_blocked_from_portal(self):
		from lms_saas.api.portal import _require_customer

		frappe.set_user("Guest")
		self.assertRaises(frappe.PermissionError, _require_customer)
