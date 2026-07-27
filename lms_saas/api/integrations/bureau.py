"""Integration API — credit bureau."""

import frappe

from lms_saas.utils.api_auth import validate_api_key


@frappe.whitelist()
def score_applicant(customer: str):
	"""Score an applicant via the configured credit bureau.

	B17 (board CRITICAL): previously this returned the raw config dict
	as if it were a score, which was a fail-open stub. Now:
	  - If bureau is disabled (`lms_credit_bureau_enabled != True`),
	    raise so the caller cannot accidentally treat the response as
	    a real score.
	  - If bureau is enabled but no URL is configured, raise — calling
	    code must not proceed without a real scoring provider.
	  - If bureau is enabled and configured, POST to the URL and return
	    the provider's response (with a `bypass` only when the site has
	    explicitly opted into sandbox fail-open via
	    ``lms_credit_bureau_sandbox_fail_open = True``).
	"""
	validate_api_key()
	from lms_saas.api.underwriting import _bureau_config

	cfg = _bureau_config()
	if not cfg["enabled"]:
		frappe.throw(
			"Credit bureau is not enabled on this site "
			"(set lms_credit_bureau_enabled = True in site_config).",
			frappe.PermissionError,
		)
	if not cfg["url"]:
		frappe.throw(
			"Credit bureau is enabled but lms_credit_bureau_url is not configured. "
			"Refusing to score without a live provider endpoint.",
			frappe.ValidationError,
		)

	# Configuration is valid — now look up the compliance record and POST.
	compliance = frappe.db.get_value("LMS Borrower Compliance", {"customer": customer}, "name")
	if not compliance:
		frappe.throw("No compliance record")
	sandbox_fail_open = bool(frappe.conf.get("lms_credit_bureau_sandbox_fail_open", False))
	if sandbox_fail_open:
		from lms_saas.api.compliance import write_audit_event
		write_audit_event(
			event_type="Bureau:SandboxFailOpen",
			reference_doctype="LMS Borrower Compliance",
			reference_name=compliance,
			details=f"customer={customer}; sandbox fail-open bypass; url={cfg['url']}",
		)
		return {
			"customer": customer,
			"compliance": compliance,
			"config": cfg,
			"sandbox_fail_open": True,
		}

	# Live bureau call: POST to provider, persist score, return normalised result.
	import requests

	customer_name = frappe.db.get_value("Customer", customer, "customer_name")
	national_id = frappe.db.get_value("LMS Borrower Compliance", compliance, "national_id_number")
	try:
		resp = requests.post(
			cfg["url"],
			json={"customer": customer, "name": customer_name, "id_number": national_id},
			timeout=cfg["timeout"],
		)
		resp.raise_for_status()
		data = resp.json() if resp.content else {}
	except requests.exceptions.RequestException as exc:
		frappe.log_error(title="LMS Bureau Provider Failure", message=str(exc))
		if cfg["block_on_error"]:
			frappe.throw("Credit bureau service unavailable. Please retry later.")
		return {
			"customer": customer,
			"compliance": compliance,
			"error": str(exc),
			"status": "error",
		}

	score = data.get("score") or data.get("credit_score")
	if score is not None:
		frappe.db.set_value(
			"LMS Borrower Compliance",
			compliance,
			{
				"bureau_score": int(score),
				"bureau_checked_at": frappe.utils.now_datetime(),
				"bureau_provider_ref": data.get("reference") or data.get("provider_ref") or "",
			},
			update_modified=False,
		)
	from lms_saas.api.compliance import write_audit_event
	write_audit_event(
		event_type="Bureau:Scored",
		reference_doctype="LMS Borrower Compliance",
		reference_name=compliance,
		details=f"customer={customer}; score={score}; min={cfg['min_score']}",
	)
	return {
		"customer": customer,
		"compliance": compliance,
		"score": int(score) if score is not None else None,
		"min_score": cfg["min_score"],
		"status": "scored",
	}
