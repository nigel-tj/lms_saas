"""R57 regression: collect modal currency + Loan Demand role permission.

Two coupled bugs surfaced together on the live site after the company
flipped from ZAR (Kesari) to USD (LMS Demo Co):

1. **Hardcoded "ZAR" in the collect modal.** ``lms_collect._openCollectModal``
   baked the string ``"ZAR"`` into the confirm sentence and the live
   preview, so when the operator collected USD 1,546.00 from a
   borrower the modal still read ``"I have ZAR 0.00 in hand"`` —
   meaningless to the operator. The confirm sentence is the cheap
   defense against a mis-typed amount (R18-6); if the currency is
   wrong, the operator can rubber-stamp the wrong number without
   noticing.

   Fix: read the company currency from ``window.__lms_currency`` (set
   by ``templates/lms_portal/shell.html`` from site_config) and fall
   back to ``frappe.boot.sysdefaults.currency`` and finally ``"USD"``.
   Use ``lms_portal.formatCurrency`` so the live preview reads
   ``$1,546.00`` not ``USD 1546.00``.

2. **Officer can't submit a field collection — "does not have doctype
   access via role permission for document Loan Demand".** When an
   officer recorded a repayment, the field-collection API created the
   ``Loan Repayment`` row with ``ignore_permissions=True`` — but
   Lending's ``Loan Repayment.on_submit`` hook fires
   ``update_demands`` / ``reverse_demands`` / ``make_new_demand``,
   which load and write ``Loan Demand`` / ``Loan Interest Accrual``
   rows in the *officer's* session. Worse, ``LMS Portal Staff`` had
   no DocPerm at all on ``Loan Repayment`` or ``Loan`` itself, so
   even a basic ``frappe.has_permission(..., throw=True)`` inside
   the hook / child-table loader rejected the officer with
   "Not permitted" before the hook could run.

   Fix: add ``Loan Demand`` + ``Loan Interest Accrual`` to
   ``_lending_doctypes()`` so System Manager / Administrator get the
   full perm, and grant ``LMS Portal Staff`` the minimum perm the
   submit hook needs (read + write + create + submit + report, but
   NOT delete / cancel / amend so the officer can't desync the
   audit trail by hand). Loan Repayment and Loan are also included
   so the field-collection path can read + submit its own records.

These tests pin both invariants so a future refactor cannot
reintroduce the hardcoded ZAR or strip the perm grant.
"""

from __future__ import annotations

import re
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase


COMPANY = "LMS Demo Co"
PERSONA_ROLE = "LMS Portal Staff"
LENDING_HOOK_DOCTYPES = (
    "Loan Repayment",
    "Loan Demand",
    "Loan Interest Accrual",
    "Loan Repayment Schedule",
    "Loan",
)


# --- Fix 1: no hardcoded ZAR anywhere in the collect modal JS -----------

class TestCollectModalCurrency(FrappeTestCase):
    """Pin that the collect modal no longer hardcodes ZAR."""

    JS_PATH = "apps/lms_saas/lms_saas/public/js/lms_collect_pwa.js"

    def _read_collect_js(self) -> str:
        import os

        # frappe.get_app_path("lms_saas") returns the app root
        # (e.g. .../apps/lms_saas) — the JS file lives at
        # .../apps/lms_saas/lms_saas/public/js/lms_collect_pwa.js
        app_root = frappe.get_app_path("lms_saas")
        with open(os.path.join(app_root, "public", "js", "lms_collect_pwa.js")) as f:
            return f.read()

    def test_no_hardcoded_zar_in_collect_modal(self):
        """The collect modal's confirm sentence + live preview must
        read from window.__lms_currency, not the literal "ZAR".

        Pins the R57 fix; a future refactor that re-hardcodes the
        South-African-Rand prefix to "ZAR" (a tempting shortcut for
        "Kesari" / "Demo Co" tests on a local ZAR bench) will break
        the same UI the operator already complained about.
        """
        src = self._read_collect_js()
        # The strings we explicitly removed in R57:
        #   'I have <strong id="lms-collect-confirm-amount">ZAR 0.00</strong> in hand ...'
        #   confirmAmount.textContent = "ZAR " + amount.toFixed(2);
        self.assertNotIn(
            "lms-collect-confirm-amount\">ZAR",
            src,
            "Collect modal still hardcodes ZAR in the confirm sentence. "
            "Use window.__lms_currency / lms_portal.formatCurrency instead.",
        )
        self.assertNotIn(
            'confirmAmount.textContent = "ZAR "',
            src,
            "Collect modal still hardcodes ZAR in the live preview. "
            "Use lms_portal.formatCurrency(amount, confirmCurrency) instead.",
        )

    def test_confirm_uses_currency_helper(self):
        """The collect modal should delegate currency resolution to
        lms_portal.resolveCurrency() and formatting to
        lms_portal.formatCurrency() — NOT inline its own fallback
        chain. If the chain were inlined here AND in lms_portal.js,
        the two could drift apart and the modal would disagree with
        every other currency display on the portal (the exact bug the
        DRY review caught: modal said ZAR while rows said $).
        """
        src = self._read_collect_js()
        self.assertIn(
            "lms_portal.resolveCurrency",
            src,
            "Collect modal must call lms_portal.resolveCurrency() so the "
            "currency fallback chain lives in one place.",
        )
        self.assertIn(
            "lms_portal.formatCurrency",
            src,
            "Collect modal should call lms_portal.formatCurrency for "
            "locale-aware symbol + grouping (Intl.NumberFormat).",
        )
        # The old inline chain must not reappear in this file.
        self.assertNotIn(
            "frappe.boot.sysdefaults.currency",
            src,
            "Collect modal must not inline the currency fallback chain — "
            "use lms_portal.resolveCurrency().",
        )

    def test_resolve_currency_is_single_source_of_truth(self):
        """lms_portal.js must define resolveCurrency() and its
        formatCurrency must consume it — this is what makes the chain
        single-sourced across the whole portal.
        """
        import os

        app_root = frappe.get_app_path("lms_saas")
        with open(os.path.join(app_root, "public", "js", "lms_portal.js")) as f:
            portal_src = f.read()
        self.assertIn(
            "lms_portal.resolveCurrency = function",
            portal_src,
            "lms_portal.js must define resolveCurrency as the single "
            "source of truth for the display currency.",
        )
        self.assertIn(
            "currency = currency || lms_portal.resolveCurrency()",
            portal_src,
            "formatCurrency must resolve via resolveCurrency(), not its "
            "own inline fallback chain.",
        )


# --- Fix 2: Loan Demand / Loan Interest Accrual perms --------------------

class TestLoanDemandPermGrant(FrappeTestCase):
    """Pin that LMS Portal Staff has the perms Lending's on_submit
    hook needs to write Loan Demand rows during a field collection."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        # Run the same perm grant the deploy pipeline runs (via
        # frappe-cloud-update.sh step 5/6) so the test exercises the
        # production code path, not just whether the rows happen to
        # exist on this particular bench's database.
        from lms_saas.install import _ensure_lending_permissions
        _ensure_lending_permissions()
        frappe.db.commit()

    def test_loan_demand_in_lending_doctypes(self):
        """``_lending_doctypes()`` must include Loan Demand so the
        System Manager / Administrator / report-perm sync covers it.

        Pins the R57 fix; removing Loan Demand from this list will
        silently skip the perm grant and the operator will get the
        "doctype access" error again on the very next field collection.
        """
        from lms_saas.install import _lending_doctypes

        lending = _lending_doctypes()
        self.assertIn(
            "Loan Demand",
            lending,
            "_lending_doctypes() must include 'Loan Demand' so "
            "Lending's on_submit hook can write demand rows for "
            "officers / collectors / branch managers.",
        )
        self.assertIn(
            "Loan Interest Accrual",
            lending,
            "_lending_doctypes() must include 'Loan Interest Accrual' "
            "so the daily-accrual hook can write rows in the "
            "officer's session during a field collection.",
        )

    def test_lms_portal_staff_has_minimum_loan_demand_perm(self):
        """``LMS Portal Staff`` must have at least read+write+create
        +submit+report on the doctypes Lending's on_submit hook
        writes. The hook runs in the officer's session, not the API
        session, so a missing perm = a hard failure on the next
        repayment.

        We deliberately do NOT require delete / cancel / amend — the
        officer shouldn't be able to desync the audit trail by hand
        (those operations are reserved for managers via the manager
        portal).
        """
        for dt in LENDING_HOOK_DOCTYPES:
            row = frappe.db.get_value(
                "Custom DocPerm",
                {"role": PERSONA_ROLE, "parent": dt},
                ["read", "write", "create", "submit", "delete", "cancel", "amend", "report"],
                as_dict=True,
            )
            self.assertIsNotNone(
                row,
                f"Custom DocPerm missing: {PERSONA_ROLE} on {dt}. "
                f"Field collection (record_field_repayment) will fail "
                f"with 'does not have doctype access'.",
            )
            self.assertEqual(row.read, 1, f"{dt}: read perm required")
            self.assertEqual(row.write, 1, f"{dt}: write perm required")
            self.assertEqual(row.create, 1, f"{dt}: create perm required")
            self.assertEqual(row.submit, 1, f"{dt}: submit perm required")
            self.assertEqual(row.report, 1, f"{dt}: report perm required")
            # Officers / collectors must not be able to delete / cancel
            # / amend demand rows — those operations are the manager's
            # and would desync the audit trail.
            self.assertEqual(row.delete, 0, f"{dt}: delete perm must be 0")
            self.assertEqual(row.cancel, 0, f"{dt}: cancel perm must be 0")
            self.assertEqual(row.amend, 0, f"{dt}: amend perm must be 0")

    def test_officer_can_check_loan_demand_perm(self):
        """End-to-end: when the API grants LMS Portal Staff the perm,
        ``frappe.has_permission('Loan Demand', 'write')`` returns True
        for an officer user. This is the actual code path the
        on_submit hook hits.
        """
        # Find or create the officer user.
        if not frappe.db.exists("User", "officer@kesari.africa"):
            self.skipTest("officer@kesari.africa user not seeded on this bench")

        frappe.set_user("officer@kesari.africa")
        try:
            can_read = frappe.has_permission("Loan Demand", "read")
            can_write = frappe.has_permission("Loan Demand", "write")
            can_create = frappe.has_permission("Loan Demand", "create")
        finally:
            frappe.set_user("Administrator")

        self.assertTrue(
            can_read,
            "officer@kesari.africa must be able to read Loan Demand "
            "(Lending's on_submit hook loads demand rows).",
        )
        self.assertTrue(
            can_write,
            "officer@kesari.africa must be able to write Loan Demand "
            "(Lending's on_submit hook updates paid_amount).",
        )
        self.assertTrue(
            can_create,
            "officer@kesari.africa must be able to create Loan Demand "
            "(Lending's on_submit hook may insert new demand rows).",
        )
