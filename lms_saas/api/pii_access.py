"""PII access helpers.

R18-4: every reveal of borrower PII (mobile / address / ID number) must
create an audit-log row so the operator can prove to the regulator that
no card was abused. The default is to MASK the value; the
``reveal=1`` query param opts in to the cleartext, and that opts-in also
calls ``record_pii_access``.
"""

from __future__ import annotations

import frappe


def mask_mobile(value: str) -> str:
	"""Return a UI-safe masked version of a MSISDN.

	Example: ``+27710000001`` -> ``+277 …001``. Falls back to ``•••`` if
	the value is empty / unparseable.
	"""
	if not value:
		return "•••"
	s = str(value).strip()
	digits = "".join(c for c in s if c.isdigit())
	if len(digits) < 4:
		return "•••"
	# Country code (if starts with + or first 1-3 digits) + last 3.
	if s.startswith("+"):
		return s[:3] + " …" + digits[-3:]
	return digits[:3] + " …" + digits[-3:]


def record_pii_access(reference_doctype: str, reference_name: str, field: str, reason: str = "") -> None:
	"""Insert a row into LMS PII Access Log. Never raises — logging must not break the page.

	Only System Manager / LMS Admin can read the log. The PII value itself
	is intentionally NOT stored in the log — only the metadata of who saw
	what for whom.
	"""
	try:
		frappe.get_doc({
			"doctype": "LMS PII Access Log",
			"event_time": frappe.utils.now_datetime(),
			"event_user": frappe.session.user,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"field": field,
			"reason": (reason or "")[:280],
		}).insert(ignore_permissions=True)
	except Exception as exc:  # noqa: BLE001
		frappe.log_error(f"record_pii_access failed: {exc}")
