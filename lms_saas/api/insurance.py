"""Insurance addon API — policies, claims, premium tracking.

Uses new LMS Insurance Policy and LMS Insurance Claim doctypes.
Policies are linked to LMS Loans and Customers.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime, today, getdate, add_days

from lms_saas.utils.addons import require_addon_persona


def _require_insurance():
    require_addon_persona("insurance")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _branch():
    from lms_saas.api.staff import get_current_user_branch
    return get_current_user_branch()


def _customer_for_user():
    """Resolve the Customer linked to the current user (for borrower access)."""
    from lms_saas.permissions import _portal_customer
    return _portal_customer(frappe.session.user)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_policies(limit=50):
    """Return LMS Insurance Policies visible to the current user."""
    _require_insurance()

    if not _is_admin():
        # Borrowers see only their own policies
        customer = _customer_for_user()
        if customer:
            policies = frappe.get_all(
                "LMS Insurance Policy",
                filters={"customer": customer},
                fields=["name", "policy_number", "loan", "customer",
                        "insurance_type", "provider", "premium_amount",
                        "premium_due_date", "coverage_amount", "start_date",
                        "end_date", "status", "company"],
                order_by="start_date desc",
                limit_page_length=int(limit),
            )
            return {"policies": policies}

        # Staff: branch-scoped via loan's custom_lms_branch
        branch = _branch()
        if branch:
            branch_loans = frappe.get_all("Loan", filters={"custom_lms_branch": branch}, pluck="name")
            if branch_loans:
                policies = frappe.get_all(
                    "LMS Insurance Policy",
                    filters={"loan": ("in", branch_loans)},
                    fields=["name", "policy_number", "loan", "customer",
                            "insurance_type", "provider", "premium_amount",
                            "premium_due_date", "coverage_amount", "start_date",
                            "end_date", "status", "company"],
                    order_by="start_date desc",
                    limit_page_length=int(limit),
                )
                return {"policies": policies}
            return {"policies": []}

    # Admin: all policies
    policies = frappe.get_all(
        "LMS Insurance Policy",
        fields=["name", "policy_number", "loan", "customer",
                "insurance_type", "provider", "premium_amount",
                "premium_due_date", "coverage_amount", "start_date",
                "end_date", "status", "company"],
        order_by="start_date desc",
        limit_page_length=int(limit),
    )
    return {"policies": policies}


@frappe.whitelist()
def get_policy_detail(policy_name):
    """Return a single policy with linked loan details."""
    _require_insurance()

    policy = frappe.get_doc("LMS Insurance Policy", policy_name)

    loan = None
    if policy.loan:
        loan = frappe.db.get_value(
            "Loan",
            policy.loan,
            ["name", "loan_amount", "status", "customer", "disbursement_date"],
            as_dict=True,
        )

    # Claims linked to this policy
    claims = frappe.get_all(
        "LMS Insurance Claim",
        filters={"policy": policy_name},
        fields=["name", "claim_date", "claim_amount", "claim_type",
                "description", "status"],
        order_by="claim_date desc",
    )

    return {
        "policy": {
            "name": policy.name,
            "policy_number": policy.policy_number,
            "loan": policy.loan,
            "customer": policy.customer,
            "insurance_type": policy.insurance_type,
            "provider": policy.provider,
            "premium_amount": policy.premium_amount,
            "premium_due_date": policy.premium_due_date,
            "coverage_amount": policy.coverage_amount,
            "start_date": policy.start_date,
            "end_date": policy.end_date,
            "status": policy.status,
            "company": policy.company,
        },
        "loan": loan,
        "claims": claims,
    }


@frappe.whitelist()
def create_policy(policy_number, loan, customer, insurance_type, company,
                   provider=None, premium_amount=None, premium_due_date=None,
                   coverage_amount=None, start_date=None, end_date=None):
    """Admin-only: create a new insurance policy for a loan."""
    _require_insurance()
    if not _is_admin():
        frappe.throw(_("Only administrators can create insurance policies."), frappe.PermissionError)

    doc = frappe.new_doc("LMS Insurance Policy")
    doc.policy_number = policy_number
    doc.loan = loan
    doc.customer = customer
    doc.insurance_type = insurance_type
    doc.provider = provider
    doc.premium_amount = premium_amount
    doc.premium_due_date = premium_due_date
    doc.coverage_amount = coverage_amount
    doc.start_date = start_date or today()
    doc.end_date = end_date
    doc.status = "Active"
    doc.company = company
    doc.flags.ignore_permissions = True
    doc.insert()

    return {"name": doc.name, "policy_number": doc.policy_number}


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

@frappe.whitelist()
def file_claim(policy, claim_date, claim_amount, claim_type, description=None, company=None):
    """Create an LMS Insurance Claim."""
    _require_insurance()

    # Resolve company from policy if not provided
    if not company:
        company = frappe.db.get_value("LMS Insurance Policy", policy, "company")

    doc = frappe.new_doc("LMS Insurance Claim")
    doc.policy = policy
    doc.claim_date = claim_date
    doc.claim_amount = claim_amount
    doc.claim_type = claim_type
    doc.description = description
    doc.status = "Filed"
    doc.company = company
    doc.flags.ignore_permissions = True
    doc.insert()

    return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def get_claims(limit=50):
    """Return LMS Insurance Claims visible to the current user."""
    _require_insurance()

    if not _is_admin():
        customer = _customer_for_user()
        if customer:
            # Borrower: claims on their policies
            policy_names = frappe.get_all(
                "LMS Insurance Policy",
                filters={"customer": customer},
                pluck="name",
            )
            if policy_names:
                claims = frappe.get_all(
                    "LMS Insurance Claim",
                    filters={"policy": ("in", policy_names)},
                    fields=["name", "policy", "claim_date", "claim_amount",
                            "claim_type", "description", "status", "company"],
                    order_by="claim_date desc",
                    limit_page_length=int(limit),
                )
                return {"claims": claims}
            return {"claims": []}

        # Staff: branch-scoped
        branch = _branch()
        if branch:
            branch_loans = frappe.get_all("Loan", filters={"custom_lms_branch": branch}, pluck="name")
            if branch_loans:
                policy_names = frappe.get_all(
                    "LMS Insurance Policy",
                    filters={"loan": ("in", branch_loans)},
                    pluck="name",
                )
                if policy_names:
                    claims = frappe.get_all(
                        "LMS Insurance Claim",
                        filters={"policy": ("in", policy_names)},
                        fields=["name", "policy", "claim_date", "claim_amount",
                                "claim_type", "description", "status", "company"],
                        order_by="claim_date desc",
                        limit_page_length=int(limit),
                    )
                    return {"claims": claims}
            return {"claims": []}

    # Admin: all claims
    claims = frappe.get_all(
        "LMS Insurance Claim",
        fields=["name", "policy", "claim_date", "claim_amount",
                "claim_type", "description", "status", "company"],
        order_by="claim_date desc",
        limit_page_length=int(limit),
    )
    return {"claims": claims}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_insurance_stats():
    """Overview stats for the insurance dashboard."""
    _require_insurance()

    total_policies = frappe.db.count("LMS Insurance Policy")
    active_policies = frappe.db.count("LMS Insurance Policy", {"status": "Active"})
    lapsed_policies = frappe.db.count("LMS Insurance Policy", {"status": "Lapsed"})
    expired_policies = frappe.db.count("LMS Insurance Policy", {"status": "Expired"})

    total_claims = frappe.db.count("LMS Insurance Claim")
    filed_claims = frappe.db.count("LMS Insurance Claim", {"status": "Filed"})
    approved_claims = frappe.db.count("LMS Insurance Claim", {"status": "Approved"})
    paid_claims = frappe.db.count("LMS Insurance Claim", {"status": "Paid"})

    # Total coverage and premiums (active policies)
    from frappe.utils import flt as _flt
    total_coverage = _flt(frappe.db.sql(
        "SELECT SUM(coverage_amount) FROM `tabLMS Insurance Policy` WHERE status='Active'"
    )[0][0] or 0)

    total_premiums = _flt(frappe.db.sql(
        "SELECT SUM(premium_amount) FROM `tabLMS Insurance Policy` WHERE status='Active'"
    )[0][0] or 0)

    return {
        "total_policies": total_policies,
        "active_policies": active_policies,
        "lapsed_policies": lapsed_policies,
        "expired_policies": expired_policies,
        "total_claims": total_claims,
        "filed_claims": filed_claims,
        "approved_claims": approved_claims,
        "paid_claims": paid_claims,
        "total_coverage": total_coverage,
        "total_premiums": total_premiums,
    }