"""Twilio smoke — sends one real SMS to operator's test number.

Skipped (not failed) when SWEEP_TWILIO_TO is unset. The sweep reports
`twilio smoke skipped` on the summary instead of treating absence as failure.
"""
from __future__ import annotations

import os
import time

import pytest

from utils.auth import login
from utils.evidence import append_result, write_console_dump
from utils.users import get as get_user


@pytest.mark.skipif(
    not os.environ.get("SWEEP_TWILIO_TO"),
    reason="SWEEP_TWILIO_TO not set — Twilio smoke is opt-in",
)
def test_twilio_smoke(page, console, base_url):
    """Sends one SMS to operator's number via the live Twilio whitelist."""
    role = "admin"
    story = "twilio-smoke"
    console.begin_story(story)
    to = os.environ["SWEEP_TWILIO_TO"]

    admin = get_user("admin")
    login(page, base_url, admin["email"], admin["password"])

    detail = ""
    status = "fail"

    # 1. ping
    try:
        ping = page.evaluate(
            """async () => {
                const r = await fetch("/api/method/lms_saas.api.integrations.twilio_api.ping", {
                  credentials: "include",
                });
                return r.json();
            }"""
        )
        if not ping or not ping.get("message", {}).get("enabled"):
            detail = f"Twilio ping reports disabled: {ping}"
        else:
            # 2. send
            sent = page.evaluate(
                f"""async () => {{
                    const r = await fetch("/api/method/lms_saas.api.integrations.twilio_api.send_sms", {{
                        method: "POST",
                        credentials: "include",
                        headers: {{ "Content-Type": "application/json" }},
                        body: JSON.stringify({{
                            to_number: "{to}",
                            body: "LMS-SaaS sweep smoke test @ {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
                            purpose: "Sweep Smoke"
                        }})
                    }});
                    return r.json();
                }}"""
            )
            if sent and sent.get("message"):
                detail = f"SMS queued: {sent.get('message')}"
                status = "pass"
            else:
                detail = f"send_sms response: {sent}"
    except Exception as exc:
        detail = f"twilio smoke exception: {exc}"

    append_result(role, story, status, detail)
    if status != "pass":
        write_console_dump(role, story, list(console.all.get(story, [])))
    console.end_story(story)
    assert status == "pass", detail
