"""AML/CFT role-restriction gates — what each LMS persona is FORBIDDEN to do.

ARCHITECTURE NOTE:
    AML/CFT (Anti-Money Laundering / Countering Financing of Terrorism)
    is a POLICY LAYER on top of the general-purpose loan management
    software. The persona gates below are NOT AML-specific — they are
    standard "segregation of duties" controls (the maker cannot be the
    checker, the screener cannot be the approver, the operator cannot
    tamper with the audit trail) that the AML/CFT regime demands.

    Loan Officers are the front line of customer onboarding. Their role
    is to collect KYC documents, originate the application, and hand it
    off for review. They MUST NOT be able to:
      - Override or set AML clearance (only the screening provider does)
      - Clear sanctions / PEP flags (the screening provider decides)
      - Approve their own applications (four-eyes / maker-checker)
      - Disburse, write off, or reverse a money-movement event
      - Edit or delete the audit trail

    These restrictions are enforced at three layers:
      1. Role-based: ``LMS Loan Officer`` role is intentionally NOT
         granted write permission on ``Loan Disbursement``,
         ``Loan Write Off``, ``LMS Audit Event`` (see permissions.py
         and DocType JSON ``permissions`` blocks).
      2. Persona-based: every whitelisted endpoint in api/lms_portal.py
         and api/officer.py calls ``_require_role('LMS Loan Officer')``
         and ``_require_officer()`` which check ``Employee.custom_lms_persona``.
      3. Hook-based: ``enforce_aml_on_origination`` and
         ``enforce_origination_controls`` (in compliance.py) re-check the
         AML clearance at submit time, so a loan officer who managed to
         bypass the role check is still blocked.

This module exposes helpers for the API to check "can this user
perform this AML-relevant action" so the UI can hide / disable
controls proactively, and the server can hard-throw as a backstop.
"""

from __future__ import annotations

import frappe

#: The set of LMS personas that have NO AML authority at all (read-only
#: view of the AML status, no override capability).
READ_ONLY_AML_PERSONAS = frozenset({
    "Loan Officer",
    "Collector",
})

#: The set of LMS personas that can mark an AML flag as "False Positive"
#: / "Cleared" after manual review. Even here, the override must be
#: paired with a written justification that is logged in LMS Audit Event.
AML_OVERRIDE_PERSONAS = frozenset({
    "Branch Manager",
})

#: The set of LMS personas that can configure the AML screening
#: provider, change the screening URL, or enable / disable screening.
AML_ADMIN_PERSONAS = frozenset({
    "System Manager",
})


def can_clear_aml_flag(user: str | None = None) -> bool:
    """True if the user can clear / override an AML flag.

    Loan Officers and Collectors are explicitly FORBIDDEN from clearing
    AML flags. Even a "false positive" override must come from a
    Branch Manager (with audit) or higher. This is the AML/CFT
    segregation-of-duties rule: the same person who onboarded the
    customer cannot be the one who decides the customer is clean.
    """
    return _user_has_persona(user, AML_OVERRIDE_PERSONAS | AML_ADMIN_PERSONAS)


def can_configure_aml_provider(user: str | None = None) -> bool:
    """True if the user can change AML provider settings.

    Loan Officers and Branch Managers are FORBIDDEN — the AML provider
    URL and screening mode are system-level configuration that should
    only be set by a System Manager.
    """
    return _user_has_persona(user, AML_ADMIN_PERSONAS)


def can_view_aml_status(user: str | None = None) -> bool:
    """True if the user can view the AML status of a borrower.

    All authenticated LMS personas can view the AML status (read-only).
    Borrowers can view their own status only.
    """
    user = user or frappe.session.user
    if not user or user == "Guest":
        return False
    roles = set(frappe.get_roles(user))
    if "System Manager" in roles or "Administrator" in roles:
        return True
    if "LMS Portal Staff" in roles:
        return True
    return False


def assert_loan_officer_cannot_clear_aml() -> None:
    """Server-side backstop: hard-throw if a Loan Officer tries to clear AML.

    Called by every AML override / clearance flow. The UI should hide
    the control for Loan Officers, but a malicious request bypasses the
    UI — this is the server-side enforcement.
    """
    if can_clear_aml_flag():
        return
    roles = set(frappe.get_roles())
    if roles & {"System Manager", "Administrator"}:
        return
    frappe.throw(
        "Loan Officers cannot clear AML/CFT flags. "
        "Escalate to a Branch Manager for false-positive review.",
        frappe.PermissionError,
    )


def get_aml_role_capabilities(user: str | None = None) -> dict:
    """Return a dict of AML capabilities for the given user.

    Used by the UI to show / hide controls and by the regulator export
    endpoint to surface the role-capability matrix.
    """
    user = user or frappe.session.user
    return {
        "user": user,
        "can_view_aml_status": can_view_aml_status(user),
        "can_clear_aml_flag": can_clear_aml_flag(user),
        "can_configure_aml_provider": can_configure_aml_provider(user),
        # Read-only personas get an explicit flag so the UI can render
        # a "View Only" badge on the AML section.
        "is_aml_read_only": _user_has_persona(user, READ_ONLY_AML_PERSONAS),
    }


def _user_has_persona(user: str | None, allowed_personas: set) -> bool:
    """True if the user's LMS persona is in the allowed set.

    Admin / System Manager roles always pass.
    """
    user = user or frappe.session.user
    if not user or user == "Guest":
        return False
    roles = set(frappe.get_roles(user))
    if roles & {"System Manager", "Administrator"}:
        return True
    if not roles & {"LMS Portal Staff"}:
        return False
    from lms_saas.utils.portal import resolve_portal_persona

    persona = resolve_portal_persona(user)
    return persona in allowed_personas
