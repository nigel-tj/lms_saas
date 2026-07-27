"""Shared label / placeholder helpers for API responses.

R18-3: replace the hard-coded `"Unassigned"` placeholder that leaked into
officer performance charts and reports. Branch managers and regulators do
not need to see an internal null label — they need to see what work is
genuinely missing an owner vs. what is just being onboarded.

R18-13: defensively sanitise user-provided strings used as chart / table
labels. Frappe allows HTML in some free-text fields, so we strip control
characters and angle brackets before the value hits Chart.js (which
otherwise renders them as raw canvas text — not an XSS surface, but
visually confusing for regulators).
"""

from __future__ import annotations

import re

from typing import Optional

import frappe


# Display labels for "loan has no custom_loan_officer set".
NEEDS_ASSIGNMENT_DPD_THRESHOLD = 30
UNASSIGNED_DPD_LATE = "⚠ Needs assignment"
UNASSIGNED_DPD_EARLY = "🕒 Awaiting officer"

# Strip angle brackets and control characters so a label like
# `<img src=x onerror=alert(1)>` becomes `(img src=x onerror=alert(1))`
# when used as a chart label.
_LABEL_SANITISE_RE = re.compile(r"[<>]|[\x00-\x08\x0b-\x1f\x7f]")


def _sanitise_label(value) -> str:
	"""Return a safe plain-text version of an arbitrary label string."""
	if value is None:
		return ""
	s = str(value).strip()
	s = _LABEL_SANITISE_RE.sub("", s)
	return s.strip()


def officer_label(officer_name: Optional[str], days_past_due: Optional[int] = None) -> str:
	"""Return the chart-friendly label for a loan officer.

	- A real officer name → returned unchanged (after sanitisation).
	- An empty / None officer and DPD > threshold → "⚠ Needs assignment".
	- Otherwise → "🕒 Awaiting officer".

	Use this anywhere a chart series or table row would otherwise render
	`"Unassigned"` to the user.
	"""
	clean = _sanitise_label(officer_name)
	if clean:
		return clean
	try:
		dpd = int(days_past_due or 0)
	except (TypeError, ValueError):
		dpd = 0
	if dpd > NEEDS_ASSIGNMENT_DPD_THRESHOLD:
		return UNASSIGNED_DPD_LATE
	return UNASSIGNED_DPD_EARLY


def branch_label(branch_name: Optional[str]) -> str:
	"""Return a chart-friendly label for a missing branch.

	R18-3 follow-on: stop leaking "Unassigned" as a branch label.
	"""
	clean = _sanitise_label(branch_name)
	if clean:
		return clean
	return "⚠ No branch"


def safe_chart_label(value: Optional[str]) -> str:
	"""Sanitise an arbitrary string before it is used as a chart / tooltip /

	aria-label source. Use this at the data-shape boundary when a label
	originates from a Customer or Employee name field that may contain HTML.
	"""
	return _sanitise_label(value)
