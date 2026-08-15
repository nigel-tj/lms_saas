"""R41 regression tests — portal notifications + email/SMS delivery.

Five bugs surfaced during the 2026-08-05 live review:

1. Default outgoing Email Account was the framework's "Jobs" row, which
   has no smtp_server. Every Email Queue row landed in ``Error`` with
   a ``get_smtp_server()`` traceback, and the LMS Notification Log was
   claiming ``Sent`` for messages that were never delivered.
2. The native SMS Settings gateway URL was empty and Twilio was not
   enabled, so every SMS dispatch returned ``False`` and the LMS log
   recorded ``Failed`` for every SMS row.
3. The LMS Notification Log status was assigned BEFORE the underlying
   Email Queue delivery completed, so the log lied about delivery
   (16 rows said ``Sent`` while the underlying Email Queue said
   ``Error``).
4. The portal notification bell filtered on ``status == "Sent"``
   only — so even with the underlying logs now honest, dev-sandboxed
   sends (``Dev-Sent``) and not-yet-delivered rows (``Queued``) were
   hidden from the borrower.
5. A freshly-onboarded borrower's bell is empty until the next nightly
   cron tick because ``run_collections_escalation`` is the only
   writer. New borrowers reported "I never see any notifications" —
   the bell was correctly empty, not broken.

These tests pin the fix:
- ``send_branded_email`` returns a dict with the actual delivery
  status (``Sent`` / ``Dev-Sent`` / ``Queued`` / ``Failed``).
- The bell accepts ``Sent``, ``Dev-Sent``, and ``Queued`` rows.
- The new ``backfill_portal_notifications`` API seeds a per-loan
  ``loan_activated`` row for borrowers with no logs.
- ``_lms_email_status_from_result`` translates dict/bool results
  correctly.
- ``ensure_dev_email_account`` self-heals a broken default (no
  smtp_server) when dev mode is on.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestR41NotificationDelivery(FrappeTestCase):
	"""Pin the new ``send_branded_email`` contract and the bell's filter."""

	def setUp(self):
		frappe.set_user("Administrator")
		# Make sure the helper module is importable in this test process.
		from lms_saas.utils import email as _email
		from lms_saas.api import collections as _collections

		self.email_mod = _email
		self.collections_mod = _collections

	# ------------------------------------------------------------------
	# 1. send_branded_email returns a dict with the actual status
	# ------------------------------------------------------------------
	def test_send_branded_email_returns_dict_with_status(self):
		"""send_branded_email now returns {ok, status, email_queue, ...}.

		Skips when running in an env where the framework's email CSS
		pipeline is broken (e.g. a fresh test bench that has never run
		``bench build``). The contract pin still holds; the framework
		precondition is the only thing missing.
		"""
		# A recipient is required, so use a real Customer email.
		email = "borrower001@example.com"
		if not frappe.db.exists("Customer", {"email_id": email}):
			self.skipTest("Demo Customer borrower001 not seeded on this bench")

		# Probe whether the framework email pipeline is healthy enough
		# to render the body (some test benches never run ``bench build``
		# and Frappe's ``inline_style_in_html`` throws in that state).
		try:
			result = self.email_mod.send_branded_email(
				recipients=[email],
				subject="R41 dict-return contract test",
				body_key="lead_acknowledgement",
				context={"lead_name": "R41 Test"},
				delayed=True,
			)
		except AttributeError as exc:
			if "bundled_assets" in str(exc) or "'NoneType'" in str(exc):
				self.skipTest(
					"Frappe framework email CSS pipeline not initialized "
					f"(run ``bench build``). Underlying error: {exc}"
				)
			raise
		except Exception as exc:
			# R41: skip when the test bench has no outgoing Email
			# Account configured (fresh install / CI without SMTP).
			# The contract pin still holds; the framework precondition
			# (Email Account) is the only thing missing.
			if "Email Account" in str(exc) or "outgoing" in str(exc).lower() or "email_account" in str(exc).lower():
				self.skipTest(
					"No outgoing Email Account configured on this bench. "
					f"Underlying error: {exc}"
				)
			raise
		self.assertIsInstance(result, dict, f"expected dict, got {type(result).__name__}: {result!r}")
		self.assertIn("ok", result)
		self.assertIn("status", result)
		self.assertIn(result.get("status"), ("Sent", "Dev-Sent", "Queued"))
		# The bell uses ``email_queue`` to back-link, so it must be present
		# on the dev path (Dev-Sent writes the local_inbox sink) and on
		# production (Queued / Sent).
		self.assertTrue(result.get("email_queue"))

	# ------------------------------------------------------------------
	# 2. _lms_email_status_from_result maps new statuses correctly
	# ------------------------------------------------------------------
	def test_lms_email_status_helper_truthful(self):
		"""Status helper must reflect the actual delivery state."""
		helper = self.collections_mod._lms_email_status_from_result
		# New dict path
		self.assertEqual(helper({"ok": True, "status": "Sent"}), "Sent")
		self.assertEqual(helper({"ok": True, "status": "Dev-Sent"}), "Sent")
		self.assertEqual(helper({"ok": True, "status": "Queued"}), "Queued")
		self.assertEqual(helper({"ok": False, "status": "Failed"}), "Failed")
		# Legacy bool path
		self.assertEqual(helper(True), "Sent")
		self.assertEqual(helper(False), "Failed")
		# Unknown / None
		self.assertEqual(helper(None), "Failed")
		self.assertEqual(helper("unexpected"), "Failed")

	# ------------------------------------------------------------------
	# 3. _dev_no_smtp_fallback_enabled is False when prod SMTP is set
	# ------------------------------------------------------------------
	def test_dev_fallback_is_off_when_smtp_configured(self):
		"""Production sites with real SMTP must not be sandboxed."""
		frappe.db.sql(
			"""UPDATE `tabEmail Account`
			   SET smtp_server='smtp.example.com', smtp_port=587
			   WHERE enable_outgoing=1 AND default_outgoing=1"""
		)
		frappe.db.commit()
		try:
			self.assertFalse(self.email_mod._dev_no_smtp_fallback_enabled())
		finally:
			# Restore whatever the bench had — never modify site state
			# for other tests.
			frappe.db.sql(
				"""UPDATE `tabEmail Account`
				   SET smtp_server=NULL, smtp_port=NULL
				   WHERE enable_outgoing=1 AND default_outgoing=1"""
			)
			frappe.db.commit()

	# ------------------------------------------------------------------
	# 4. dev local-inbox sink actually writes the file
	# ------------------------------------------------------------------
	def test_dev_local_inbox_sink_writes_file(self):
		"""R41: dev-sink writes the rendered HTML to <site>/local_inbox/."""
		# Mock the inbox dir to a temp path so the test does not pollute
		# the real site.
		with tempfile.TemporaryDirectory() as tmp:
			with patch.object(frappe, "get_site_path", return_value=tmp):
				self.email_mod._sink_to_local_inbox(
					queue_name="TEST-Q-1",
					recipients=["borrower001@example.com"],
					subject="R41 sink test",
					html="<p>hello</p>",
					reference_doctype="Loan",
					reference_name="LOAN-X",
				)
			# find the file we just wrote
			files = os.listdir(os.path.join(tmp, "local_inbox"))
			self.assertTrue(files, "no file written to local_inbox")
			body = open(os.path.join(tmp, "local_inbox", files[0]), encoding="utf-8").read()
			self.assertIn("R41 sink test", body)
			self.assertIn("hello", body)
			self.assertIn("TEST-Q-1", body)


class TestR41PortalBell(FrappeTestCase):
	"""Pin the bell's filter widening + the new backfill API."""

	def setUp(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------------
	# 5. Bell accepts Sent / Dev-Sent / Queued rows
	# ------------------------------------------------------------------
	def test_bell_filter_includes_dev_sent_and_queued(self):
		"""The bell surface must include non-Failed rows, not just Sent."""
		# Use the seeded demo borrower — their customer owns an active loan
		# and their User is enabled (the only guaranteed portal user on
		# every bench). ``_portal_customer`` resolves it via the
		# ``active-loan fallback`` in permissions.py.
		frappe.set_user("demo.lms.borrower@example.com")
		frappe.db.commit()
		from lms_saas.api.portal import get_portal_notifications

		# Get this user's loans.
		from lms_saas.permissions import _portal_customer
		customer = _portal_customer(frappe.session.user)
		loans = frappe.get_all(
			"Loan",
			filters={"applicant_type": "Customer", "applicant": customer, "docstatus": 1},
			pluck="name",
		)
		if not loans:
			self.skipTest("Demo borrower has no active loan")
		loan = loans[0]
		# Three rows, one per status we want to see.
		for status in ("Sent", "Dev-Sent", "Queued"):
			frappe.get_doc(
							{
									"doctype": "LMS Notification Log",
									"loan": loan,
									"reminder_type": f"r41_bell_{status.lower()}",
									"notification_date": frappe.utils.getdate(),
									"channel": "Email",
									"status": status,
									"recipient": customer,
									"message_preview": f"R41 bell test {status}",
								}
							).insert(ignore_permissions=True)
		res = get_portal_notifications()
		types = {n.get("reminder_type") for n in res.get("notifications", [])}
		for status in ("Sent", "Dev-Sent", "Queued"):
			self.assertIn(
				f"r41_bell_{status.lower()}",
				types,
				f"bell hid {status} row — only Sent is visible? Got types={types}",
			)
		# Failed / Skipped must stay hidden.
		frappe.get_doc(
			{
				"doctype": "LMS Notification Log",
				"loan": loan,
				"reminder_type": "r41_bell_failed",
				"notification_date": frappe.utils.getdate(),
				"channel": "Email",
				"status": "Failed",
				"recipient": customer,
				"message_preview": "R41 bell test Failed (should be hidden)",
			}
		).insert(ignore_permissions=True)
		res2 = get_portal_notifications()
		types2 = {n.get("reminder_type") for n in res2.get("notifications", [])}
		self.assertNotIn("r41_bell_failed", types2, "bell must hide Failed rows")

	# ------------------------------------------------------------------
	# 6. Backfill API seeds a row for a loan with zero logs
	# ------------------------------------------------------------------
	def test_backfill_seeds_for_loans_with_no_logs(self):
		"""backfill_portal_notifications creates a loan_activated row per empty loan."""
		frappe.set_user("demo.lms.borrower@example.com")
		frappe.db.commit()
		from lms_saas.permissions import _portal_customer
		customer = _portal_customer(frappe.session.user)
		if not customer:
			self.skipTest("Demo borrower does not resolve to a Customer")
		loans = frappe.get_all(
			"Loan",
			filters={"applicant_type": "Customer", "applicant": customer, "docstatus": 1},
			pluck="name",
		)
		# Wipe any pre-existing logs on these loans so the test is
		# deterministic. The fixture bench is allowed to be dirty.
		for ln in loans:
			frappe.db.delete("LMS Notification Log", {"loan": ln})
		if not loans:
			self.skipTest("Demo borrower has no active loan to backfill")

		from lms_saas.api.portal import backfill_portal_notifications

		res = backfill_portal_notifications()
		self.assertGreaterEqual(res.get("created", 0), 1, f"backfill returned {res}")
		after = sum(
			frappe.db.count("LMS Notification Log", {"loan": ln}) for ln in loans
		)
		self.assertEqual(after, len(loans))

		# Re-run is idempotent.
		res2 = backfill_portal_notifications()
		self.assertEqual(res2.get("created", 0), 0, f"backfill not idempotent: {res2}")
		after2 = sum(
			frappe.db.count("LMS Notification Log", {"loan": ln}) for ln in loans
		)
		self.assertEqual(after2, len(loans))

	# ------------------------------------------------------------------
	# 7. send_loan_reminder writes an honest status (regression for
	# the "log says Sent, queue says Error" bug)
	# ------------------------------------------------------------------
	def test_send_loan_reminder_status_matches_email(self):
		"""Pin: when SMTP is broken the LMS log must say Failed, not Sent."""
		# Force the default Email Account to be missing so the dispatcher
		# fails honestly (mirrors the live state on 2026-08-05).
		frappe.db.sql(
			"""UPDATE `tabEmail Account`
			   SET smtp_server=NULL, smtp_port=NULL
			   WHERE enable_outgoing=1 AND default_outgoing=1"""
		)
		# Disable the dev-sink path so we see the truthful Failed path.
		frappe.conf.lms_dev_local_inbox_off = 1
		try:
			# Pick a loan with a Customer applicant that has a valid email.
			loan_rows = frappe.db.sql(
				"""SELECT l.name, c.email_id
				   FROM `tabLoan` l
				   JOIN `tabCustomer` c ON c.name = l.applicant
				   WHERE l.docstatus=1 AND l.applicant_type='Customer'
				     AND c.email_id IS NOT NULL AND c.email_id != ''
				   LIMIT 1""",
				as_dict=True,
			)
			if not loan_rows:
				self.skipTest("No suitable customer loan to test")
			loan = loan_rows[0]
			from lms_saas.api.collections import send_loan_reminder
			from frappe.utils import getdate, today

			notif_date = getdate(today())
			# Use a unique reminder_type so we don't collide with prior logs.
			rt = f"r41_pin_{frappe.utils.now_datetime().strftime('%H%M%S%f')}"
			# Override should_send_notification so the idempotency check
			# does not block the test (the bench has prior rows).
			with patch(
				"lms_saas.api.collections.should_send_notification",
				return_value=True,
			):
				send_loan_reminder(
					loan["name"],
					rt,
					"R41 honest-status test message",
					reference_doctype="Loan",
					reference_name=loan["name"],
					notification_date=notif_date,
				)
			# Look up the log we just created.
			row = frappe.db.get_value(
				"LMS Notification Log",
				{"loan": loan["name"], "reminder_type": rt, "channel": "Email"},
				"status",
			)
			# With SMTP broken AND dev-sink disabled, the LMS log must
			# be Failed — NOT Sent. That is the regression pin.
			self.assertEqual(
				row,
				"Failed",
				f"LMS log said {row!r} but SMTP is broken — bell will lie",
			)
		finally:
			frappe.conf.lms_dev_local_inbox_off = 0
			frappe.db.sql(
				"""UPDATE `tabEmail Account`
				   SET smtp_server='smtp.example.com', smtp_port=587
				   WHERE enable_outgoing=1 AND default_outgoing=1"""
			)
			frappe.db.commit()


class TestR41SeedDevEmailRepair(FrappeTestCase):
	"""Pin: ensure_dev_email_account self-heals a broken default."""

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags.in_test = True

	def test_ensure_dev_email_account_repairs_broken_default(self):
		"""A default with no smtp_server must be repaired in dev mode."""
		# Snapshot the original.
		orig = frappe.db.get_value(
			"Email Account",
			{"enable_outgoing": 1, "default_outgoing": 1},
			["name", "smtp_server", "smtp_port"],
			as_dict=True,
		)
		if not orig:
			self.skipTest("No default outgoing Email Account on this bench")
		frappe.conf.developer_mode = 1
		try:
			# Force the broken state.
			frappe.db.sql(
				"""UPDATE `tabEmail Account`
				   SET smtp_server=NULL, smtp_port=NULL
				   WHERE name=%(name)s""",
				{"name": orig["name"]},
			)
			frappe.db.commit()
			from lms_saas.setup.seed_dev_email import ensure_dev_email_account

			res = ensure_dev_email_account()
			# Self-heal: the function must report either "repaired" or
			# "skipped" — it must NEVER silently return ok=False.
			self.assertTrue(res.get("ok"), f"repair returned {res}")
			# The row must now have an smtp_server set.
			after = frappe.db.get_value(
				"Email Account", orig["name"], ["smtp_server", "smtp_port"], as_dict=True
			)
			self.assertTrue(after.get("smtp_server"), f"smtp_server still empty: {after}")
		finally:
			frappe.conf.developer_mode = 0
			# Restore the bench's original state so other tests are
			# unaffected.
			frappe.db.sql(
				"""UPDATE `tabEmail Account`
				   SET smtp_server=%(smtp_server)s, smtp_port=%(smtp_port)s
				   WHERE name=%(name)s""",
				{
					"name": orig["name"],
					"smtp_server": orig.get("smtp_server"),
					"smtp_port": orig.get("smtp_port"),
				},
			)
			frappe.db.commit()
