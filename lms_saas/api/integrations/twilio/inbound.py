"""Inbound SMS keyword parser.

Twilio's inbound webhook POSTs the borrower replies with at minimum
``From`` (E.164) and ``Body`` (free text). Mapping that to operator
actions is small and non-Frappe-coupled, so we keep it pure.
"""

from __future__ import annotations

from lms_saas.api.integrations.twilio._settings import (
    get_help_keywords,
    get_opt_keywords,
    get_optin_keywords,
)


def classify_keyword(body: str) -> str:
	"""Return one of: ``optout``, ``optin``, ``help``, ``unknown``.

	Comparison is case-insensitive and trims whitespace; multi-word
	bodies (e.g. ``STOP all``) match as long as the first token matches a
	known keyword.
	"""
	if not body:
		return "unknown"
	head = body.strip().split(" ", 1)[0].strip().lower()
	if head in get_opt_keywords():
		return "optout"
	if head in get_optin_keywords():
		return "optin"
	if head in get_help_keywords():
		return "help"
	return "unknown"


def parse_inbound_keyword(body: str, from_number: str | None = None) -> dict:
	"""Return ``{keyword: 'optout'|'optin'|'help'|'unknown', raw: body}``."""
	return {"keyword": classify_keyword(body), "raw": body, "from": from_number}


def twiml_response(text: str = "") -> str:
	"""Wrap a text response in Twilio TwiML.

	The endpoint returns this to Twilio, which forwards it as the reply
	for the inbound number. We don't drive the reply body off the
	borrower's text — we always reply with a non-PII operator-controlled
	string from the LMS admin, never from the user input.
	"""
	escaped = (
		text.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
	)
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		"<Response>"
		f"<Message>{escaped}</Message>"
		"</Response>"
	)
