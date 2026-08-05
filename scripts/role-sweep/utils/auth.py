"""Login + logout helpers for the sweep.

Frappe's `/login` page renders inputs as `<input id="login_email">` and
`<input id="login_password">` with no `name=` attribute. Submit is a
plain `<button>` inside the form. After login, the persona-based `on_login`
hook redirects to the appropriate landing — we don't manually navigate.
"""
from __future__ import annotations

from playwright.sync_api import Page


LOGIN_PATH = "/login"


def login(page: Page, base_url: str, email: str, password: str) -> None:
    page.goto(f"{base_url}{LOGIN_PATH}", wait_until="domcontentloaded", timeout=20000)
    page.fill("#login_email", email)
    page.fill("#login_password", password)
    # Submit — the visible "Sign In" button is inside form.form-signin
    page.click("form.form-signin button:has-text('Sign in'), form.form-signin button[type='submit']")
    page.wait_for_url(lambda url: LOGIN_PATH not in url, timeout=20000)


def logout(page: Page, base_url: str) -> None:
    try:
        page.goto(f"{base_url}/api/method/logout", wait_until="domcontentloaded", timeout=10000)
    except Exception:
        pass
    try:
        page.context.clear_cookies()
    except Exception:
        pass
