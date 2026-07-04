import frappe
import requests

DEFAULT_MIN_SCORE = 600
DEFAULT_TIMEOUT = 10


def _bureau_config():
    """Credit bureau settings, sourced from site_config with safe defaults.

    Configure per environment in site_config.json:
        lms_credit_bureau_enabled       (bool)  default False
        lms_credit_bureau_url           (str)   bureau scoring endpoint
        lms_credit_bureau_min_score     (int)   default 600
        lms_credit_bureau_block_on_error(bool)  default False (fail-open)
        lms_credit_bureau_timeout       (int)   seconds, default 10
    """
    conf = frappe.conf
    return {
        "enabled": bool(conf.get("lms_credit_bureau_enabled", False)),
        "url": conf.get("lms_credit_bureau_url"),
        "min_score": int(conf.get("lms_credit_bureau_min_score", DEFAULT_MIN_SCORE)),
        "block_on_error": bool(conf.get("lms_credit_bureau_block_on_error", False)),
        "timeout": int(conf.get("lms_credit_bureau_timeout", DEFAULT_TIMEOUT)),
    }


def execute_credit_bureau_check(doc, method):
    """Gate loan application submit on KYC and an optional external credit bureau.

    The external bureau call is config-driven and non-blocking by default, so a
    third-party outage cannot halt loan origination. The KYC "Approved" gate is
    always enforced. The credit score is persisted with ``db.set_value`` (not a
    full document save) so the mandatory KYC attachment fields cannot block the
    scoring update during application submission.
    """
    compliance_name = frappe.db.get_value(
        "LMS Borrower Compliance", {"customer": doc.applicant}, "name"
    )

    if not compliance_name:
        frappe.throw(
            f"Cannot submit application. Missing LMS Borrower Compliance profile for {doc.applicant}"
        )

    kyc_status, national_id = frappe.db.get_value(
        "LMS Borrower Compliance", compliance_name, ["kyc_status", "national_id_number"]
    )

    if kyc_status != "Approved":
        frappe.throw("Cannot proceed. Applicant's KYC status must be fully 'Approved'.")

    cfg = _bureau_config()
    if not cfg["enabled"] or not cfg["url"]:
        # External scoring disabled; KYC gate already enforced above.
        return

    try:
        response = requests.post(
            cfg["url"], json={"id_number": national_id}, timeout=cfg["timeout"]
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        frappe.log_error(message=str(e), title="LMS Credit Bureau API Failure")
        if cfg["block_on_error"]:
            frappe.throw("Credit validation service unavailable. Please retry later.")
        # Fail-open: allow submission to proceed without an external score.
        return

    score = data.get("score", 0)
    dti = data.get("dti", 0.0)

    frappe.db.set_value(
        "LMS Borrower Compliance",
        compliance_name,
        {"credit_score": score, "debt_to_income_ratio": dti},
        update_modified=False,
    )

    if score < cfg["min_score"]:
        frappe.throw(
            f"Application automatically rejected: Credit score below required threshold ({cfg['min_score']})."
        )
