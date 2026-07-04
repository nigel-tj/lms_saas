"""AML/CFT screening — config-driven external provider hook (RBZ 3.18)."""

from __future__ import annotations

import json

import frappe
import requests

DEFAULT_TIMEOUT = 15
BLOCKED_STATUSES = frozenset({"Flagged", "Rejected"})


def _aml_config():
	"""AML provider settings from site_config."""
	conf = frappe.conf
	return {
		"enabled": bool(conf.get("lms_aml_enabled", False)),
		"url": conf.get("lms_aml_url"),
		"block_on_error": bool(conf.get("lms_aml_block_on_error", False)),
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


def on_compliance_after_insert(doc, method=None):
	"""Screen new borrowers when AML is enabled."""
	if frappe.flags.in_install or frappe.flags.in_migrate:
		return
	screen_borrower_compliance(doc.name)


def enforce_aml_on_origination(doc, method=None):
	"""Block loan application submit when AML is not clear (config-gated)."""
	cfg = _aml_config()
	if not cfg["enabled"]:
		return

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
