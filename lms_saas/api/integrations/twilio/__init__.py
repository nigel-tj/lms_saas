"""Twilio SMS provider package.

Stable public re-exports:

    from lms_saas.api.integrations.twilio import (
        is_enabled,                # bool
        get_settings,              # dict (PII-stripped; never contains auth_token)
        auth_token,                # returns the plaintext token (server-only)
        send_sms_via_twilio,        # low-level sender
        send_otp,                  # sends + persists an OTP challenge
        verify_otp,                # constant-time verify; locks after N
        parse_inbound_keyword,     # STOP/HELP/START
        handle_status_callback,    # idempotent updater
    )

All higher-level entry points (whitelisted APIs, dispatch_sms_gateway
re-routing, webhook receivers) live in
``lms_saas.api.integrations.twilio_api`` so this package stays an
importable, framework-agnostic core.
"""

from __future__ import annotations

from lms_saas.api.integrations.twilio._send import send_sms_via_twilio
from lms_saas.api.integrations.twilio._settings import (
    auth_token,
    get_settings,
    is_enabled,
)
from lms_saas.api.integrations.twilio._status import handle_status_callback
from lms_saas.api.integrations.twilio._verify import send_otp, verify_otp
from lms_saas.api.integrations.twilio.inbound import parse_inbound_keyword

__all__ = [
    "auth_token",
    "get_settings",
    "handle_status_callback",
    "is_enabled",
    "parse_inbound_keyword",
    "send_otp",
    "send_sms_via_twilio",
    "verify_otp",
]
