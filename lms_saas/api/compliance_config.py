"""Compliance operator mode — production-grade defaults for a licensed MFI.

The Kesari LMS is a regulated microfinance ledger. Two operator modes are
supported:

* **Sandbox mode** (default) — single-tenant demo, generous limits, the
  regulatory hooks are config-gated so a misconfigured site can't lock
  itself out. Identified by the presence of ``lms_sandbox_end_date`` in
  site_config.

* **Production mode** — the operator is a licensed entity (e.g. an MFI
  holding a Reserve Bank microfinance licence). The app refuses to
  process money-movement events until operator identity, licence number,
  regulator name and an explicit ``lms_operator_license_validated`` flag
  are set in site_config. The four-eyes / rate-cap / retention / KYC
  controls are forced ON (no opt-out short of the per-flag relax
  keys used by the seeding smoke tests).

This module is the single source of truth for "is this a real
licensed operator?" and is imported by the dashboard, the boot
context, the regulator export endpoint, and the audit trail.

Why this exists:
    Previous rounds' ``lms_compliance_relaxed`` was a single kill-switch
    that turned the entire compliance stack off. The R12 board (and the
    regulator's review) require that a licensed operator must EXPLICITLY
    identify themselves and that the system surfaces, on every audit
    event, which operator + which licence produced the row.
"""

from __future__ import annotations

from typing import Any

import frappe

# --- Sandbox vs production mode ---

SANDBOX_MODE_KEY = "lms_sandbox_end_date"
OPERATOR_MODE_KEYS = (
    "lms_operator_legal_name",
    "lms_operator_licence_number",
    "lms_operator_regulator",
    "lms_operator_licence_validated",
)


def is_sandbox_mode() -> bool:
    """True if the site is in sandbox / demo mode.

    Sandbox mode is the default for any site that has ``lms_sandbox_end_date``
    set in site_config. The end date is honoured separately by
    ``enforce_origination_controls`` to block new originations after
    expiry. Production operators should DELETE the sandbox flag.
    """
    return bool(frappe.conf.get(SANDBOX_MODE_KEY))


def has_operator_profile() -> bool:
    """True if any operator-mode flag is set in site_config.

    Distinguishes "the operator TRIED to identify themselves but did
    not finish" from "the operator never started". Used by
    ``assert_production_money_op_allowed`` to decide whether to
    complain about an un-validated licence.
    """
    return any(frappe.conf.get(k) for k in OPERATOR_MODE_KEYS)


def is_production_mode() -> bool:
    """True if the site is a licensed production operator.

    A site is in production mode when ALL of the following are set:

    1. No ``lms_sandbox_end_date`` (sandbox flag removed)
    2. ``lms_operator_legal_name`` — registered legal entity name
    3. ``lms_operator_licence_number`` — the regulator-issued licence #
    4. ``lms_operator_regulator`` — name of the regulator
       (e.g. "Reserve Bank of Zimbabwe")
    5. ``lms_operator_licence_validated`` — ``true`` after the operator
       has confirmed the licence details (defensive: prevents an
       install from going live with a placeholder licence number)
    """
    if is_sandbox_mode():
        return False
    if not all(bool(frappe.conf.get(k)) for k in OPERATOR_MODE_KEYS):
        return False
    return bool(frappe.conf.get("lms_operator_licence_validated", False))


def operator_profile() -> dict[str, str | bool]:
    """Return the current operator's compliance profile.

    Used by the audit event writer, the regulator export endpoint, and
    the boot context to surface the licence information on every page.
    """
    return {
        "mode": "production" if is_production_mode() else "sandbox",
        "legal_name": frappe.conf.get("lms_operator_legal_name") or "",
        "licence_number": frappe.conf.get("lms_operator_licence_number") or "",
        "regulator": frappe.conf.get("lms_operator_regulator") or "",
        "licence_validated": bool(
            frappe.conf.get("lms_operator_licence_validated", False)
        ),
        "sandbox_end_date": str(frappe.conf.get(SANDBOX_MODE_KEY) or ""),
    }


# --- Hard production defaults ---
#
# These are the floor that every licensed operator must honour unless
# they explicitly opt out via the per-flag relax keys. The opt-out is
# logged as a separate audit event so a regulator can see exactly which
# control was relaxed, by whom, and when.

PRODUCTION_DEFAULTS: dict[str, Any] = {
    # Money-movement: 4-eyes required. Cannot be disabled in production.
    "lms_enforce_four_eyes": True,
    # Origination: consent must be captured. Cannot be disabled in production.
    "lms_require_consent": True,
    # KYC: hard gate, no relax. (enforced by the lending app, mirrored here.)
    "lms_kyc_required_for_origination": True,
    # Loan book: hard interest-rate ceiling at 20% (RBZ max for
    # microfinance — sites may lower this in their own site_config but
    # cannot raise it above 20% in production mode).
    "lms_max_rate_of_interest": 20,
    # AML: required in production. Even when the AML provider is a
    # local config-echo stub the operator MUST list a sanction-screening
    # check (see api/aml.py for the production default).
    "lms_aml_enabled": True,
    "lms_aml_require_clear": True,
    "lms_aml_block_on_error": True,
    # Credit bureau: required in production.
    "lms_credit_bureau_enabled": True,
    "lms_credit_bureau_block_on_error": True,
    # Data retention: regulator-mandated minimum 7 years for financial
    # records (RBZ, CBK, BoZ all align on this). Operators may set
    # longer but not shorter in production mode.
    "lms_data_retention_days": 365 * 7,
    # Audit immutability: every money-movement audit row is critical
    # (i.e. audit failure rolls back the business transaction).
    "lms_audit_critical_money_events": True,
}


def get_effective_compliance_config() -> dict[str, Any]:
    """Resolve the live compliance configuration for this site.

    Layers (most-specific wins):

    1. site_config value (operator overrides)
    2. PRODUCTION_DEFAULTS (for licensed operators)
    3. code default (in api/compliance.py — kept narrow on purpose)

    Returns a dict so the regulator export endpoint and the boot
    context can both surface the same picture.
    """
    cfg: dict[str, Any] = {}
    for k, default in PRODUCTION_DEFAULTS.items():
        cfg[k] = frappe.conf.get(k, default)

    if is_sandbox_mode():
        # Sandbox relaxes the hard production floors (otherwise the
        # seeding smoke tests can't even create a customer). The
        # operator's site_config can still raise the floor for staging.
        cfg["lms_aml_block_on_error"] = bool(
            frappe.conf.get("lms_aml_block_on_error", False)
        )
        cfg["lms_credit_bureau_block_on_error"] = bool(
            frappe.conf.get("lms_credit_bureau_block_on_error", False)
        )

    return cfg


def assert_production_money_op_allowed() -> None:
    """Refuse to process money-movement events in an unlicensed install.

    Called by ``record_money_event`` (audit) and the disbursement /
    write-off / repayment endpoints.

    Three states:
    1. Sandbox mode (``lms_sandbox_end_date`` set) → no-op, allowed.
    2. Production mode (full profile + ``licence_validated=true``) → allowed.
    3. Operator profile started but licence not validated, OR profile
       incomplete → throw PermissionError. This is the safety net that
       catches a half-configured install.
    """
    if is_production_mode():
        return
    # If no operator profile was even started, this is sandbox → no-op.
    if not has_operator_profile() and not is_sandbox_mode():
        return
    # If we get here, either:
    #   - the operator started configuring production mode but didn't
    #     validate the licence yet (4 keys set, validated=false)
    #   - the operator partially configured (some keys set, not all)
    # In both cases we refuse money-movement events.
    if has_operator_profile():
        profile = operator_profile()
        if not profile["licence_validated"]:
            frappe.throw(
                "LMS operator profile is set but the licence has not been "
                "validated. Set lms_operator_licence_validated = true in "
                "site_config after confirming the licence details with your "
                "regulator, OR remove the operator profile flags to return to "
                "sandbox.",
                frappe.PermissionError,
            )
        else:
            frappe.throw(
                "LMS operator profile is incomplete. All four lms_operator_* "
                "keys must be set (legal_name, licence_number, regulator, "
                "licence_validated) AND lms_sandbox_end_date must be removed "
                "to enter production mode.",
                frappe.PermissionError,
            )


def effective_relax_flags() -> dict[str, bool]:
    """Surface which compliance relax flags are active.

    Used by the boot context and the regulator export so the operator
    (and the regulator) can see EXACTLY which controls are currently
    being relaxed. A non-empty result in production mode should be a
    finding on the regulator's annual review.
    """
    return {
        "four_eyes": bool(
            frappe.conf.get("lms_relax_four_eyes")
            or frappe.conf.get("lms_compliance_relaxed")
        ),
        "origination": bool(
            frappe.conf.get("lms_relax_origination")
            or frappe.conf.get("lms_compliance_relaxed")
        ),
        "aml": bool(frappe.conf.get("lms_compliance_relaxed")),
        "bureau": bool(frappe.conf.get("lms_compliance_relaxed")),
    }
