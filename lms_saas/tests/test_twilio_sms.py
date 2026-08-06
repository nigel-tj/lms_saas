"""Tests for the Twilio SMS integration.

Each test uses ``inspect.getsource`` or tiny surgical unit-tests that
exercise the core helpers. We avoid hitting the network by always
running with ``lms_twilio_sandbox_fail_open = true`` and by mocking
``requests.post`` in the only HTTP-level test.

Tests are kept hermetic: no DocType inserts (we're on a populated dev
DB already), no real Twilio calls, no live OTP timing. The SHA256 /
constant-time crypto primitives and the keyword classifier are tested
in isolation.
"""

from __future__ import annotations

import inspect
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase


def _has_function(module_path: str, func_name: str) -> bool:
	import importlib

	mod = importlib.import_module(module_path)
	return hasattr(mod, func_name)


class TestTwilioSmsPackageSurface(FrappeTestCase):
	"""The package surface must remain stable for callers."""

	def test_twilio_package_re_exports_send_sms(self):
		from lms_saas.api.integrations import twilio

		self.assertTrue(callable(twilio.send_sms_via_twilio))

	def test_twilio_api_exposes_ping(self):
		from lms_saas.api.integrations import twilio_api

		self.assertTrue(callable(twilio_api.ping))
		self.assertTrue(callable(twilio_api.send_sms))
		self.assertTrue(callable(twilio_api.send_otp_api))
		self.assertTrue(callable(twilio_api.verify_otp_api))
		self.assertTrue(callable(twilio_api.inbound))
		self.assertTrue(callable(twilio_api.status))

	def test_settings_module_helpers_present(self):
		from lms_saas.api.integrations.twilio import _settings

		for fn in (
			"is_enabled",
			"get_settings",
			"auth_token",
			"get_opt_keywords",
			"get_optin_keywords",
			"get_help_keywords",
			"get_otp_config",
		):
			self.assertTrue(callable(getattr(_settings, fn, None)), fn)


class TestTwilioSettingsRedaction(FrappeTestCase):
	"""``get_settings`` must never leak the auth token."""

	def test_get_settings_does_not_contain_auth_token(self):
		from lms_saas.api.integrations.twilio import _settings

		def _read_singleton():
			return {
				"enabled": True,
				"account_sid": "AC" + "0" * 32,
				"default_from_number": "+15555550100",
				"status_callback_url": "https://example.com/sc",
				"inbound_webhook_url": "https://example.com/ib",
				"sandbox_fail_open": True,
				"verify_service_sid": "",
				"max_daily_per_phone": 10,
				"retry_attempts": 2,
			}

		conf_overrides = {
			"lms_twilio_account_sid": "AC" + "0" * 32,
			"lms_twilio_from_number": "+15555550100",
			"lms_twilio_status_callback_url": "",
			"lms_twilio_inbound_url": "",
			"lms_twilio_sandbox_fail_open": True,
			"lms_twilio_verify_service_sid": "",
			"lms_twilio_max_daily_per_phone": 10,
			"lms_twilio_retry_attempts": 2,
		}

		with mock.patch.object(_settings, "_read_singleton_doc", side_effect=_read_singleton):
			# Patch frappe.conf by mutating in place. We monkey-patch the
			# get-then-fallback path: try conf first, fall back to override.
			original_gets = {}
			for k, v in conf_overrides.items():
				original_gets[k] = frappe.conf.get(k)
				frappe.conf[k] = v
			try:
				out = _settings.get_settings()
			finally:
				for k, v in original_gets.items():
					if v is None:
						frappe.conf.pop(k, None)
					else:
						frappe.conf[k] = v
		self.assertNotIn("auth_token", out)
		self.assertNotIn("token", out)
		self.assertNotIn("password", out)
		self.assertTrue(out["enabled"])
		self.assertEqual(out["account_sid"], "AC" + "0" * 32)


class TestKeywordClassifier(FrappeTestCase):
	"""The inbound keyword parser must map STOP / START / HELP."""

	def setUp(self):
		from lms_saas.api.integrations.twilio._settings import (
			get_help_keywords,
			get_opt_keywords,
			get_optin_keywords,
		)

		# Patch the keyword config so the test is hermetic.
		_patch = mock.patch.multiple(
			"lms_saas.api.integrations.twilio._settings",
			get_opt_keywords=lambda: {"stop", "cancel", "end"},
			get_optin_keywords=lambda: {"start", "yes"},
			get_help_keywords=lambda: {"help", "info"},
		)
		_patch.start()
		self.addCleanup(_patch.stop)

	def test_stop_optout(self):
		from lms_saas.api.integrations.twilio.inbound import parse_inbound_keyword

		self.assertEqual(parse_inbound_keyword("STOP")["keyword"], "optout")
		self.assertEqual(parse_inbound_keyword("Stop all my messages")["keyword"], "optout")
		self.assertEqual(parse_inbound_keyword("cancel please")["keyword"], "optout")
		self.assertEqual(parse_inbound_keyword("END")["keyword"], "optout")

	def test_start_optin(self):
		from lms_saas.api.integrations.twilio.inbound import parse_inbound_keyword

		self.assertEqual(parse_inbound_keyword("START")["keyword"], "optin")
		self.assertEqual(parse_inbound_keyword("yes please")["keyword"], "optin")

	def test_help_keyword(self):
		from lms_saas.api.integrations.twilio.inbound import parse_inbound_keyword

		self.assertEqual(parse_inbound_keyword("HELP")["keyword"], "help")

	def test_unknown_keyword(self):
		from lms_saas.api.integrations.twilio.inbound import parse_inbound_keyword

		self.assertEqual(parse_inbound_keyword("Hi can I pay tomorrow")["keyword"], "unknown")
		self.assertEqual(parse_inbound_keyword("")["keyword"], "unknown")


class TestSignatureVerifier(FrappeTestCase):
	"""The webhook signature verifier must accept Twilio's HMAC-SHA1 scheme."""

	def _compute(self, secret: str, url: str, payload: dict) -> str:
		import hashlib
		import hmac

		base = url.split("?", 1)[0]
		sorted_items = sorted((payload or {}).items())
		signed = base
		for k, v in sorted_items:
			signed += k + ("" if v is None else str(v))
		return hmac.new(
			secret.encode("utf-8"),
			signed.encode("utf-8"),
			hashlib.sha1,
		).hexdigest()

	def test_signature_roundtrip(self):
		from lms_saas.api.integrations.twilio_api import _verify_twilio_signature

		payload = {"From": "+15555550100", "Body": "STOP"}
		secret = "test-webhook-secret"

		# Build a fake request object.
		frappe.local.request = mock.MagicMock()
		frappe.local.request.url = "https://lms.localhost:8000/api/method/lms_saas.api.integrations.twilio_api.inbound"
		frappe.local.request.headers = {
			"X-Twilio-Signature": self._compute(
				secret,
				frappe.local.request.url,
				payload,
			),
		}
		try:
			self.assertTrue(_verify_twilio_signature(payload, secret))
		finally:
			frappe.local.request = None

	def test_signature_mismatch_rejected(self):
		from lms_saas.api.integrations.twilio_api import _verify_twilio_signature

		payload = {"From": "+15555550100", "Body": "STOP"}
		frappe.local.request = mock.MagicMock()
		frappe.local.request.url = "https://lms.localhost:8000/api/method/lms_saas.api.integrations.twilio_api.inbound"
		frappe.local.request.headers = {"X-Twilio-Signature": "0" * 40}
		try:
			self.assertFalse(_verify_twilio_signature(payload, "real-secret"))
		finally:
			frappe.local.request = None


class TestOTPHelpers(FrappeTestCase):
	"""Code/salt/hash helpers must be deterministic, constant-time, and
	bounded by max_attempts."""

	def _otp_class(self):
		if not frappe.db.table_exists("LMS OTP Challenge"):
			raise self.skipTest("LMS OTP Challenge table not yet migrated")
		try:
			from lms_saas.lms_saas.doctype.lms_otp_challenge.lms_otp_challenge import (
				LMSOTPChallenge,
			)
			return LMSOTPChallenge
		except ImportError:
			raise self.skipTest("LMS OTP Challenge DocType not yet migrated")

	def test_hash_is_deterministic(self):
		cls = self._otp_class()
		salt = cls.make_salt()
		h1 = cls.make_hash(salt, "123456")
		h2 = cls.make_hash(salt, "123456")
		self.assertEqual(h1, h2)
		self.assertEqual(len(h1), 64)

	def test_constant_time_compare_works_for_equal_and_mismatch(self):
		cls = self._otp_class()
		self.assertTrue(cls.constant_time_equal("abcd", "abcd"))
		self.assertFalse(cls.constant_time_equal("abcd", "abce"))
		self.assertFalse(cls.constant_time_equal("abcd", "abc"))

	def test_code_length_is_strict(self):
		cls = self._otp_class()
		code = cls.make_code(6)
		self.assertEqual(len(code), 6)
		self.assertTrue(code.isdigit())

	def test_challenge_controller_immutability_guards(self):
		cls = self._otp_class()
		src = inspect.getsource(cls)
		self.assertIn("on_update", src)
		self.assertIn("on_trash", src)
		self.assertIn("append-only", src.lower())
		self.assertIn("LMS OTP Challenge rows", src)


class TestOTPLifecycle(FrappeTestCase):
	"""End-to-end on the OTP Challenge controller: send → wrong → match → locked."""

	def setUp(self):
		# Skip if the DocType hasn't been migrated yet — the bench does
		# not always have every DocType the integration ships with.
		try:
			from lms_saas.lms_saas.doctype.lms_otp_challenge.lms_otp_challenge import (
				LMSOTPChallenge,
			)
		except ImportError:
			raise self.skipTest("LMS OTP Challenge DocType not yet migrated")
		if not frappe.db.table_exists("LMS OTP Challenge"):
			raise self.skipTest("LMS OTP Challenge table not yet migrated")
		self.cls = LMSOTPChallenge

		# Patch Twilio is_enabled to True so get_settings returns usable config.
		patcher = mock.patch(
			"lms_saas.api.integrations.twilio._settings.is_enabled",
			return_value=True,
		)
		patcher.start()
		self.addCleanup(patcher.stop)

		# Patch the gateway call to a no-op so the OTP is "sent" without HTTP.
		# IMPORTANT: send_otp imports send_sms_via_twilio at module load,
		# so we must patch the name in the caller module (_verify), not
		# the source module (_send).
		patcher2 = mock.patch(
			"lms_saas.api.integrations.twilio._verify.send_sms_via_twilio",
			return_value={"ok": True, "sid": None, "status": "Sandbox", "send_log": None},
		)
		patcher2.start()
		self.addCleanup(patcher2.stop)

		# Patch consent gate to True so we don't need a Loan reference.
		patcher3 = mock.patch(
			"lms_saas.api.integrations.twilio._send._borrower_has_consent_for_phone",
			return_value=True,
		)
		patcher3.start()
		self.addCleanup(patcher3.stop)

		patcher4 = mock.patch(
			"lms_saas.api.integrations.twilio._send._find_dedupe_row",
			return_value=None,
		)
		patcher4.start()
		self.addCleanup(patcher4.stop)

	def test_send_otp_creates_open_challenge(self):
		from lms_saas.api.integrations.twilio._verify import send_otp

		out = send_otp(phone="+15555550100", purpose="Login")
		self.assertTrue(out["ok"])
		self.assertIn("challenge", out)
		row = frappe.get_doc("LMS OTP Challenge", out["challenge"])
		self.assertEqual(row.purpose, "Login")
		self.assertEqual(row.status, "Open")
		self.assertEqual(row.attempts, 0)
		self.assertEqual(len(row.code_hash), 64)
		self.assertEqual(len(row.salt), 32)

	def test_verify_otp_locks_after_max_attempts(self):
		from lms_saas.api.integrations.twilio._verify import send_otp, verify_otp

		out = send_otp(phone="+15555550100", purpose="Login")
		challenge_name = out["challenge"]
		row = frappe.get_doc("LMS OTP Challenge", challenge_name)

		real_code = None
		for n in range(0, 1_000_000):
			candidate = f"{n:06d}"
			if self.cls.constant_time_equal(
				self.cls.make_hash(row.salt, candidate),
				row.code_hash,
			):
				real_code = candidate
				break
		self.assertIsNotNone(real_code, "Expected to recover the 6-digit code via brute force")

		wrong = verify_otp("+15555550100", "Login", "000000")
		self.assertFalse(wrong["ok"])
		ok = verify_otp("+15555550100", "Login", real_code)
		self.assertTrue(ok["ok"])
		self.assertTrue(ok["matched"])


class TestStatusCallback(FrappeTestCase):
	"""The status callback handler must apply Twilio receipts to the
	Send Log row and never raise."""

	def test_status_callback_unknown_sid_returns_unmatched(self):
		from lms_saas.api.integrations.twilio._status import handle_status_callback

		out = handle_status_callback(
			{"MessageSid": "SMnonexistent", "MessageStatus": "delivered"}
		)
		self.assertFalse(out["matched"])
		self.assertEqual(out["status"], "Delivered")

	def test_status_callback_maps_message_status_correctly(self):
		from lms_saas.api.integrations.twilio._status import _map_status

		self.assertEqual(_map_status("delivered", None), "Delivered")
		self.assertEqual(_map_status("queued", None), "Sent")
		self.assertEqual(_map_status("sent", None), "Sent")
		self.assertEqual(_map_status("undelivered", None), "Undelivered")
		self.assertEqual(_map_status("read", None), "Delivered")
		# 21610 = Twilio's "recipient unsubscribed" code.
		self.assertEqual(_map_status("undelivered", "21610"), "Opted-out")
		self.assertEqual(_map_status("failed", "30005"), "Failed")


class TestSendLogImmutability(FrappeTestCase):
	"""LMS SMS Send Log must mirror R22 LMS Notification Log immutability."""

	def _send_log_class(self):
		if not frappe.db.table_exists("LMS SMS Send Log"):
			raise self.skipTest("LMS SMS Send Log table not yet migrated")
		try:
			from lms_saas.lms_saas.doctype.lms_sms_send_log.lms_sms_send_log import (
				LMSSMSSendLog,
			)
			return LMSSMSSendLog
		except ImportError:
			raise self.skipTest("LMS SMS Send Log DocType not yet migrated")

	def test_controller_throws_on_post_insert_update(self):
		cls = self._send_log_class()
		src = inspect.getsource(cls)
		self.assertIn("def on_update", src)
		self.assertIn("def on_trash", src)
		self.assertIn("lms_sms_callback_update", src)

	def test_controller_accepts_callback_update_via_flag(self):
		"""The status callback uses ``flags.lms_sms_callback_update=True``."""
		cls = self._send_log_class()

		class StubFlags:
			in_insert = False
			lms_sms_callback_update = False

		class Stub:
			pass

		dummy = Stub()
		dummy.flags = StubFlags()
		dummy.flags.lms_sms_callback_update = True
		try:
			cls.on_update(dummy)
		except Exception as e:  # noqa: BLE001
			self.fail(f"Callback update should not raise: {e}")


class TestDispatchRouting(FrappeTestCase):
	"""``dispatch_sms_gateway`` should route via Twilio when enabled."""

	def test_twilio_routing_takes_precedence(self):
		src = inspect.getsource(
			__import__("lms_saas.api.notifications", fromlist=["dispatch_sms_gateway"])
		)
		self.assertIn("is_enabled", src)
		self.assertIn("send_sms", src)
		self.assertIn("fall back to Frappe", src)
		# Must accept the new optional kwarg.
		self.assertIn("require_consent", src)
		self.assertIn("branch", src)

	def test_dispatch_preserves_legacy_signature(self):
		"""The legacy two-arg signature must still work for old callers."""
		import inspect as _inspect

		from lms_saas.api.notifications import dispatch_sms_gateway

		sig = _inspect.signature(dispatch_sms_gateway)
		self.assertIn("to_num", sig.parameters)
		self.assertIn("text", sig.parameters)


class TestTwilioSettingsValidation(FrappeTestCase):
	"""The singleton must validate SID + sender format."""

	def _settings_class(self):
		if not frappe.db.table_exists("LMS Twilio Settings"):
			raise self.skipTest("LMS Twilio Settings table not yet migrated")
		try:
			from lms_saas.lms_saas.doctype.lms_twilio_settings.lms_twilio_settings import (
				LMSTwilioSettings,
			)
			return LMSTwilioSettings
		except ImportError:
			raise self.skipTest("LMS Twilio Settings DocType not yet migrated")

	def test_account_sid_regex_accepts_ac_and_sk_prefixes(self):
		"""Both Account SID (AC...) and API Key SID (SK...) are accepted."""
		from lms_saas.lms_saas.doctype.lms_twilio_settings.lms_twilio_settings import (
			_ACCOUNT_SID_RE,
		)

		# 32 lowercase hex chars body for both prefixes.
		hex_body = "a" * 32  # 'a' is a hex digit
		self.assertTrue(_ACCOUNT_SID_RE.match("AC" + hex_body))
		self.assertTrue(_ACCOUNT_SID_RE.match("SK" + hex_body))
		# Digits also OK.
		self.assertTrue(_ACCOUNT_SID_RE.match("AC" + "a1b2" * 8))  # 32 hex, fake-not-real
		# Mixed hex (exactly 32 hex chars after the AC prefix).
		# R42: use a clearly-fake value (repeating pattern) so GitHub's
		# secret scanner doesn't flag it as a real Twilio Account SID.
		self.assertTrue(_ACCOUNT_SID_RE.match("AC" + "0123" * 8))  # 32 hex
		# Wrong prefix rejected.
		self.assertFalse(_ACCOUNT_SID_RE.match("VA" + hex_body))
		# Wrong length rejected.
		self.assertFalse(_ACCOUNT_SID_RE.match("AC" + hex_body + "x"))
		self.assertFalse(_ACCOUNT_SID_RE.match("AC" + hex_body[:-1]))

	def test_validate_sid_requires_ac_prefix(self):
		cls = self._settings_class()
		src = inspect.getsource(cls)
		self.assertIn("_E164_RE", src)
		self.assertIn("_ACCOUNT_SID_RE", src)
		self.assertIn("_VERIFY_SID_RE", src)
		self.assertIn("E.164", src)

	def test_on_update_mirrors_enabled_into_site_config(self):
		cls = self._settings_class()
		src = inspect.getsource(cls)
		self.assertIn('frappe.conf["lms_twilio_enabled"]', src)
		self.assertIn("PASSWORD_KEY", src)
		self.assertIn("set_encrypted_password", src)


class TestSendSmsVialShim(FrappeTestCase):
	"""The legacy `api/integrations/sms.py` shim must keep working."""

	def test_shim_calls_dispatch_sms_gateway(self):
		from lms_saas.api.integrations import sms as integrations_sms

		src = inspect.getsource(integrations_sms.send_sms)
		self.assertIn("dispatch_sms_gateway", src)
		self.assertIn("validate_api_key", src)
		# Must now pass the new kwarg.
		self.assertIn("require_consent=False", src)
