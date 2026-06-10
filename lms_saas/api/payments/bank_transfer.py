"""Bank transfer adapter — virtual reference generation."""

from __future__ import annotations

import frappe

from lms_saas.api.payments.base import BasePaymentAdapter


class BankTransferAdapter(BasePaymentAdapter):
	provider_code = "bank_transfer"

	def initiate(self, intent: dict) -> dict:
		prefix = frappe.conf.get("lms_bank_transfer_ref_prefix", "LMS")
		external_ref = f"{prefix}-{intent.get('name', frappe.generate_hash(length=8))}"
		bank_details = {
			"account_name": frappe.conf.get("lms_bank_account_name", ""),
			"account_number": frappe.conf.get("lms_bank_account_number", ""),
			"bank_name": frappe.conf.get("lms_bank_name", ""),
			"reference": external_ref,
		}
		return {
			"external_ref": external_ref,
			"redirect_url": "",
			"raw": bank_details,
			"instructions": bank_details,
		}

	def verify_webhook(self, payload: dict, headers: dict) -> dict | None:
		return {
			"external_ref": payload.get("reference"),
			"status": "Confirmed" if payload.get("confirmed") else "Pending",
			"amount": payload.get("amount"),
		}

	def fetch_settlement(self, external_ref: str) -> dict | None:
		return None
