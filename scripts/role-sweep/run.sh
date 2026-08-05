#!/usr/bin/env bash
# apps/lms_saas/scripts/role-sweep/run.sh — entrypoint for the LMS role-by-role sweep
#
# Designed to run from either the bench (`~/frappe-bench`) or any clone of the
# repo. Self-contained: auto-creates its own Python venv alongside the script
# the first time it's invoked, so no operator setup is required.
#
# Usage:
#   bash apps/lms_saas/scripts/role-sweep/run.sh                 # full sweep
#   bash apps/lms_saas/scripts/role-sweep/run.sh --role manager  # one role only
#   bash apps/lms_saas/scripts/role-sweep/run.sh --dry-run       # show plan, don't run
#
# Env (required):
#   FC_SITE             e.g. https://lms-saas.frappe.cloud (or http://lms.localhost:8000)
# Env (optional):
#   SWEEP_TWILIO_TO     E.164 number for Twilio smoke (skipped if unset)
#   SWEEP_HEADLESS      default true
#   SWEEP_TIMEOUT       default 20 (seconds per step)
#   SWEEP_ARTIFACTS_DIR default ./_artifacts (relative to bench CWD)

set -uo pipefail

# ── Locations ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Sweep is self-contained: keep venv next to the script so we don't depend on
# the monorepo layout the bench doesn't carry.
VENV="$SCRIPT_DIR/.sweep-venv"
PY="$VENV/bin/python"

# ── Ensure Python + venv ──
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ ! -x "$PY" ]]; then
  echo "[run.sh] first run — creating venv at $VENV"
  if ! "$PYTHON_BIN" -m venv "$VENV"; then
    echo "[run.sh] venv creation failed; ensure python3-venv is installed (apt install python3-venv on Debian/Ubuntu)" >&2
    exit 2
  fi
  "$VENV/bin/pip" install --quiet --upgrade pip || true
  "$VENV/bin/pip" install --quiet playwright pytest-playwright
  "$VENV/bin/playwright" install --with-deps chromium 2>&1 | tail -8
fi

# ── Args ──
DRY_RUN=false
ROLE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --role)
      ROLE="${2:-}"; shift 2 ;;
    --role=*) ROLE="${1#*=}"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ── Preflight ──
bash "$SCRIPT_DIR/preflight.sh" "$PY"

# ── Dry run ──
if [[ "$DRY_RUN" == "true" ]]; then
  echo ""
  echo "[dry-run] would execute:"
  if [[ -n "$ROLE" ]]; then
    echo "  $PY -m pytest -q tests/ -k $ROLE"
  else
    echo "  $PY -m pytest -q tests/"
  fi
  exit 0
fi

# ── Run ──
# The tests import utils.evidence etc. via `from utils import ...`. Add
# $SCRIPT_DIR (where utils/ lives) to PYTHONPATH, then cd to $SCRIPT_DIR so
# cwd === package root for any relative paths inside the runbook.
cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"
if [[ -n "$ROLE" ]]; then
  exec "$PY" -m pytest -q "$SCRIPT_DIR/tests/" -k "$ROLE"
else
  exec "$PY" -m pytest -q "$SCRIPT_DIR/tests/"
fi
