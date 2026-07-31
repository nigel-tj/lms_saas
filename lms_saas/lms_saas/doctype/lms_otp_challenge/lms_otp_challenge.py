# Copyright (c) 2026, lms_saas and contributors
# License: MIT

"""LMS OTP Challenge — one-time code with bounded attempts + TTL.

Used by ``lms_saas.api.integrations.twilio._verify.send_otp`` and
``verify_otp``. The plain code is never stored — only
``SHA256(salt + plain)``. Match uses ``hmac.compare_digest`` so a timing
attack cannot extract a one-byte-at-a-time read of the correct prefix.

Lifecycle:
  - ``send_otp`` writes a fresh row with status='Open'.
  - ``verify_otp`` increments ``attempts`` and flips status to 'Matched'
    on success or 'Locked' once ``max_attempts`` (from site_config) is
    reached.
  - Time-based expiry: any ``verify_otp`` call after ``expires_at``
    flips status='Expired' (the row is still auditable).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


def _hash(salt_hex: str, code: str) -> str:
	"""Return SHA256(salt_bytes + utf8_code) as hex."""
	salt = bytes.fromhex(salt_hex)
	return hashlib.sha256(salt + code.encode("utf-8")).hexdigest()


def _gen_salt() -> str:
	return secrets.token_hex(16)


def _gen_code(length: int) -> str:
	"""Numeric OTP, leading zeros preserved, never starts with '0' for UX."""
	return f"{secrets.randbelow(10**length):0{length}d}"


class LMSOTPChallenge(Document):
	"""Bounded OTP challenge; code is never persisted in plaintext.

	Match-result helpers live on the ``verify_otp`` controller at the
	provider level; this class only defines the model layout.
	"""

	@staticmethod
	def make_hash(salt_hex: str, code: str) -> str:
		return _hash(salt_hex, code)

	@staticmethod
	def make_salt() -> str:
		return _gen_salt()

	@staticmethod
	def make_code(length: int = 6) -> str:
		return _gen_code(length)

	@staticmethod
	def constant_time_equal(hex_a: str, hex_b: str) -> bool:
		return hmac.compare_digest(hex_a, hex_b)

	def on_update(self):
		# Status transitions from the verify endpoint set a flag so
		# the no-edit-after-insert guard does not block them.
		if getattr(self.flags, "lms_otp_callback_update", False):
			return
		if not self.flags.in_insert:
			frappe.throw(
				"LMS OTP Challenge rows are append-only. "
				"Append a new row with status='Cancelled' instead."
			)

	def on_trash(self):
		frappe.throw(
			"LMS OTP Challenge rows cannot be deleted. "
			"Append a new row with status='Cancelled' instead."
		)

	def is_expired(self) -> bool:
		if not self.expires_at:
			return False
		return now_datetime() >= self.expires_at

	def is_locked_out(self, max_attempts: int) -> bool:
		return self.status == "Locked" or (self.attempts or 0) >= max_attempts
