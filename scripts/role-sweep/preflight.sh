#!/usr/bin/env bash
# scripts/role-sweep/preflight.sh — sweep environment check
#
# Exits 2 if any precondition fails. Sweep run.sh refuses to proceed without
# a clean preflight.

set -uo pipefail

fail=0
log() { echo "  [preflight] $*"; }
err() { echo "  [preflight] FAIL: $*" >&2; fail=1; }

ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PY="${1:-$ROOT/.sweep-venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  err "no python at $PY"
fi

# 1. FC_SITE
if [[ -z "${FC_SITE:-}" ]]; then
  err "FC_SITE unset — set it (e.g. export FC_SITE=https://lms-saas.frappe.cloud or http://lms.localhost:8000)"
else
  log "FC_SITE=$FC_SITE"
  if curl -sfm 10 -o /dev/null "${FC_SITE}/api/method/frappe.ping"; then
    log "Frappe ping: OK"
  else
    err "${FC_SITE}/api/method/frappe.ping did not return pong"
  fi
  if curl -sfm 10 -o /dev/null -L "${FC_SITE}/login"; then
    log "/login: reachable"
  else
    err "${FC_SITE}/login not 200 — bench up?"
  fi
fi

# 2. Playwright Python
if "$PY" -c "import playwright" 2>/dev/null; then
  log "playwright python: OK"
else
  err "playwright python missing — pip install playwright"
fi

# 3. pytest
if "$PY" -c "import pytest" 2>/dev/null; then
  log "pytest: OK"
else
  err "pytest missing — pip install pytest"
fi

# 4. Chromium browser installed
if "$PY" - <<'PY' 2>/dev/null
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    b.close()
PY
then
  log "chromium: ready"
else
  err "chromium not installed — .sweep-venv/bin/playwright install chromium"
fi

# 5. Twilio smoke opt-in check
if [[ -z "${SWEEP_TWILIO_TO:-}" ]]; then
  log "SWEEP_TWILIO_TO unset — twilio smoke will be skipped (not failed)"
else
  log "SWEEP_TWILIO_TO=$SWEEP_TWILIO_TO — twilio smoke will run"
fi

if [[ "$fail" -ne 0 ]]; then
  echo ""
  echo "preflight failed; sweep not started" >&2
  exit 2
fi
echo ""
echo "[preflight] all green"
