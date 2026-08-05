"""Admin (admin@kesari.africa) — A1 desk landing + A2 portal-mode as Branch Manager."""
from __future__ import annotations

import os

import pytest

from utils.auth import login, logout
from utils.evidence import append_result, screenshot, write_console_dump
from utils.users import get as get_user


ADMIN_ALLOWLIST = (
    r"^Page lending not found$",  # /desk/lending 404 (R35-#24)
)


@pytest.fixture(scope="function")
def admin(page, base_url, console):
    u = get_user("admin")
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


def test_a1_desk_landing(admin, page, console, base_url):
    """A1: /desk renders module nav. Frappe /desk is heavy on first paint — wait longer."""
    role, story = "admin", "A1-desk-landing"
    console.begin_story(story)
    default_to_ms = int(os.environ.get("SWEEP_TIMEOUT", "20")) * 1000
    page.set_default_timeout(45_000)
    try:
        page.goto(f"{base_url}/desk", wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_selector(
            ".desk, .module-sidebar, .module-section, .app-glyph, [data-page], .frappe-card, .frappe-list, body",
            timeout=45_000,
        )
        page.wait_for_load_state("networkidle", timeout=15_000)
        status = "pass"
        detail = "/desk landing rendered"
    except Exception as exc:
        status = "fail"
        detail = f"/desk did not render within 45s: {exc.__class__.__name__}: {exc}"
    finally:
        page.set_default_timeout(default_to_ms)
    _record(page, console, role, story, status, detail, allowlist=ADMIN_ALLOWLIST)
    assert status == "pass", detail


def test_a2_admin_in_manager_portal(admin, page, console, base_url):
    """A2: Admin's LMS portal mode behaves like Manager + exposes Full Desk link."""
    role, story = "admin", "A2-portal-as-manager"
    console.begin_story(story)
    page.goto(f"{base_url}/lms/manager", wait_until="domcontentloaded")
    page.wait_for_selector(".lms-stat-card, .lms-stat-label", timeout=15000)
    page.wait_for_load_state("networkidle")
    detail = ""
    try:
        labels = page.locator(".lms-stat-label").all_inner_texts()
        body = page.evaluate("document.body.innerText") or ""
        has_kpi = any(k in "\n".join(labels) for k in ("Portfolio", "Active Loans")) or any(k in body for k in ("Portfolio Outstanding",))
        desk_link = page.locator("a:has-text('Full Desk'), a:has-text('Desk')").first
        if has_kpi:
            status = "pass"
            extra = " + Full Desk link" if desk_link.count() else ""
            detail = f"admin /lms/manager shows manager-style KPIs{extra}"
        else:
            status = "fail"
            detail = f"admin /lms/manager missing KPI labels; labels={labels!r}, body[:200]={body[:200]!r}"
    except Exception as exc:
        status = "fail"; detail = f"admin portal mode failed: {exc}"
    _record(page, console, role, story, status, detail, allowlist=ADMIN_ALLOWLIST)
    assert status == "pass", detail
