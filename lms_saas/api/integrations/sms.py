"""Integration API — SMS."""

import frappe

from lms_saas.utils.api_auth import validate_api_key


@frappe.whitelist()
def send_sms(to_num: str, message: str):
	validate_api_key()
	from lms_saas.api.notifications import dispatch_sms_gateway

	ok = dispatch_sms_gateway(to_num, message)
	return {"sent": ok}
