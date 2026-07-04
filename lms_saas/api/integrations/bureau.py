"""Integration API — credit bureau."""

import frappe

from lms_saas.utils.api_auth import validate_api_key


@frappe.whitelist()
def score_applicant(customer: str):
	validate_api_key()
	compliance = frappe.db.get_value("LMS Borrower Compliance", {"customer": customer}, "name")
	if not compliance:
		frappe.throw("No compliance record")
	from lms_saas.api.underwriting import _bureau_config

	cfg = _bureau_config()
	return {"customer": customer, "compliance": compliance, "config": cfg}
