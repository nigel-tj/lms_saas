"""R37 regression tests — approval queue must include SUBMITTED applications.

Symptom (live, 2026-08-04): officer created 2 loan applications via the
portal "New application" modal and clicked "Submit for manager approval".
The applications dropped out of the manager's Approval Queue tab AND
disappeared from the officer's "Pending applications" panel. Manager tab
spun forever. Investigation:

  - `submit_pending_application` correctly calls `app.submit()` which sets
    `docstatus=1` while leaving `status="Open"`.
  - But `get_approval_queue` and `get_pending_applications` both filtered on
    `{"docstatus": 0}`, never the canonical "submitted, awaiting manager"
    state (`docstatus=1, status="Open"`).

Root cause: the queue filter checked the wrong docstatus. Lending's own
number card for "Open Loan Applications" defines the canonical pattern as
`docstatus=1, status=Open` — and `submit_pending_application`'s docstring
explicitly states its job is "advance it from Draft (docstatus=0) to
Submitted (docstatus=1) so the manager queue picks it up."

Pinned tests:

  * test_approval_queue_returns_submitted_app
      After `submit_pending_application`, the app MUST show up in
      `get_approval_queue`.
  * test_pending_applications_returns_submitted_app
      Same for the officer's `get_pending_applications`.
  * test_dashboard_approval_count_includes_submitted
      `get_manager_dashboard` KPI `approval_queue_count` must include
      the submitted app, not zero out.
  * test_approve_application_accepts_submitted
      The manager-side `approve_application` must accept the SUBMITTED
      docstatus=1 state (currently it throws "Only draft applications
      can be approved").

Run via: `cd frappe-bench && python3 run_lms_tests.py`
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


# Loan Application state that means "submitted, awaiting manager approval".
PENDING_DOCSTATUS = 1
PENDING_STATUS = "Open"

# Bench fixtures kept simple to avoid touching globals.
_CUSTOMER_GROUP = "Commercial"
_TERRITORY = "_Test Territory Rest Of The World"
_BRANCH = "Main Branch - LMS"  # Cost Center the bench ships with.


def _make_branch_filter_match(branch):
    """Patch manager._manager_branch / officer._officer_branch → given
    branch so the queue's branch filter is permissive for that branch.
    The actual bug is the docstatus filter, not the branch filter —
    keep branch PATCHED-OUT of the assertion by always pinning the
    branch to the bench's known Cost Center.
    """
    from lms_saas.api import manager as mgr
    from lms_saas.api import officer as off

    mgr_orig = mgr._manager_branch
    off_orig = off._officer_branch
    mgr._manager_branch = lambda: branch
    off._officer_branch = lambda: branch
    return mgr_orig, off_orig


def _restore_branch_filter(mgr_orig, off_orig):
    from lms_saas.api import manager as mgr
    from lms_saas.api import officer as off

    mgr._manager_branch = mgr_orig
    off._officer_branch = off_orig


def _make_customer(name="CUST-R37", branch=None):
    if frappe.db.exists("Customer", name):
        cust = frappe.get_doc("Customer", name)
        cust.set("custom_lms_branch", branch or "")
        cust.flags.ignore_permissions = True
        cust.save()
    else:
        cust = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": name,
                "customer_type": "Individual",
                "customer_group": _CUSTOMER_GROUP,
                "territory": _TERRITORY,
                "custom_lms_branch": branch or "",
            }
        )
        cust.insert(ignore_permissions=True)

    compliance_name = frappe.db.get_value("LMS Borrower Compliance", {"customer": cust.name}, "name")
    if not compliance_name:
        compliance = frappe.get_doc(
            {
                "doctype": "LMS Borrower Compliance",
                "customer": cust.name,
                "kyc_status": "Approved",
                "aml_status": "Clear",
                "consent_given": 1,
                "national_id_number": "R37-NID-" + (cust.name[-6:] or "R37"),
                "id_document_proof": "/files/r37-id.pdf",
                "proof_of_address": "/files/r37-poa.pdf",
            }
        )
        compliance.insert(ignore_permissions=True)
    else:
        frappe.db.set_value(
            "LMS Borrower Compliance",
            compliance_name,
            {
                "kyc_status": "Approved",
                "aml_status": "Clear",
                "consent_given": 1,
                "national_id_number": "R37-NID-EXIST",
                "id_document_proof": "/files/r37-id.pdf",
                "proof_of_address": "/files/r37-poa.pdf",
            },
        )
    return cust


def _ensure_product(company):
    """Create a minimal LMS-STD Loan Product if none exists."""
    product = frappe.get_doc(
        {
            "doctype": "Loan Product",
            "product_code": "LMS-STD",
            "product_name": "LMS Standard Loan",
            "company": company,
            "rate_of_interest": 24,
            "maximum_loan_amount": 1_000_000,
            "is_term_loan": 1,
            "disabled": 0,
        }
    )
    product.insert(ignore_permissions=True)
    return product.name


def _make_submitted_app(applicant="CUST-R37", branch=None, amount=4000):
    company = frappe.db.get_single_value("Global Defaults", "default_company") or "LMS Demo Co"
    product = (
        frappe.db.get_value("Loan Product", {"company": company, "product_code": "LMS-STD"}, "name")
        or frappe.db.get_value("Loan Product", {"company": company, "disabled": 0}, "name")
        or _ensure_product(company)
    )
    branch = branch or _BRANCH

    app = frappe.get_doc(
        {
            "doctype": "Loan Application",
            "applicant_type": "Customer",
            "applicant": applicant,
            "company": company,
            "loan_product": product,
            "loan_amount": amount,
            "repayment_periods": 6,
            "rate_of_interest": 24,
            "repayment_method": "Repay Over Number of Periods",
            "posting_date": frappe.utils.nowdate(),
            "custom_lms_branch": branch,
        }
    )
    app.flags.ignore_permissions = True
    app.insert()
    app.submit()
    app.reload()
    return app


class TestR37ApprovalQueueState(FrappeTestCase):
    """R37: approval queue must include SUBMITTED Loan Applications."""

    def setUp(self):
        frappe.set_user("Administrator")
        # Make the borrower / compliance row exist with the bench's branch.
        _make_customer(branch=_BRANCH)
        # Pin manager + officer branch resolution to our bench branch so
        # the queue's branch filter matches the apps we create in this test.
        self._mgr_orig, self._off_orig = _make_branch_filter_match(_BRANCH)

    def tearDown(self):
        _restore_branch_filter(self._mgr_orig, self._off_orig)

    # ── Manager queue includes SUBMITTED apps ──────────────────────

    def test_approval_queue_returns_submitted_app(self):
        from lms_saas.api.manager import get_approval_queue

        app = _make_submitted_app()
        res = get_approval_queue()

        names = [a["name"] for a in (res.get("applications") or [])]
        self.assertIn(
            app.name,
            names,
            f"Approval queue must include SUBMITTED app {app.name} "
            f"(docstatus=1, status='Open'). Reported bug: approval "
            f"queue empty after officer clicks 'Submit for manager approval'.",
        )

    def test_dashboard_approval_count_includes_submitted(self):
        from lms_saas.api.manager import get_manager_dashboard

        app = _make_submitted_app()
        res = get_manager_dashboard()

        count = (res.get("kpis") or {}).get("approval_queue_count") or 0
        self.assertGreaterEqual(
            count,
            1,
            f"Dashboard 'Approval Queue' KPI ({count}) must include the "
            f"SUBMITTED app {app.name}.",
        )

    # ── Officer-side queue includes SUBMITTED apps ────────────────

    def test_pending_applications_returns_submitted_app(self):
        from lms_saas.api.officer import get_pending_applications

        app = _make_submitted_app()
        res = get_pending_applications()

        names = [a["name"] for a in (res.get("applications") or [])]
        self.assertIn(
            app.name,
            names,
            f"Officer 'Pending applications' must include SUBMITTED app "
            f"{app.name} so the officer sees their own submission waiting "
            f"on manager.",
        )

    # ── Approve application accepts SUBMITTED ─────────────────────

    def test_approve_application_accepts_submitted(self):
        """approve_application must accept the canonical SUBMITTED state.
        Currently the docstatus!=0 guard throws and the manager can never
        approve a Loan Application that was submitted by an officer.
        """
        from lms_saas.api.manager import approve_application

        app = _make_submitted_app()
        try:
            approve_application(application_name=app.name)
        except Exception as e:
            msg = str(e)
            self.assertNotIn(
                "Only draft applications can be approved",
                msg,
                "approve_application must accept SUBMITTED (docstatus=1) "
                "Loan Applications.",
            )
