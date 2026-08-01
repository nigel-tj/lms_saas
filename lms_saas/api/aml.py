"""AML/CFT screening — config-driven external provider hook.

ARCHITECTURE NOTE:
    AML/CFT (Anti-Money Laundering / Countering Financing of Terrorism)
    is enforced as a POLICY LAYER on top of the general-purpose loan
    software. The screening provider is configured by the operator via
    site_config (``lms_aml_url``, ``lms_aml_enabled``); the operator's
    own regulator requirements are surfaced as audit-trail evidence but
    the code base does not name a specific regulator.

    AML/CFT is a hard gate before origination: a Loan Application
    cannot be submitted unless the borrower's AML status is "Clear".
    The provider call is idempotent (cached on the compliance record)
    so re-submissions don't re-charge the screening fee.
"""

from __future__ import annotations

import json

import frappe
import requests

DEFAULT_TIMEOUT = 15
BLOCKED_STATUSES = frozenset({"Flagged", "Rejected"})


def _aml_config():
	"""AML provider settings from site_config.

	The canonical fail-CLOSED default is owned by
	``lms_saas.api.compliance_config.PRODUCTION_DEFAULTS`` (and flipped
	to fail-open in sandbox mode by ``get_effective_compliance_config``).
	Callers should use ``lms_saas.api.compliance_config.get_effective_compliance_config()``
	to resolve the operator-aware flag. This helper is kept as a
	lightweight accessor for the AML screen flow.
	"""
	from lms_saas.api.compliance_config import get_effective_compliance_config

	conf = frappe.conf
	effective = get_effective_compliance_config()
	return {
		"enabled": bool(conf.get("lms_aml_enabled", False)),
		"url": conf.get("lms_aml_url"),
		"block_on_error": bool(effective.get("lms_aml_block_on_error", True)),
		"timeout": int(conf.get("lms_aml_timeout", DEFAULT_TIMEOUT)),
		"require_clear": bool(conf.get("lms_aml_require_clear", True)),
	}


def screen_borrower_compliance(compliance_name: str, *, force: bool = False) -> dict | None:
	"""Run AML screening for a compliance record. Returns provider payload or None if disabled."""
	cfg = _aml_config()
	if not cfg["enabled"] or not cfg["url"]:
		return None

	compliance = frappe.db.get_value(
		"LMS Borrower Compliance",
		compliance_name,
		["name", "customer", "national_id_number", "aml_status", "aml_screened_at"],
		as_dict=True,
	)
	if not compliance:
		return None

	if not force and compliance.aml_status in ("Clear", "Flagged", "Rejected") and compliance.aml_screened_at:
		return None

	national_id = compliance.national_id_number
	customer_name = frappe.db.get_value("Customer", compliance.customer, "customer_name")

	try:
		response = requests.post(
			cfg["url"],
			json={"id_number": national_id, "name": customer_name, "customer": compliance.customer},
			timeout=cfg["timeout"],
		)
		response.raise_for_status()
		data = response.json()
	except requests.exceptions.RequestException as exc:
		frappe.log_error(message=str(exc), title="LMS AML Provider Failure")
		_log_aml_incident(compliance_name, str(exc))
		if cfg["block_on_error"]:
			frappe.throw("AML screening service unavailable. Please retry later.")
		return None

	status = _normalize_aml_status(data.get("status") or data.get("aml_status") or "Pending")
	risk_level = data.get("risk_level") or data.get("risk") or "Unknown"
	provider_ref = data.get("reference") or data.get("provider_ref") or ""

	frappe.db.set_value(
		"LMS Borrower Compliance",
		compliance_name,
		{
			"aml_status": status,
			"aml_screened_at": frappe.utils.now_datetime(),
			"aml_provider_ref": provider_ref,
			"aml_risk_level": risk_level,
			"aml_details": json.dumps(data) if isinstance(data, dict) else str(data),
		},
		update_modified=False,
	)

	from lms_saas.api.compliance import write_audit_event

	write_audit_event(
		event_type="AML:Screened",
		reference_doctype="LMS Borrower Compliance",
		reference_name=compliance_name,
		details=f"status={status}, risk={risk_level}, ref={provider_ref}",
	)

	if status in BLOCKED_STATUSES:
		try:
			from lms_saas.api.webhooks import dispatch_webhook_event

			dispatch_webhook_event(
				"aml.flagged",
				{"compliance": compliance_name, "customer": compliance.customer, "status": status},
			)
		except Exception:
			pass

	return data


def _normalize_aml_status(raw: str) -> str:
	value = (raw or "Pending").strip().title()
	allowed = {"Clear", "Pending", "Flagged", "Rejected"}
	if value in allowed:
		return value
	if value.lower() in ("pass", "approved", "ok"):
		return "Clear"
	if value.lower() in ("fail", "block", "blocked"):
		return "Rejected"
	return "Pending"


@frappe.whitelist(allow_guest=False)
def override_aml_flag(compliance_name: str, new_status: str, reason: str) -> dict:
	"""Branch Manager override of an AML flag (false-positive review).

	R22 board hardening: the AML/CFT regime requires segregation of
	duties between the customer-facing staff (Loan Officer / Collector)
	who onboards the borrower and the reviewer who clears the flag.
	Only a Branch Manager (or higher) may invoke this. The override is
	written as a critical LMS Audit Event so the regulator can request
	"show me every AML override in the last quarter" and get a
	verifiable, attributable list.

	The new_status must be one of "Clear" (false-positive) or "Flagged"
	/ "Rejected" (confirmed after review). Setting to "Clear" without
	a reason is forbidden.

	Whitelisted (R32) so the Branch Manager portal can call this from
	the review modal. The role-gate check below is still the source of
	truth — Loan Officers calling this get a PermissionError.
	"""
	# Permission check via the role-gate module — keeps the AML/CFT
	# segregation-of-duties rule in one place.
	from lms_saas.api.aml_role_gates import assert_loan_officer_cannot_clear_aml

	assert_loan_officer_cannot_clear_aml()

	allowed = {"Clear", "Flagged", "Rejected"}
	if new_status not in allowed:
		frappe.throw(f"Invalid AML override status '{new_status}'.")
	if new_status == "Clear" and not (reason or "").strip():
		frappe.throw(
			"An override clearing an AML flag requires a written reason. "
			"The reason is recorded in LMS Audit Event."
		)

	old_status = frappe.db.get_value(
		"LMS Borrower Compliance", compliance_name, "aml_status"
	)
	frappe.db.set_value(
		"LMS Borrower Compliance",
		compliance_name,
		{
			"aml_status": new_status,
			"aml_screened_at": frappe.utils.now_datetime(),
			"aml_details": (
				(frappe.db.get_value("LMS Borrower Compliance", compliance_name, "aml_details") or "")
				+ f"\nMANUAL_OVERRIDE by {frappe.session.user} at {frappe.utils.now_datetime()}: "
				+ f"old_status={old_status} new_status={new_status} reason={reason}"
			),
		},
		update_modified=False,
	)

	from lms_saas.api.compliance import write_audit_event

	write_audit_event(
		event_type="AML:Override",
		reference_doctype="LMS Borrower Compliance",
		reference_name=compliance_name,
		details=(
			f"old_status={old_status} new_status={new_status} "
			f"reason={reason} reviewer={frappe.session.user}"
		),
		critical=True,
	)

	return {
		"compliance": compliance_name,
		"old_status": old_status,
		"new_status": new_status,
		"reason": reason,
	}


def on_compliance_after_insert(doc, method=None):
	"""Screen new borrowers when AML is enabled."""
	if frappe.flags.in_install or frappe.flags.in_migrate:
		return
	screen_borrower_compliance(doc.name)


def enforce_aml_on_origination(doc, method=None):
	"""Block loan application submit when AML is not clear.

	PRODUCTION-HARDENING (B5): AML screening is now REQUIRED by default
	(fail-closed). Previously, if `lms_aml_enabled` was False the check was
	skipped entirely, so a misconfigured site could originate loans for
	un-screened borrowers. Now, unless the site is explicitly in relaxed mode
	(`lms_compliance_relaxed=True`), AML must be enabled and the borrower must
	screen Clear before origination.
	"""
	if frappe.conf.get("lms_compliance_relaxed", False):
		# Relaxed/sandbox mode: honour the legacy config-gated behaviour.
		cfg = _aml_config()
		if not cfg["enabled"]:
			return
	else:
		cfg = _aml_config()
		if not cfg["enabled"] or not cfg["url"]:
			frappe.throw(
				"AML/CFT screening is required before loan origination. "
				"Configure lms_aml_enabled + lms_aml_url (or enable relaxed mode for sandbox)."
			)

	compliance_name = frappe.db.get_value(
		"LMS Borrower Compliance", {"customer": doc.applicant}, "name"
	)
	if not compliance_name:
		return

	aml_status, screened_at = frappe.db.get_value(
		"LMS Borrower Compliance", compliance_name, ["aml_status", "aml_screened_at"]
	)

	if not screened_at or aml_status == "Pending":
		screen_borrower_compliance(compliance_name, force=True)
		aml_status = frappe.db.get_value("LMS Borrower Compliance", compliance_name, "aml_status")

	if cfg["require_clear"] and aml_status != "Clear":
		frappe.throw(
			f"Cannot proceed. AML/CFT status is '{aml_status}'. "
			"Applicant must be cleared before loan origination."
		)


def _log_aml_incident(compliance_name: str, description: str):
	try:
		frappe.get_doc(
			{
				"doctype": "LMS Incident Log",
				"incident_type": "Technical",
				"severity": "Medium",
				"status": "Open",
				"description": f"AML screening failed for {compliance_name}: {description}",
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="LMS AML incident log failed", message=frappe.get_traceback())
