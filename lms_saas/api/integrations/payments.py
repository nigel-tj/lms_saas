"""Integration API — payments."""

import frappe

from lms_saas.utils.api_auth import validate_api_key


@frappe.whitelist()
def create_intent(loan: str, amount: float, provider_code: str = "ecocash"):
	validate_api_key()
	from lms_saas.api.payments.service import create_payment_intent

	return create_payment_intent(loan=loan, amount=amount, provider_code=provider_code)


@frappe.whitelist()
def list_providers():
	validate_api_key()
	from lms_saas.api.payments.service import get_payment_config

	return get_payment_config()
