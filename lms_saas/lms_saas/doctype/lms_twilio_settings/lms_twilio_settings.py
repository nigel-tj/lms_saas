# Copyright (c) 2026, lms_saas and contributors
# License: MIT

"""LMS Twilio Settings — single DocType for the Twilio SMS provider.

Stores the Twilio Account SID, encrypted Auth Token (via
``frappe.utils.password``), default sender phone number, status-callback
URL, and the optional Twilio Verify Service SID.

The controller is responsible for:
  - **on_update**: validating the SID + phone format, auto-populating the
    callback URLs from the current request host (when unset), and syncing
    ``enabled`` to ``site_config.lms_twilio_enabled`` so runtime code can
    read it without a DB query.
  - **Auth-token caching**: the auth token is stored encrypted under the
    key ``lms_twilio_auth_token`` in Frappe's Password table. API callers
    never see the decrypted value — they only get a boolean ``enabled``
    flag plus a redacted Account SID.

R22 immutability policy mirrors R20-H1 / R21-H1: rows in
``LMS Twilio Settings`` exist only as a single — System Manager can edit,
but no delete (issingle means there is no list view to wipe in bulk).
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.password import set_encrypted_password

PASSWORD_KEY = "lms_twilio_auth_token"

# Twilio SID formats:
#   - Account SID:    literal 'AC' prefix + 32 lowercase hex/alnum (34 chars total).
#   - API Key SID:    literal 'SK' prefix + 32 lowercase hex/alnum (34 chars total).
# Both are accepted here so operators can paste either. We only verify the
# canonical Twilio shape; we do not check digit characters against any
# internal Twilio allow-list because the canonical examples include mixed
# alpha+digits in the body.
_ACCOUNT_SID_RE = re.compile(r"^(?:AC|SK)[a-f0-9]{32}$")
# Twilio Verify SID format: literal 'VA' prefix + 32 hex chars.
_VERIFY_SID_RE = re.compile(r"^VA[a-f0-9]{32}$")
# E.164: leading + then 7-15 digits.
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


class LMSTwilioSettings(Document):
	"""Twilio SMS provider configuration. Singleton — ``issingle=1``."""

	def validate(self):
		self._validate_sid()
		self._validate_sender()
		self._validate_verify_sid()
		self._populate_callback_urls()

	def on_update(self):
		# Mirror enabled state to site_config so runtime checks (which
		# run before the DB is necessarily available in API paths) can
		# use ``frappe.conf.lms_twilio_enabled``.
		try:
			frappe.conf["lms_twilio_enabled"] = bool(self.enabled)
		except Exception:  # noqa: BLE001
			pass

		# If a fresh auth token was entered, persist it encrypted.
		# The Password field returns the plaintext on read; on save it
		# should have been entered by the user. We re-encrypt via
		# `set_password` so the value never leaves this controller in
		# plaintext past this point.
		token = getattr(self, "auth_token", None)
		if token:
			set_encrypted_password(PASSWORD_KEY, "", token)

	# ------------------------------------------------------------------
	# Validators
	# ------------------------------------------------------------------
	def _validate_sid(self):
		sid = (self.account_sid or "").strip()
		if not self.enabled:
			return
		if not sid:
			frappe.throw(_("Account SID is required when Twilio is enabled."))
		if not _ACCOUNT_SID_RE.match(sid):
			frappe.throw(
				_(
					"Account SID must start with 'AC' (Account SID) or 'SK' (API Key SID) "
					"and be 34 characters of lowercase hex. Got prefix '{0}'."
				).format(sid[:4] or "(empty)")
			)

	def _validate_sender(self):
		if not self.enabled:
			return
		from_number = (self.default_from_number or "").strip()
		if from_number and not _E164_RE.match(from_number):
			frappe.throw(
				_("Default Sender must be in E.164 format, e.g. +15555550100.")
			)

	def _validate_verify_sid(self):
		verify_sid = (self.verify_service_sid or "").strip()
		if not verify_sid:
			return
		if not _VERIFY_SID_RE.match(verify_sid):
			frappe.throw(
				_("Verify Service SID must start with 'VA' followed by 32 hex chars.")
			)

	def _populate_callback_urls(self):
		"""Auto-populate callback URLs from the request host when empty."""
		try:
			host = frappe.request.host if frappe.request else ""
		except Exception:  # noqa: BLE001
			host = ""
		if not host:
			return
		base = f"https://{host}/api/method"
		if not (self.status_callback_url or "").strip():
			self.status_callback_url = (
				f"{base}/lms_saas.api.integrations.twilio_api.status"
			)
		if not (self.inbound_webhook_url or "").strip():
			self.inbound_webhook_url = (
				f"{base}/lms_saas.api.integrations.twilio_api.inbound"
			)
