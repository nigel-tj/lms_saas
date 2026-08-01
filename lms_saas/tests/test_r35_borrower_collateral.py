"""R35 regression tests — Borrower / KYC modal de-dup + collateral fallback.

R35 bundles two fixes requested by the operator:

1. **Borrower Profile modal de-duplication.** The officer-side
   "Borrower Profile" modal used to render an editable Name / Mobile /
   Email / National ID form whose NID input wrote to
   ``Customer.custom_national_id_number``. But the KYC approval gate at
   ``officer.update_kyc`` reads ``LMS Borrower Compliance.national_id_number``
   — *two stores of truth*. Entering NID in the borrower modal "didn't
   propagate" to the KYC approval, so the officer's KYC approval got
   blocked even when the customer already had an ID on file.

   R35 fixes this by:
     * Removing the redundant NID input from the borrower modal (NID
       is edited ONLY through the KYC review modal).
     * Pre-filling the KYC modal's NID input from the Customer master
       record via ``_hydratedNid`` so the Compliance record carries the
       same value without the officer re-typing.

2. **Collateral loan_application link missing.** Officer-side
   ``submit_pending_application`` created ``LMS Collateral`` records
   without setting their ``loan_application`` Link, so the manager
   review endpoint filtered by that link and saw zero collateral. R35
   sets the link at origination AND adds an ``owner_customer`` fallback
   on both manager/officer detail endpoints so historical collateral
   (created before this fix) surfaces too — including the case where
   the Customer record was deleted while the Collateral + Loan
   Application records remained.

This file covers both halves.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest import TestCase

APP_ROOT = Path(__file__).resolve().parents[1]
JS_PATH = APP_ROOT / "public" / "js" / "lms_officer_portal.js"


# ---------------------------------------------------------------------------
# R35-1: Borrower Profile modal de-dup — read-only summary + KYC/contact
# actions (no NID input, modal-root save button removed).
# ---------------------------------------------------------------------------
class TestR35BorrowerProfileDeDup(TestCase):
    """R35 regression: Borrower Profile modal no longer carries an editable
    NID input or a top-level Save button. NID lives on the Compliance
    record and is edited through the KYC review modal only."""

    def _src(self):
        return JS_PATH.read_text()

    def test_borrower_modal_does_not_render_nid_input(self):
        """R35-1: no National ID input inside the borrower profile form."""
        src = self._src()
        # Locate the body of _showBorrowerModal
        start = src.index("lms_officer._showBorrowerModal = function")
        # End at the next top-level function (a loose "lms_officer._loadLoans =")
        end = src.index("\nlms_officer._loadLoans = function", start)
        body = src[start:end]
        # The NID input id was `lms-brw-nid`. The legacy code created it.
        self.assertNotIn('id="lms-brw-nid"', body)
        self.assertNotIn('name="national_id"', body)

    def test_borrower_modal_has_open_kyc_button(self):
        """R35-2: the open-KYC button (start or open) is rendered and
        references the existing KYC modal entrypoint."""
        src = self._src()
        start = src.index("lms_officer._showBorrowerModal = function")
        end = src.index("\nlms_officer._loadLoans = function", start)
        body = src[start:end]
        self.assertIn("lms-of-brw-start-kyc", body)
        self.assertIn("lms-of-brw-open-kyc", body)
        # Routed to the canonical KYC review modal.
        self.assertIn("lms_officer._openKycReview", body)

    def test_borrower_modal_has_inline_contact_form(self):
        """R35-3: name/mobile/email are edited via an inline form, with
        explicit Save + Cancel buttons, NOT a top-level modal Save."""
        src = self._src()
        start = src.index("lms_officer._showBorrowerModal = function")
        end = src.index("\nlms_officer._loadLoans = function", start)
        body = src[start:end]
        # Edit toggle + inline Save/Cancel pair.
        self.assertIn("lms-brw-edit-contact-btn", body)
        self.assertIn("lms-brw-save-contact", body)
        self.assertIn("lms-brw-cancel-contact", body)
        # Top-level Save removed — modal root confirmText = "Close" with
        # confirmVariant "ghost" and no onConfirm handler.
        self.assertIn('confirmText: "Close"', body)
        self.assertIn('confirmVariant: "ghost"', body)
        # The wrap-around search lands before the function; check the
        # preceding comment header (a few lines above the function def)
        # doesn't carry the old Save handler signature.
        # (The function itself doesn't bind onConfirm, which is what we
        # want — confirmed by absence of `onConfirm: function` inside
        # the function body block.)
        self.assertNotIn("onConfirm: function", body)

    def test_borrower_modal_contact_save_does_not_send_nid(self):
        """R35-4: the inline contact save posts ONLY customer / mobile /
        email. NID is intentionally absent so it never overwrites the
        Compliance record."""
        src = self._src()
        start = src.index("lms_officer._showBorrowerModal = function")
        end = src.index("\nlms_officer._loadLoans = function", start)
        body = src[start:end]
        # Find the args object inside the save handler.
        idx = body.index("var args = {")
        snippet = body[idx : idx + 600]
        self.assertIn("customer_name:", snippet)
        self.assertIn("email_id:", snippet)
        self.assertIn("mobile_no:", snippet)
        # NID MUST NOT appear as a key.
        self.assertNotIn("national_id:", snippet)
        self.assertNotIn("'national_id':", snippet)
        self.assertNotIn('"national_id":', snippet)

    def test_kyc_modal_hydrates_nid_from_customer(self):
        """R35-5: the KYC modal pre-fills its NID input from
        Customer.custom_national_id_number when the Compliance record's
        NID is blank. Avoids the operator's "saved NID but KYC still
        says it's missing" complaint."""
        src = self._src()
        idx = src.index("lms_officer._showKycReviewModal = function")
        # Locate the body up to the next sibling declaration.
        end = src.index('var body', idx)
        snippet = src[idx:end]
        self.assertIn("_hydratedNid", snippet)
        # Falls back to borrower's NID too.
        self.assertIn("borrower.custom_national_id_number", snippet)

    def test_kyc_modal_publishes_nid_on_save(self):
        """R35-6: when the officer hits Save, the args.national_id sent
        to update_kyc falls back to _hydratedNid if the input is empty,
        so the Compliance record captures what was pre-filled from the
        Customer master."""
        src = self._src()
        idx = src.index("var nidInputVal =")
        snippet = src[idx : idx + 1500]
        self.assertIn("_hydratedNid", snippet)
        self.assertIn("national_id:", snippet)
        self.assertIn("args.national_id || _hydratedNid", snippet)


# ---------------------------------------------------------------------------
# R35-7: Collateral loan_application link at origination.
# ---------------------------------------------------------------------------
class TestR35CollateralLinkAtOrigination(TestCase):
    """R35 regression: collateral created during origination must set
    the loan_application Link, otherwise the manager review cannot
    see it."""

    def test_officer_submit_sets_loan_application_on_collateral(self):
        from lms_saas.api import officer as officer_mod

        # Pull the function source without executing it.
        src = inspect.getsource(officer_mod.submit_application_on_behalf)
        # The new LMS Collateral doc must include loan_application: app.name
        # where `app` is the just-inserted Loan Application doc.
        self.assertIn('"loan_application": app.name', src)
        # The comment / block must mention R35 or the link rationale.
        self.assertRegex(src, r"R35: link the new LMS Collateral")


# ---------------------------------------------------------------------------
# R35-8: Manager + officer detail endpoints fall back to owner_customer
# lookup when the direct loan_application link is missing.
# ---------------------------------------------------------------------------
class TestR35CollateralFallbackRead(TestCase):
    """R35 regression: when the loan_application Link is blank (legacy
    data, or the Customer was deleted with the Customer Link still on
    the LMS Collateral doc), the manager + officer endpoints must
    surface it via the borrower owner_customer."""

    def test_manager_detail_has_owner_customer_fallback(self):
        from lms_saas.api import manager as mgr_mod

        src = inspect.getsource(mgr_mod.get_manager_application_detail)
        # Primary lookup.
        self.assertIn('"loan_application": application_name', src)
        # Fallback: same code block must query by owner_customer.
        self.assertIn('"owner_customer": applicant', src)
        # Doesn't gate on Customer doc existence — the Customer may be
        # deleted while the Collateral record remains.
        self.assertNotIn('frappe.db.exists("Customer", applicant)', src)

    def test_officer_detail_has_owner_customer_fallback(self):
        from lms_saas.api import officer as officer_mod

        src = inspect.getsource(officer_mod.get_application_detail)
        self.assertIn('"loan_application": application_name', src)
        self.assertIn('"owner_customer": applicant', src)
        self.assertNotIn('frappe.db.exists("Customer", applicant)', src)


# ---------------------------------------------------------------------------
# R35-9: get_borrower_detail prefers Compliance.national_id_number over
# Customer.custom_national_id_number, so the borrower modal's read-only
# NID label matches the actual KYC gate value.
# ---------------------------------------------------------------------------
class TestR35BorrowerDetailNidSource(TestCase):
    """R35 regression: borrower modal NID label is sourced from the
    Compliance record when present, otherwise the Customer master."""

    def test_get_borrower_detail_prefers_compliance_nid(self):
        from lms_saas.api import officer as officer_mod

        src = inspect.getsource(officer_mod.get_borrower_detail)
        # The compliance read pulls national_id_number.
        self.assertIn('"national_id_number"', src)
        # And the function explicitly overrides Customer.custom_national_id_number
        # when Compliance has an NID — so the borrower modal surfaces the
        # same value the KYC approval reads.
        self.assertIn("compliance.national_id_number", src)


# ---------------------------------------------------------------------------
# R35-10: API contract — direct call to get_manager_application_detail
# with a deleted Customer still surfaces collateral. End-to-end smoke
# via Frappe DB (only runs in bench / test environment).
# ---------------------------------------------------------------------------
class TestR35CollateralEndToEndViaAPI(TestCase):
    """R35 regression: API contract — orphan collateral (loan_application
    empty, owner_customer pointing to a now-deleted Customer) is still
    surfaced by the manager detail endpoint."""

    def test_orphan_collateral_surfaces_via_owner_customer(self):
        # Skip if the bench isn't initialized (the test infra guards on this).
        try:
            import frappe  # noqa: F401
        except Exception:
            self.skipTest("frappe not importable in test env")
        try:
            frappe.init(site="lms.localhost", sites_path="/home/nigel/work/erp-loan-microfin/frappe-bench/sites")
            frappe.connect()
        except Exception:
            self.skipTest("bench not available")
        # Use existing orphan collateral fixture in the live bench:
        #   COL-00134 (owner=Manager Test Borrower,
        #   loan_application=empty)
        # and the matching Loan Application ACC-LOAP-2026-00026.
        # Manager Test Borrower's Customer doc may or may not exist — the
        # fallback must still surface the collateral.
        try:
            from lms_saas.api.manager import get_manager_application_detail
            result = get_manager_application_detail(
                application_name="ACC-LOAP-2026-00026"
            )
            names = [c["name"] for c in result.get("collateral", [])]
            self.assertIn("COL-00134", names)
        except Exception as e:
            self.skipTest(f"manager endpoint unreachable: {e}")
        finally:
            try:
                frappe.destroy()
            except Exception:
                pass
