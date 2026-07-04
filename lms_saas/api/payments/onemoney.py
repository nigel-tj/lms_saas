"""OneMoney payment adapter."""

from __future__ import annotations

import hashlib
import hmac

import frappe

from lms_saas.api.payments.base import BasePaymentAdapter


class OneMoneyAdapter(BasePaymentAdapter):
	provider_code = "onemoney"

	def initiate(self, intent: dict) -> dict:
		base_url = frappe.conf.get("lms_onemoney_api_url", "")
		external_ref = intent.get("name") or frappe.generate_hash(length=12)
		return {
			"external_ref": external_ref,
			"redirect_url": f"{base_url}/checkout?ref={external_ref}&amount={intent.get('amount')}",
			"raw": {"provider": self.provider_code},
		}

	def verify_webhook(self, payload: dict, headers: dict) -> dict | None:
		secret = frappe.conf.get("lms_onemoney_webhook_secret") or ""
		if secret:
			sig = headers.get("X-OneMoney-Signature") or ""
			body = frappe.request.get_data() if frappe.request else b""
			expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
			if not hmac.compare_digest(sig, expected):
				return None
		status = (payload.get("status") or "").lower()
		mapped = "Confirmed" if status in ("success", "completed", "paid") else "Failed"
		return {
			"external_ref": payload.get("reference") or payload.get("transaction_id"),
			"status": mapped,
			"amount": payload.get("amount"),
		}

	def fetch_settlement(self, external_ref: str) -> dict | None:
		return None
