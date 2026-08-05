"""Read-only persona re-check: field, supervisor, senior.collector.

The sweep does not re-run every story — it just asserts landing renders at
the persona's expected URL + SPA shell renders without 404.

Allow-list includes 'Page lending not found' (R35-#24) because the senior
collector's login redirect historically went to /desk/lending before that
fix; if it's still hitting that path on live, the C1/C2 collector tests
above are the proper regression check, and this smoke ignores it.
"""
from __future__ import annotations

import pytest

from utils.auth import login, logout
from utils.evidence import append_result, screenshot, write_console_dump
from utils.users import get as get_user


READ_ONLY_USERS = ("field", "supervisor", "senior")
ALLOWLIST = (r"^Page lending not found$",)


def _record(page, console, role, story, status, detail=""):
    append_result(role, story, status, detail)
    if status != "pass":
        write_console_dump(role, story, list(console.all.get(story, [])))
    try:
        screenshot(page, role, story)
    except Exception:
        pass
    offenders = console.end_story(story, allowlist=ALLOWLIST)
    if status == "pass" and offenders:
        append_result(role, story + "-console-gate", "fail",
                      f"unfiltered console errors: {[o['text'][:80] for o in offenders]}")


@pytest.mark.parametrize("user_key", READ_ONLY_USERS)
def test_read_only_landing(page, console, base_url, user_key):
    u = get_user(user_key)
    login(page, base_url, u["email"], u["password"])
    role = user_key
    story = f"{user_key}-landing"
    console.begin_story(story)
    page.goto(f"{base_url}{u['landing']}", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    detail = ""
    status = "fail"
    try:
        page.wait_for_selector(
            "body, .lms-page-header, .lms-panel, .lms-stat-card, .lms-empty, .lms-error",
            timeout=15000,
        )
        body_text = page.evaluate("document.body.innerText") or ""
        if "404" in body_text or "Not Found" in body_text:
            detail = f"404 page rendered for {user_key}; expected {u['landing']} (R35-#24 redirect?)"
            status = "fail"
        else:
            status = "pass"
            detail = f"{user_key} landing reached at {u['landing']}"
    except Exception as exc:
        detail = f"landing failed for {user_key}: {exc}"
    _record(page, console, role, story, status, detail)
    logout(page, base_url)
    assert status == "pass", detail
