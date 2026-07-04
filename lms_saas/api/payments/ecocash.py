"""EcoCash payment adapter (config-driven)."""

from __future__ import annotations

import hashlib
import hmac

import frappe

from lms_saas.api.payments.base import BasePaymentAdapter


class EcoCashAdapter(BasePaymentAdapter):
	provider_code = "ecocash"

	def initiate(self, intent: dict) -> dict:
		cfg = _provider_config(self.provider_code)
		base_url = cfg.get("api_url") or frappe.conf.get("lms_ecocash_api_url", "")
		external_ref = intent.get("name") or frappe.generate_hash(length=12)
		callback = frappe.utils.get_url(
			f"/api/method/lms_saas.api.payments.service.handle_payment_webhook?provider=ecocash"
		)
		return {
			"external_ref": external_ref,
			"redirect_url": f"{base_url}/pay?ref={external_ref}&amount={intent.get('amount')}&callback={callback}",
			"raw": {"provider": self.provider_code, "mode": "redirect"},
		}

	def verify_webhook(self, payload: dict, headers: dict) -> dict | None:
		secret = frappe.conf.get("lms_ecocash_webhook_secret") or ""
		if secret:
			sig = headers.get("X-EcoCash-Signature") or headers.get("X-Signature") or ""
			body = frappe.request.get_data() if frappe.request else b""
			expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
			if not hmac.compare_digest(sig, expected):
				return None
		status = (payload.get("status") or "").lower()
		if status not in ("success", "completed", "paid"):
			return {"external_ref": payload.get("reference"), "status": "Failed", "amount": payload.get("amount")}
		return {
			"external_ref": payload.get("reference") or payload.get("external_ref"),
			"status": "Confirmed",
			"amount": payload.get("amount"),
		}

	def fetch_settlement(self, external_ref: str) -> dict | None:
		return None


def _provider_config(code: str) -> dict:
	row = frappe.db.get_value(
		"LMS Payment Provider",
		{"provider_code": code, "enabled": 1},
		["api_url", "merchant_id"],
		as_dict=True,
	)
	return row or {}
