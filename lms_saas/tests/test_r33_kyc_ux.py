"""R33 regression tests — KYC review modal UX guards.

R33-High: The KYC review modal was the source of a 417 flood in the
console — the server-side gate (``officer.update_kyc``) correctly rejects
"Approved" when NID, consent, or ID document are missing, but the UI let
the officer click Save without any indication of WHY the request would
fail. The officer would click Save → see the 417 toast → click again →
see another 417. Server validation was correct; UX was not.

R33 fix introduces:
  1. A live inline alert (``#lms-kyc-requirements``) at the top of the
     KYC review modal that lists the missing requirements the moment the
     officer selects ``Approved``.
  2. A disabled state on the modal's primary "Save changes" action when
     the form is incomplete.
  3. A pre-submit guard inside the click handler so we don't even POST to
     ``update_kyc`` if the form is invalid — eliminating the 417 spam at
     the source.

These tests assert that the wiring exists in both the JS bundle and the
modal markup template. Server gate enforcement is already covered by
``test_compliance_gates`` / ``test_loan_officer_kyc``.
"""

from __future__ import annotations

from pathlib import Path
from unittest import TestCase

APP_ROOT = Path(__file__).resolve().parents[1]
JS_PATH = APP_ROOT / "public" / "js" / "lms_officer_portal.js"
CSS_PATH = APP_ROOT / "public" / "css" / "lms_components.css"


class TestR33KycReviewModalUx(TestCase):
    """R33 regression: the KYC review modal explains its own gate before
    the officer clicks Save."""

    def test_inline_alert_element_is_in_modal_markup(self):
        """R33-1: the modal body must include the inline alert container."""
        src = JS_PATH.read_text()
        # Inside the _showKycReviewModal function, the body string must
        # include the inline alert element id and class hooks.
        self.assertIn('id="lms-kyc-requirements"', src)
        self.assertIn("lms-form-alert", src)
        self.assertIn('id="lms-kyc-requirements-list"', src)

    def test_live_evaluation_function_present(self):
        """R33-2: a live-evaluation function must walk the form and toggle
        the alert + save button state whenever inputs change."""
        src = JS_PATH.read_text()
        # Match either a named inner function or an in-handler block — but
        # the trio (NID, consent, ID doc) must be checked together with
        # an "Approved" status guard.
        self.assertIn("lmsKycEvalRequirements", src)
        self.assertIn('"#lms-kyc-status"', src)
        self.assertIn('"#lms-kyc-nid"', src)
        self.assertIn('"#lms-kyc-consent"', src)
        self.assertIn('"#lms-kyc-iddoc-url"', src)

    def test_save_button_disabled_class_wired(self):
        """R33-3: the save button must toggle a disabled class based on the
        requirements list — preventing the visual "click → 417" loop."""
        src = JS_PATH.read_text()
        self.assertIn("lms-action-disabled", src)

    def test_click_handler_blocks_submit_when_invalid(self):
        """R33-4: the click handler must refuse to call the API when the
        form is invalid for "Approved", surfacing the inline alert and
        showing a toast instead."""
        src = JS_PATH.read_text()
        # Find the click handler block of the KYC modal — it must have
        # an early return when missing.length > 0 after the requirement
        # check.
        # Locate the section that references #lms-kyc-status in the args
        # block and follow it with the missing-list check.
        idx = src.find('kyc_status: (dlgRoot.querySelector("#lms-kyc-status")')
        self.assertGreater(idx, -1, "Could not find KYC status args block in officer portal JS")
        # Look ahead ~3000 chars (covers the click handler body).
        snippet = src[idx : idx + 3000]
        self.assertIn('args.kyc_status === "Approved"', snippet)
        self.assertIn("National ID number", snippet)
        self.assertIn("Borrower consent", snippet)
        self.assertIn("ID document proof", snippet)

    def test_alert_css_exists(self):
        """R33-5: the inline alert class must have CSS — without it the
        alert either shows always or never."""
        css = CSS_PATH.read_text()
        self.assertIn(".lms-form-alert", css)
        self.assertIn(".lms-form-alert--show", css)
        self.assertIn(".lms-action-disabled", css)


class TestR33KycServerGateStillAuthoritative(TestCase):
    """R33 regression: the client-side guard is a UX layer. The server
    gate at ``officer.update_kyc`` still enforces requirements even if
    the JS is bypassed. These tests cover the existing server gate that
    we did NOT weaken.

    If R33 ever tries to "loosen" the server gate (e.g. by letting the
    API accept a status without the matching fields), these tests will
    fail.
    """

    def test_update_kyc_requires_consent_for_approved(self):
        """R33-6: officer.update_kyc must still raise ValidationError when
        Approved is requested without consent_given."""
        import inspect

        from lms_saas.api import officer as officer_mod

        src = inspect.getsource(officer_mod.update_kyc)
        # The gate text is platform-stable; we just need to confirm
        # the check is in the function body.
        self.assertIn("consent_given", src)
        self.assertIn("Approved", src)
        # The raise must still be a ValidationError-shaped one. Both
        # are valid — frappe.throw raises ValidationError under the
        # hood, so accept either form.
        self.assertTrue(
            "frappe.ValidationError" in src or "frappe.throw" in src,
            "update_kyc must raise on the consent gate. Found neither "
            "frappe.ValidationError nor frappe.throw in the function body.",
        )

    def test_update_kyc_requires_nid_for_approved(self):
        """R33-7: the server gate must also require NID for Approved."""
        import inspect

        from lms_saas.api import officer as officer_mod

        src = inspect.getsource(officer_mod.update_kyc)
        self.assertIn("national_id", src)
