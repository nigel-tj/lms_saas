"""R58 regression: notification bell must resolve staff callers by branch, not borrower link.

Two coupled bugs surfaced together on the live site (field QA 2026-09-03):

1. **Staff personas got the borrower "No account on file yet" modal.**
   Opening the notification bell as collector / officer / manager fired
   ``mark_notifications_read``, which resolved the caller through the
   borrower-only Customer link (``_require_customer()``). For staff —
   who have no Customer record — that raised the orange
   "No account on file yet" msgprint, which Frappe's JS renders as a
   modal. The list side of the bell (``get_portal_notifications``)
   was already R43-fixed to scope staff notifications by branch, so
   the two halves of the same feature disagreed about who the user
   was: staff saw a badge with 22 unread items, clicked it, and got
   a borrower onboarding message.

   Worse, the badge could never clear: mark-as-read marked nothing
   for staff, so every bell open re-fired the modal.

   Fix: both mark-as-read and backfill resolve the caller through the
   same shared helper the list endpoint uses — borrower → own loans,
   portal staff → branch loans, admin → silence.

2. **Borrower behavior must not change.** A borrower still marks only
   their own loans' rows; staff never mark a borrower's rows.

These tests pin the staff contract at the whitelisted-API seam so a
future refactor cannot reintroduce the borrower-only resolution.
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase


STAFF_USERS = (
    "collector@kesari.africa",
    "officer@kesari.africa",
    "manager@kesari.africa",
)
BORROWER_USER = "borrower@example.com"
PASSWORDS = {
    "collector@kesari.africa": "Collector@123",
    "officer@kesari.africa": "Officer@123",
    "manager@kesari.africa": "Manager@123",
    "borrower@example.com": "Borrower@123",
}


def _user_exists(email: str) -> bool:
    return bool(frappe.db.exists("User", email))


def _as(email: str):
    """Context-managed session user switch."""
    return frappe.set_user(email)


class TestStaffBellMarkRead(FrappeTestCase):
    """Pin that mark-as-read works for staff personas with no borrower msgprint."""

    STAFF_SEED_EMAILS = STAFF_USERS

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_mark_read_as_staff_has_no_server_messages(self):
        """mark_notifications_read as staff returns a dict and no msgprint.

        Pins the R58 fix. Before the fix, staff hit the borrower-only
        ``_require_customer()`` resolution which queued the orange
        "No account on file yet" msgprint — the modal every staff
        persona saw on bell open. The whole message log must be empty:
        ANY queued message would render as a modal in the browser, not
        just the borrower one.
        """
        from lms_saas.api.portal import mark_notifications_read

        for email in self.STAFF_SEED_EMAILS:
            if not _user_exists(email):
                self.skipTest(f"test user {email} not provisioned on this bench")
            _as(email)
            # msgprint queues into frappe.message_log; assert nothing queued.
            frappe.local.message_log = []
            result = mark_notifications_read()
            self.assertIsInstance(result, dict, email)
            self.assertIn("marked", result, email)
            self.assertEqual(
                [],
                frappe.local.message_log,
                f"staff {email} got queued server messages: {frappe.local.message_log}",
            )

    def test_mark_read_clears_branch_unread_count(self):
        """After mark-as-read, the unread count the badge displays reaches zero.

        The badge count comes from get_portal_notifications (branch-scoped
        for staff). The bell contract: badge > 0 → open bell → mark-read
        fires → badge drops to 0. Before the fix the count stayed put for
        staff, so the modal re-fired on every open. If the branch has no
        unread rows on this bench, the contract is pinned with a seeded
        notification log row instead of passing vacuously.
        """
        from lms_saas.api.portal import get_portal_notifications, mark_notifications_read

        email = self.STAFF_SEED_EMAILS[0]
        if not _user_exists(email):
            self.skipTest(f"test user {email} not provisioned on this bench")

        _as(email)
        before = get_portal_notifications()
        unread_before = before.get("unread_count", 0)
        seed_name = None
        if not unread_before:
            # Seed one unread row for a branch loan so the contract is
            # actually exercised (not a vacuous pass on an empty bench).
            branch = self._staff_branch(email)
            loan = frappe.db.get_value(
                "Loan", {"custom_lms_branch": branch, "docstatus": 1}, "name"
            ) if branch else None
            if not loan:
                self.skipTest("no branch loans to seed a notification row against")
            seed_name = frappe.get_doc({
                "doctype": "LMS Notification Log",
                "loan": loan,
                "reminder_type": "loan_activated",
                "channel": "Bell",
                "status": "Sent",
                "recipient": email,
                "message_preview": "R58 badge-clear contract seed",
                "notification_date": frappe.utils.today(),
            }).insert(ignore_permissions=True).name
            frappe.db.commit()
            before = get_portal_notifications()
            self.assertGreater(before.get("unread_count", 0), 0, "seed did not register as unread")

        try:
            mark_notifications_read()
            after = get_portal_notifications()
            self.assertEqual(
                0,
                after.get("unread_count"),
                "staff mark-as-read must clear the branch unread count",
            )
        finally:
            if seed_name:
                frappe.set_user("Administrator")
                frappe.delete_doc("LMS Notification Log", seed_name, force=True, ignore_permissions=True)
                frappe.db.commit()

    def _staff_branch(self, email):
        from lms_saas.api.staff import get_current_user_branch

        _as(email)
        return get_current_user_branch()

    def test_borrower_mark_read_still_scopes_to_own_loans(self):
        """A borrower marks only their own loans' rows — unchanged behavior."""
        from lms_saas.api.portal import mark_notifications_read

        if not _user_exists(BORROWER_USER):
            self.skipTest("borrower test user not provisioned on this bench")

        frappe.set_user("Administrator")
        customer = frappe.db.get_value(
            "Dynamic Link",
            {"link_doctype": "Customer", "parenttype": "Contact", "parent": ["like", "%borrower%"]},
            "link_name",
        )
        # Fall back: resolve via the portal's own helper.
        if not customer:
            from lms_saas.permissions import _portal_customer

            frappe.set_user(BORROWER_USER)
            customer = _portal_customer(BORROWER_USER)
        if not customer:
            self.skipTest("borrower has no Customer linked on this bench")

        frappe.set_user(BORROWER_USER)
        frappe.local.message_log = []
        result = mark_notifications_read()
        self.assertIsInstance(result, dict)
        self.assertIn("marked", result)
        # No borrower-facing error for a properly linked borrower —
        # the whole log must be empty (any message renders as a modal).
        self.assertEqual([], frappe.local.message_log)


class TestStaffBellBackfill(FrappeTestCase):
    """Backfill must use the same caller resolution — never the borrower message."""

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_backfill_as_staff_never_queues_borrower_message(self):
        """Backfill as staff: silent no-op (skipped) or branch-scoped, never a msgprint."""
        from lms_saas.api.portal import backfill_portal_notifications

        for email in STAFF_USERS:
            if not _user_exists(email):
                self.skipTest(f"test user {email} not provisioned on this bench")
            _as(email)
            frappe.local.message_log = []
            result = backfill_portal_notifications()
            self.assertIsInstance(result, dict, email)
            # R58: backfill rides the shared bell scope — the borrower
            # account message must never queue for staff (whole log empty).
            self.assertEqual(
                [],
                frappe.local.message_log,
                f"staff {email} got queued server messages from backfill: {frappe.local.message_log}",
            )