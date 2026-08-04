"""R40 regression tests — collateral must link to the loan that created it.

Symptom (live, 2026-08-05):

  The manager's Collateral tab showed 6 items, all "Pledged", but every
  row reported ``Linked Loans: 0`` and the View button revealed no
  loans. The officer reported "collateral is not linked to the loan that
  was used to create the collateral".

  Clicking "View" on the live R39-deployed fix did nothing because the
  click handler used ``lms-collateral-detail-{cid}`` as the ID selector
  but the detail row was rendered with ``id="lms-col-detail-{cid}"``
  (prefix typo) — the lookup silently missed. Two bugs in one screen.

Root cause:

  1. **Server: child table never written.** The officer's
     ``submit_application_on_behalf`` created standalone ``LMS Collateral``
     DocType rows but never appended matching ``LMS Loan Collateral``
     child rows to ``app.custom_collateral``. The manager portal's
     ``get_collateral_register`` queries that child table to find linked
     loans; with zero rows it returns ``linked_loans: []`` for every
     collateral regardless of how many loans actually reference it.

  2. **Server: child table not propagated to the Loan.** When the manager
     approved an application, ``approve_application`` created a new Loan
     DocType but did NOT copy ``app.custom_collateral`` to
     ``loan.custom_collateral``. So even after the Loan existed, its
     coverage ratio (NRV / loan amount) was 0, the Loans tab's View
     modal showed no collateral, and any subsequent coverage check
     (repayments, write-offs, releases) saw an empty table.

  3. **JS: View button click was a no-op.** ``lms_renderCollateralRegister``
     built the detail row with ``id="lms-col-detail-{name}"`` but the
     click handler looked up ``#lms-collateral-detail-{cid}``. Mismatched
     prefix — the row never appeared, the click silently did nothing.

Fix:

  1. ``submit_application_on_behalf`` now appends a matching
     ``LMS Loan Collateral`` row to ``app.custom_collateral`` for every
     collateral item captured in the new-application form, then
     ``app.save()`` to persist the child rows.

  2. ``approve_application`` now copies each ``app.custom_collateral``
     row onto ``loan.custom_collateral`` so the Loan has the same
     linkage. Coverage checks, the Loans tab View modal, and downstream
     flows (repayment schedule, NRV computation, write-offs) all see
     the same pledged assets.

  3. The click handler now uses ``#lms-col-detail-{cid}`` consistently
     with the rendered detail row id.

Pinned tests:

  * test_officer_create_app_writes_collateral_child_table
  * test_manager_approve_propagates_collateral_to_loan
  * test_get_collateral_register_returns_linked_loans

Run via: `cd frappe-bench && python3 run_lms_tests.py`
"""

from __future__ import annotations

import time
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from lms_saas.tests.test_r37_approval_queue_state import (
    _make_customer,
    _BRANCH,
)


def _new_customer_name():
    """Return a unique-per-run customer name so test runs don't collide."""
    return f"R40 Cust {int(time.time() * 1000) % 10**10}"


def _ensure_compliance(cust):
    """Create / refresh LMS Borrower Compliance so the KYC/AML gate is passable."""
    name = frappe.db.get_value("LMS Borrower Compliance", {"customer": cust}, "name")
    fields = {
        "kyc_status": "Approved",
        "aml_status": "Clear",
        "consent_given": 1,
        "national_id_number": "R40-NID",
        "id_document_proof": "/files/r40-id.pdf",
        "proof_of_address": "/files/r40-poa.pdf",
    }
    if name:
        frappe.db.set_value("LMS Borrower Compliance", name, fields)
    else:
        frappe.get_doc(
            {"doctype": "LMS Borrower Compliance", "customer": cust, **fields}
        ).insert(ignore_permissions=True)


def _product():
    company = frappe.db.get_single_value("Global Defaults", "default_company") or "LMS Demo Co"
    p = frappe.db.get_value(
        "Loan Product",
        {"company": company, "product_code": "LMS-STD"},
        "name",
    )
    return p


class TestR40CollateralLinking(FrappeTestCase):
    """R40: collateral must link to the loan that created it."""

    def setUp(self):
        frappe.set_user("Administrator")

    def test_officer_create_app_writes_collateral_child_table(self):
        """After submit_application_on_behalf, app.custom_collateral must
        have one LMS Loan Collateral row per captured item."""
        cust_name = _new_customer_name()
        cust = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": cust_name,
                "customer_type": "Individual",
                "customer_group": "Commercial",
                "territory": "_Test Territory Rest Of The World",
                "custom_lms_branch": _BRANCH,
            }
        )
        cust.insert(ignore_permissions=True)
        _ensure_compliance(cust.name)

        product = _product()
        self.assertTrue(product, "LMS-STD product must exist on the bench")

        from lms_saas.api.officer import submit_application_on_behalf

        frappe.set_user("officer@kesari.africa")
        res = submit_application_on_behalf(
            customer=cust.name,
            loan_amount=5000,
            loan_product=product,
            repayment_periods=6,
            rate_of_interest=24,
            collateral=[
                {
                    "collateral_type": "Vehicle",
                    "collateral_value": 9000,
                    "description": "R40 Test Honda",
                }
            ],
        )
        app = frappe.get_doc("Loan Application", res["application"])

        # Standalone LMS Collateral record (for the register)
        stand = frappe.get_all(
            "LMS Collateral",
            filters={"loan_application": res["application"]},
            fields=["name", "market_value"],
        )
        self.assertEqual(
            len(stand), 1,
            "R40: exactly one standalone LMS Collateral must be created per item.",
        )

        # Child table (LMS Loan Collateral) must also be populated.
        children = app.get("custom_collateral") or []
        self.assertEqual(
            len(children), 1,
            f"R40: app.custom_collateral must have one LMS Loan Collateral "
            f"row per item. Got {len(children)}.",
        )
        # The child row must point at the standalone LMS Collateral.
        self.assertEqual(
            children[0].collateral, stand[0].name,
            "R40: child row's `collateral` link must point at the "
            "standalone LMS Collateral created in the same call.",
        )

    def test_manager_approve_propagates_collateral_to_loan(self):
        """After approve_application, loan.custom_collateral must mirror
        the application's child table so coverage is non-zero and the
        Loans tab View modal shows the collateral."""
        cust_name = _new_customer_name() + "-AP"
        cust = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": cust_name,
                "customer_type": "Individual",
                "customer_group": "Commercial",
                "territory": "_Test Territory Rest Of The World",
                "custom_lms_branch": _BRANCH,
            }
        )
        cust.insert(ignore_permissions=True)
        _ensure_compliance(cust.name)

        from lms_saas.api.officer import submit_application_on_behalf
        from lms_saas.api import manager as mgr_mod
        # Pin the manager branch so the queue + scope checks match the
        # bench's branch. (We can't call _manager_branch() — it may be
        # None if a prior test patched it off; read via the module attr.)
        orig_branch = mgr_mod._manager_branch
        try:
            mgr_mod._manager_branch = lambda: _BRANCH
            from lms_saas.api.manager import approve_application
            frappe.set_user("officer@kesari.africa")
            res = submit_application_on_behalf(
                customer=cust.name,
                loan_amount=4000,
                loan_product=_product(),
                repayment_periods=6,
                rate_of_interest=24,
                collateral=[
                    {
                        "collateral_type": "Vehicle",
                        "collateral_value": 6000,
                        "description": "R40 Suzuki",
                    }
                ],
            )
            # Submit the application so the manager can approve it.
            app = frappe.get_doc("Loan Application", res["application"])
            app.flags.ignore_permissions = True
            app.submit()

            # Approve as manager.
            frappe.set_user("manager@kesari.africa")
            out = approve_application(application_name=res["application"])
            self.assertEqual(
                out.get("status"), "approved",
                f"R40: approve must succeed. Got {out}",
            )

            # Verify the Loan inherited the child table.
            loan = frappe.get_doc("Loan", out["loan"])
            loan_children = loan.get("custom_collateral") or []
            self.assertGreater(
                len(loan_children), 0,
                f"R40: loan.custom_collateral must be populated after "
                f"approve. Got {len(loan_children)} rows.",
            )
        finally:
            mgr_mod._manager_branch = orig_branch

    def test_get_collateral_register_returns_linked_loans(self):
        """The manager-portal collateral register must report non-empty
        ``linked_loans`` for a collateral that was created as part of
        an approved Loan Application."""
        cust_name = _new_customer_name() + "-REG"
        cust = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": cust_name,
                "customer_type": "Individual",
                "customer_group": "Commercial",
                "territory": "_Test Territory Rest Of The World",
                "custom_lms_branch": _BRANCH,
            }
        )
        cust.insert(ignore_permissions=True)
        _ensure_compliance(cust.name)

        from lms_saas.api.officer import submit_application_on_behalf
        from lms_saas.api.manager import approve_application, get_collateral_register, _manager_branch

        orig = _manager_branch()
        try:
            from lms_saas.api import manager as mgr_mod
            mgr_mod._manager_branch = lambda: _BRANCH

            frappe.set_user("officer@kesari.africa")
            res = submit_application_on_behalf(
                customer=cust.name,
                loan_amount=3500,
                loan_product=_product(),
                repayment_periods=6,
                rate_of_interest=24,
                collateral=[
                    {
                        "collateral_type": "Vehicle",
                        "collateral_value": 7000,
                        "description": "R40 Toyota",
                    }
                ],
            )
            app = frappe.get_doc("Loan Application", res["application"])
            app.flags.ignore_permissions = True
            app.submit()

            frappe.set_user("manager@kesari.africa")
            out = approve_application(application_name=res["application"])
            self.assertEqual(out.get("status"), "approved")

            # Now query the register and find the collateral row.
            coll = get_collateral_register()
            target = (app.get("custom_collateral") or [])[0].collateral
            hit = next((c for c in coll["collateral"] if c["name"] == target), None)
            self.assertIsNotNone(
                hit,
                f"R40: collateral {target} must appear in "
                f"get_collateral_register (the manager-portal view).",
            )
            self.assertGreater(
                len(hit.get("linked_loans") or []),
                0,
                f"R40: linked_loans must be non-empty for a collateral "
                f"that was pledged to an approved Loan Application. "
                f"Got {hit.get('linked_loans')!r}",
            )
            # And the linked loan must be the one we just approved.
            self.assertEqual(
                hit["linked_loans"][0]["loan"], out["loan"],
                "R40: the linked loan must be the one approve_application "
                "returned, not some earlier placeholder loan.",
            )
        finally:
            from lms_saas.api import manager as mgr_mod
            mgr_mod._manager_branch = orig
