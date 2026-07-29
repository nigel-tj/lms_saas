# Copyright (c) 2026, lms_saas and contributors
# License: MIT

"""LMS PII Access Log controller.

Append-only audit table for every reveal of borrower PII (mobile, address,
ID number). The DocType is JSON-defined; this controller hardens the
``on_update`` and ``on_trash`` paths so no role (including System Manager)
can edit or delete a row — even if the DocType permission block is
loosened by mistake. R21-H1 mirrors the R20-H1 fix on LMS Audit Event.
"""

import frappe
from frappe.model.document import Document


class LMSPIIAccessLog(Document):
	"""Audit row for a single PII reveal event.

	Fields are populated by ``lms_saas.api.pii_access.record_pii_access``
	(strict variant is used on every reveal path — R20-M3). Never edit or
	delete manually — these rows back the RBZ sandbox-exit evidence pack.
	"""

	def on_update(self):
		if not self.flags.in_insert:
			frappe.throw(
				"LMS PII Access Log records are immutable. "
				"Append a new row with field='AUDIT_RETRACTED' instead."
			)

	def on_trash(self):
		# R21-H1: hard-throw even for System Manager. The PII reveal trail
		# is the regulator's audit evidence — deletion must be impossible
		# for every role. Mirrors the R20-H1 fix on LMS Audit Event.
		frappe.throw(
			"LMS PII Access Log records are immutable and cannot be deleted. "
			"If a row must be retracted for legal reasons, append a "
			"LMS PII Access Log with field='AUDIT_RETRACTED' instead."
		)