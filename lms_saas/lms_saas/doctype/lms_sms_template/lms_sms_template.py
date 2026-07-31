# Copyright (c) 2026, lms_saas and contributors
# License: MIT

"""LMS SMS Template — approved SMS copy with placeholder substitution.

Templates are admin-only at write-time. The controller's ``render``
helper applies ``{{var}}`` substitution with strict per-template variable
allow-listing so a misconfigured call site can't inject arbitrary text.

Used by ``lms_saas.api.integrations.twilio._send`` for every non-OTP send
that wants template-based copy, and surfaced through
``lms_saas.api.integrations.twilio_api.send_sms`` when a
``template`` argument is supplied.
"""

from __future__ import annotations

import re

import frappe
from frappe.model.document import Document

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}", re.IGNORECASE)


class LMSSMSTemplate(Document):
	"""Approved SMS copy. ``body`` is interpolated at send time."""

	def render(self, variables: dict | None = None) -> str:
		"""Render the template with the supplied variables.

		Unknown placeholders are left intact rather than dropped silently —
		that way a misspelled variable surfaces in the LMS SMS Send Log's
		``body_preview`` and is debuggable in CI without logging PII.
		"""
		variables = variables or {}
		declared = {row.variable_name for row in (self.variables_table or [])}
		missing = [p for p in _PLACEHOLDER_RE.findall(self.body or "") if p not in declared and p not in variables]

		def _sub(match):
			name = match.group(1)
			value = variables.get(name, match.group(0))
			return str(value)

		rendered = _PLACEHOLDER_RE.sub(_sub, self.body or "")

		if missing:
			frappe.logger().info(
				"LMS SMS template %s render used undeclared placeholders: %s",
				self.name,
				", ".join(sorted(set(missing))),
			)
		return rendered
