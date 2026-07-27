# Copyright (c) 2026, lms_saas and contributors
# License: MIT

"""LMS PII Access Log controller.

Append-only audit table for every reveal of borrower PII (mobile, address,
ID number). The DocType is JSON-defined; this controller is intentionally
minimal — heavy lifting happens in ``lms_saas.api.pii_access`` which is
called from the field-collection run-sheet reveal flow.
"""

from frappe.model.document import Document


class LMSPIIAccessLog(Document):
	"""Audit row for a single PII reveal event.

	Fields are populated by ``lms_saas.api.pii_access.record_pii_access``.
	Never edit manually — these rows back the RBZ sandbox-exit evidence pack.
	"""

	pass

