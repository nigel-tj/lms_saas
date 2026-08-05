"""Collector (collector@kesari.africa) — C1 + C2.

R25 regression: 'Failed to create chart' console error must not appear.
"""
from __future__ import annotations

import pytest

from utils.auth import login, logout
from utils.evidence import append_result, screenshot, write_console_dump
from utils.users import get as get_user


COLLECTOR_ALLOWLIST = (
    r"^Page lending not found$",  # /desk/lending 404 (R35-#24)
)


@pytest.fixture(scope="function")
def collector(page, base_url, console):
    u = get_user("collector")
    login(page, base_url, u["email"], u["password"])
    yield page
    logout(page, base_url)


def _record(page, console, role, story, status, detail="", allowlist=()):
    append_result(role, story, status, detail)
    if status != "pass":
        write_console_dump(role, story, list(console.all.get(story, [])))
    try:
        screenshot(page, role, story)
    except Exception:
        pass
    offenders = console.end_story(story, allowlist=allowlist)
    if status == "pass" and offenders:
        append_result(role, story + "-console-gate", "fail",
                      f"unfiltered console errors: {[o['text'][:80] for o in offenders]}")


def test_c1_field_collection(collector, page, console, base_url):
    role, story = "collector", "C1-field-collection"
    console.begin_story(story)
    page.goto(f"{base_url}/lms/collect", wait_until="domcontentloaded")
    page.wait_for_selector(".lms-page-header, .lms-panel, .lms-stat-card, .lms-empty, .lms-error", timeout=15000)
    page.wait_for_load_state("networkidle")
    detail = ""
    try:
        body = page.evaluate("document.body.innerText") or ""
        labels = page.locator(".lms-stat-label, .lms-summary-label").all_inner_texts()
        all_text = "\n".join([body] + labels)
        if any(k in all_text for k in ("Online", "Offline", "Stops today", "Amount due", "Offline queue", "Run")):
            status = "pass"
            detail = "collector landing rendered with KPIs/run surface"
        else:
            status = "fail"
            detail = "no Online/Offline/Stops today/Run surface"
    except Exception as exc:
        status = "fail"; detail = f"collector landing selector wait failed: {exc}"
    _record(page, console, role, story, status, detail, allowlist=COLLECTOR_ALLOWLIST)
    assert status == "pass", detail


def test_c2_run_sheet(collector, page, console, base_url):
    role, story = "collector", "C2-run-sheet"
    console.begin_story(story)
    page.goto(f"{base_url}/lms/collect", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    detail = ""
    try:
        page.wait_for_selector("table.lms-data-table, .lms-empty, .lms-panel", timeout=10000)
        status = "pass"
        detail = "run sheet renders (table or empty state)"
    except Exception as exc:
        status = "fail"; detail = f"run sheet failed: {exc}"
    _record(page, console, role, story, status, detail, allowlist=COLLECTOR_ALLOWLIST)
    assert status == "pass", detail
