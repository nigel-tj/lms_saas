"""Base payment adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BasePaymentAdapter(ABC):
	provider_code: str = ""

	@abstractmethod
	def initiate(self, intent: dict) -> dict:
		"""Create provider-side payment. Returns {redirect_url, external_ref, raw}."""

	@abstractmethod
	def verify_webhook(self, payload: dict, headers: dict) -> dict | None:
		"""Validate webhook and return {external_ref, status, amount} or None."""

	@abstractmethod
	def fetch_settlement(self, external_ref: str) -> dict | None:
		"""Poll provider for settlement status."""
