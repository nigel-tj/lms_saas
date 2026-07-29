# Copyright (c) 2026, lms_saas and contributors
# License: MIT

"""LMS Incident Log controller.

Append-only audit table for every operational, technical, cyber-security,
data-breach, fraud, and customer-complaint incident. R22-C1 mirrors the
R20-H1 / R21-H1 immutability pattern: System Manager cannot edit or
delete a row once written — the controller hard-throws on update and
trash, and the DocType permission block has been tightened to
read + create + export + report only.

Incidents — especially Data Breach, Fraud, and Cyber Security — are
regulator-facing evidence. A regulator's first incident-response question
is "show me every Data Breach you recorded in the last 12 months". The
row must be unmutable and undeletable from the moment it is written.
"""

import frappe
from frappe.model.document import Document


class LMSIncidentLog(Document):
	"""Immutable incident record.

	Fields are populated by the incident-reporting workflows. Never edit
	or delete manually — these rows back the regulator's incident-response
	walk-through. To retract a row for a legitimate reason, append a new
	``LMS Incident Log`` with ``incident_type='Operational'``,
	``title='AUDIT_RETRACTED: <original-name>'`` and reference the
	original incident in the description.
	"""

	def on_update(self):
		if not self.flags.in_insert:
			frappe.throw(
				"LMS Incident Log records are immutable. "
				"Append a new 'AUDIT_RETRACTED' row instead."
			)

	def on_trash(self):
		# R22-C1: hard-throw even for System Manager. The incident log
		# is the regulator's IR evidence — deletion must be impossible
		# for every role. Mirrors R20-H1 (LMS Audit Event) and R21-H1
		# (LMS PII Access Log).
		frappe.throw(
			"LMS Incident Log records are immutable and cannot be deleted. "
			"If a row must be retracted, append a new LMS Incident Log with "
			"title='AUDIT_RETRACTED: <original-name>' instead."
		)
