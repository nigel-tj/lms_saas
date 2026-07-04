# Copy module — single source of truth for user-facing strings.
# Keys are namespaced by feature. Variables use {curly_braces} syntax.

import json

import frappe

COPY = {
	# Pay flow
	"pay.success": "Payment of {amount} recorded.",
	"pay.error": "We couldn't reach {provider}. Check your signal and try again.",
	"pay.copied": "Reference copied to clipboard.",
	"pay.initiated": "Payment initiated. Reference: {reference}",

	# Loan
	"loan.overdue_soft": "This payment is {days} days late. We can help you get back on track — call us at {phone}.",
	"loan.paid_off": "Loan paid off. Thank you.",
	"loan.next_due": "Next payment due {date} · {amount}",

	# Account
	"account.welcome": "Welcome, {name}. When you're ready, your first loan is three minutes away.",
	"account.empty": "No loans yet. Apply for one to see your dashboard here.",

	# Wizard
	"wizard.select_product": "Please select a loan product.",
	"wizard.enter_amount": "Please enter a loan amount.",
	"wizard.amount_too_high": "Amount exceeds the maximum for this product ({max}).",
	"wizard.consent_required": "Please confirm consent to proceed.",
	"wizard.submitted": "Application submitted. Reference: {reference}",
	"wizard.submit_failed": "Submission failed. Please try again.",

	# Officer / Manager
	"officer.empty_pipeline": "No applications waiting. New leads will appear here.",
	"manager.zero_portfolio": "No loans are active yet. As soon as your team disburses a loan, your portfolio will appear here.",
	"manager.review": "Review and approve",
	"manager.approve": "Approve",
	"manager.reject": "Reject",

	# Collector
	"collector.offline_saved": "Saved on this device. Will sync when you're back online.",
	"collector.synced": "Synced {when}",
	"collector.sync_failed": "Sync failed. {count} records will retry when you're back online.",
	"collector.collected": "Collected {amount} from {customer}.",

	# Generic
	"generic.loading": "Loading…",
	"generic.error": "Something went wrong. Please try again.",
	"generic.save": "Save",
	"generic.cancel": "Cancel",
	"generic.confirm": "Confirm",
	"generic.dismiss": "Dismiss",
	"generic.try_again": "Try again",
	"generic.search": "Search…",
	"generic.no_data": "No data yet",
}

DEFAULT_LOCALE = "en"


def _fallback_key(key):
	"""Map 'foo.bar.baz' -> 'foo.bar' (last segment removed) recursively."""
	parts = key.split(".")
	while len(parts) > 1:
		parts.pop()
		candidate = ".".join(parts)
		if candidate in COPY:
			return candidate
	return key


@frappe.whitelist()
def get(key, vars=None, locale=None):
	"""Render a copy string with optional variables.

	Falls back to English if the key is missing.
	"""
	from frappe import _
	text = COPY.get(key) or COPY.get(_fallback_key(key)) or key
	vars_dict = _parse_vars(vars)
	if vars_dict:
		try:
			return _(text).format(**vars_dict)
		except Exception:
			return text
	return _(text)


def _parse_vars(vars):
	if not vars:
		return None
	if isinstance(vars, dict):
		return vars
	if isinstance(vars, str):
		try:
			parsed = json.loads(vars)
			return parsed if isinstance(parsed, dict) else None
		except Exception:
			return None
	return None
