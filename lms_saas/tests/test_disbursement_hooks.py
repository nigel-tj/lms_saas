from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

from lms_saas.api.disbursement_hooks import notify_disbursed
from lms_saas.utils.email import get_email_brand_context


class TestDisbursementHooks(unittest.TestCase):
	def test_notify_disbursed_email_failure_is_non_blocking(self):
		doc = SimpleNamespace(
			name="LM-DIS-TEST-0001",
			against_loan="ACC-LOAN-TEST-0001",
			disbursed_amount=1200,
			company="Kesari",
			docstatus=1,
			applicant_type="Customer",
		)

		with mock.patch("lms_saas.api.webhooks.dispatch_webhook_event"), \
			mock.patch("lms_saas.api.disbursement_hooks.send_disbursement_branded_email", side_effect=Exception("email boom")), \
			mock.patch("lms_saas.api.disbursement_hooks.frappe.log_error") as log_error:
			notify_disbursed(doc)

		self.assertTrue(log_error.called)
		self.assertTrue(any(call.kwargs.get("title") == "LMS disbursement email failed" for call in log_error.call_args_list))

	def test_email_brand_context_skips_missing_support_email_field(self):
		meta = mock.Mock()
		meta.has_field.return_value = False
		fake_frappe = SimpleNamespace(
			conf=SimpleNamespace(get=lambda *args, **kwargs: ""),
			db=SimpleNamespace(get_single_value=mock.Mock(side_effect=AssertionError("should not query missing field"))),
			get_meta=mock.Mock(return_value=meta),
		)

		with mock.patch("lms_saas.utils.email.enrich_brand", return_value={"support_email": ""}), \
			mock.patch("lms_saas.utils.email._brand_alias", return_value="LMS"), \
			mock.patch("lms_saas.utils.email.get_brand_logo_url", return_value=""), \
			mock.patch("lms_saas.utils.email.get_brand_favicon_url", return_value=""), \
			mock.patch("lms_saas.utils.email.get_url", return_value="https://lms-saas.frappe.cloud"), \
			mock.patch("lms_saas.utils.email.frappe", fake_frappe):
			context = get_email_brand_context()

		self.assertEqual(context["support_email"], "")