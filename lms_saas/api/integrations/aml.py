"""Integration API — AML."""

import frappe

from lms_saas.utils.api_auth import validate_api_key


@frappe.whitelist()
def screen_customer(customer: str, force: int = 0):
	validate_api_key()
	compliance = frappe.db.get_value("LMS Borrower Compliance", {"customer": customer}, "name")
	if not compliance:
		frappe.throw("No compliance record")
	from lms_saas.api.aml import screen_borrower_compliance

	result = screen_borrower_compliance(compliance, force=bool(force))
	status = frappe.db.get_value("LMS Borrower Compliance", compliance, "aml_status")
	return {"customer": customer, "aml_status": status, "provider": result}
