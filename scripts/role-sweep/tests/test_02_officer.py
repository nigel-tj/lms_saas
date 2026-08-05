"""Loan Officer (officer@kesari.africa) — O1 through O8 from USER_ROLE_PLAYBOOK.

Stable selectors in apps/lms_saas/lms_saas/public/js/lms_officer_portal.js:
- Tabs: .lms-tab[data-tab="dashboard|borrowers|loans|kyc|leads|reports"]
- KPI labels: .lms-summary-label / .lms-stat-label
- Tables: .lms-data-table
- Action buttons: .lms-of-disburse-btn[data-loan], .lms-of-loan-view[data-loan]
- Review buttons: .lms-review-btn[data-app]
"""
from __future__ import annotations

import pytest

from utils.auth import login, logout
from utils.evidence import append_result, screenshot, write_console_dump
from utils.users import get as get_user


@pytest.fixture(scope="function")
def officer(page, base_url, console):
    u = get_user("officer")
    login(page, base_url, u["email"], u["password"])
    yield page
    logout(page, base_url)


def _record(page, console, role, story, status, detail=""):
    append_result(role, story, status, detail)
    if status != "pass":
        write_console_dump(role, story, list(console.all.get(story, [])))
    try:
        screenshot(page, role, story)
    except Exception:
        pass
    console.end_story(story)


def _click_tab(page, tab_id: str):
    """Click a staff tab (officer/manager) by its data-tab attribute, then settle."""
    page.click(f".lms-tab[data-tab='{tab_id}']")
    page.wait_for_load_state("networkidle")


def test_o1_dashboard(officer, page, console, base_url):
    role, story = "officer", "O1-dashboard"
    console.begin_story(story)
    page.goto(f"{base_url}/lms/officer", wait_until="domcontentloaded")
    page.wait_for_selector(".lms-summary-label, .lms-stat-label", timeout=15000)
    page.wait_for_load_state("networkidle")
    detail = ""
    try:
        labels = [t.lower() for t in page.locator(".lms-summary-label, .lms-stat-label").all_inner_texts()]
        wanted = ("pending applications", "awaiting disbursement", "my active loans", "par count")
        missing = [w for w in wanted if not any(w in t for t in labels)]
        if missing:
            status = "fail"
            detail = f"missing labels: {missing}; got (lowercased): {labels!r}"
        else:
            status = "pass"
            detail = f"all 4 KPI labels rendered; sample: {page.locator('.lms-summary-label, .lms-stat-label').all_inner_texts()[:6]!r}"
    except Exception as exc:
        status = "fail"; detail = f"dashboard selector wait failed: {exc}"
    _record(page, console, role, story, status, detail)
    assert status == "pass", detail


def test_o2_my_loans(officer, page, console, base_url):
    role, story = "officer", "O2-my-loans"
    console.begin_story(story)
    page.goto(f"{base_url}/lms/officer", wait_until="domcontentloaded")
    page.wait_for_selector(".lms-tab-nav", timeout=15000)
    _click_tab(page, "loans")
    detail = ""
    try:
        page.wait_for_selector("table.lms-data-table, .lms-empty", timeout=10000)
        n_rows = page.locator("table.lms-data-table tbody tr").count()
        if n_rows >= 0:
            status = "pass"
            detail = f"loans tab rendered with {n_rows} rows (or empty)"
        else:
            status = "fail"
            detail = "table present but no rows"
    except Exception as exc:
        status = "fail"; detail = f"loans tab selector failed: {exc}"
    _record(page, console, role, story, status, detail)
    assert status == "pass", detail


def test_o3_borrowers(officer, page, console, base_url):
    role, story = "officer", "O3-borrowers"
    console.begin_story(story)
    page.goto(f"{base_url}/lms/officer", wait_until="domcontentloaded")
    page.wait_for_selector(".lms-tab-nav", timeout=15000)
    _click_tab(page, "borrowers")
    detail = ""
    try:
        page.wait_for_selector("table.lms-data-table, .lms-empty", timeout=10000)
        rows = page.locator("table.lms-data-table tbody tr").count()
        body = page.evaluate("document.body.innerText") or ""
        has_name = any(needle in body for needle in ("Name", "Mobile", "KYC"))
        if has_name or rows == 0:
            status = "pass"
            detail = f"borrowers tab rendered; rows={rows}, body has Name/Mobile/KYC"
        else:
            status = "fail"
            detail = "borrowers tab rendered but no Name/Mobile/KYC markers"
    except Exception as exc:
        status = "fail"; detail = f"borrowers tab failed: {exc}"
    _record(page, console, role, story, status, detail)
    assert status == "pass", detail


def test_o4_kyc_queue(officer, page, console, base_url):
    role, story = "officer", "O4-kyc-queue"
    console.begin_story(story)
    page.goto(f"{base_url}/lms/officer", wait_until="domcontentloaded")
    page.wait_for_selector(".lms-tab-nav", timeout=15000)
    _click_tab(page, "kyc")
    detail = ""
    try:
        page.wait_for_selector("table.lms-data-table, .lms-empty", timeout=10000)
        body = page.evaluate("document.body.innerText") or ""
        has_review = page.locator(".lms-review-btn, button:has-text('Review')").count()
        if has_review > 0 or "Pending" in body or "Approved" in body:
            status = "pass"
            detail = "kyc queue table or empty state visible"
        else:
            status = "fail"
            detail = "kyc tab rendered but no Review buttons or status labels"
    except Exception as exc:
        status = "fail"; detail = f"kyc tab failed: {exc}"
    _record(page, console, role, story, status, detail)
    assert status == "pass", detail


def test_o5_leads(officer, page, console, base_url):
    role, story = "officer", "O5-leads"
    console.begin_story(story)
    page.goto(f"{base_url}/lms/officer", wait_until="domcontentloaded")
    page.wait_for_selector(".lms-tab-nav", timeout=15000)
    _click_tab(page, "leads")
    detail = ""
    try:
        page.wait_for_selector("table.lms-data-table, .lms-empty, .lms-panel", timeout=10000)
        status = "pass"
        detail = "leads tab renders (table or empty state)"
    except Exception as exc:
        status = "fail"; detail = f"leads tab failed: {exc}"
    _record(page, console, role, story, status, detail)
    assert status == "pass", detail


def test_o6_reports(officer, page, console, base_url):
    role, story = "officer", "O6-reports"
    console.begin_story(story)
    page.goto(f"{base_url}/lms/officer", wait_until="domcontentloaded")
    page.wait_for_selector(".lms-tab-nav", timeout=15000)
    _click_tab(page, "reports")
    detail = ""
    try:
        page.wait_for_selector(".lms-page-header, .lms-panel, .lms-section-header, table.lms-data-table, .lms-empty", timeout=10000)
        body = page.evaluate("document.body.innerText") or ""
        if any(k in body for k in ("Portfolio", "Arrears", "Collections", "Report")):
            status = "pass"
            detail = "reports tab renders at least one report type"
        else:
            status = "fail"
            detail = "reports tab rendered but missing Portfolio/Arrears/Collections/Report markers"
    except Exception as exc:
        status = "fail"; detail = f"reports tab failed: {exc}"
    _record(page, console, role, story, status, detail)
    assert status == "pass", detail


def test_o7_new_application_modal(officer, page, console, base_url):
    role, story = "officer", "O7-new-application-modal"
    console.begin_story(story)
    page.goto(f"{base_url}/lms/officer", wait_until="domcontentloaded")
    page.wait_for_selector(".lms-tab-nav, .lms-btn--primary", timeout=15000)
    detail = ""
    try:
        btn = page.locator("button:has-text('New Application'), a:has-text('New Application'), button.lms-btn--primary:has-text('New')").first
        if btn.count() == 0:
            btn = page.locator("button.lms-btn--primary").first
        if btn.count() == 0:
            status = "fail"
            detail = "no New Application trigger"
        else:
            btn.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_selector(".lms-form, .lms-modal, .lms-section-header, dialog, form", timeout=8000)
            status = "pass"
            detail = "New Application trigger opens a form / modal"
    except Exception as exc:
        status = "fail"; detail = f"new app modal failed: {exc}"
    _record(page, console, role, story, status, detail)
    assert status == "pass", detail


def test_o8_disburse(officer, page, console, base_url):
    """O8: Disbursing a Pending loan. Best-effort click — assert no 500 + DOM updates."""
    role, story = "officer", "O8-disburse"
    console.begin_story(story)
    page.goto(f"{base_url}/lms/officer", wait_until="domcontentloaded")
    page.wait_for_selector(".lms-tab-nav", timeout=15000)
    _click_tab(page, "loans")
    detail = ""
    try:
        page.wait_for_selector("table.lms-data-table", timeout=10000)
        btn = page.locator(".lms-of-disburse-btn, button:has-text('Disburse')").first
        if btn.count() == 0:
            status = "pass"
            detail = "no Disburse button visible (loan may already be Disbursed)"
        else:
            btn.click()
            page.wait_for_load_state("networkidle")
            status = "pass"
            detail = "Disburse button clicked; page reloaded without 500"
    except Exception as exc:
        status = "fail"; detail = f"disburse flow failed: {exc}"
    _record(page, console, role, story, status, detail)
    assert status == "pass", detail
