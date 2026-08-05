"""pytest fixtures shared across role-sweep tests.

We delegate the browser + page lifecycle to pytest-playwright (which
provides the `browser` and `context` and `page` fixtures). This file
adds:

- `base_url` session-scoped: read from FC_SITE
- `console` function-scoped: a ConsoleErrorCollector attached to the
  fresh page
- `sweep_run_id`: identifies this run for cross-test evidence aggregation
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

from utils.console import ConsoleErrorCollector


# pytest-playwright provides a `page` fixture via `context` + `browser_name`
# we just bump the default timeout from env so SWEEP_TIMEOUT controls waits.
@pytest.fixture(scope="function")
def page(context, browser_name, base_url):
    p = context.new_page()
    p.set_default_timeout(int(os.environ.get("SWEEP_TIMEOUT", "20")) * 1000)
    yield p
    p.close()


@pytest.fixture(scope="session")
def base_url() -> str:
    url = os.environ.get("FC_SITE", "").rstrip("/")
    if not url:
        pytest.exit("FC_SITE is not set; preflight should have caught this", 2)
    return url


@pytest.fixture(scope="function")
def console(page) -> ConsoleErrorCollector:
    c = ConsoleErrorCollector()
    c.attach(page)
    return c


@pytest.fixture(scope="session", autouse=True)
def sweep_run_id() -> str:
    rid = os.environ.get("SWEEP_RUN_ID") or uuid.uuid4().hex[:8]
    os.environ["SWEEP_RUN_ID"] = rid
    return rid


# -----------------------------------------------------------------------------
# Evidence aggregation on session finish
# -----------------------------------------------------------------------------
def pytest_sessionfinish(session, exitstatus):
    """Aggregate per-role JSONL results into role-*.md + summary.md."""
    try:
        from utils.evidence import artifacts_root, write_role_markdown, write_summary
        from utils.users import USERS, PRIMARY, READ_ONLY

        path = artifacts_root() / "sweep-results.jsonl"
        if not path.exists():
            return

        by_role: dict[str, list[dict]] = {}
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            by_role.setdefault(r["role"], []).append(
                {"story": r["story"], "status": r["status"], "detail": r.get("detail", "")}
            )

        role_to_persona = {}
        for k in PRIMARY + READ_ONLY:
            if k in USERS:
                role_to_persona[k] = USERS[k]["persona"]

        for role, results in by_role.items():
            persona = role_to_persona.get(role, role.title())
            write_role_markdown(role, persona, results)
        write_summary(by_role)
    except Exception as exc:
        print(f"[sweep] failed to aggregate evidence: {exc}")
