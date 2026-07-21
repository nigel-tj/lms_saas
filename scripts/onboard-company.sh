#!/usr/bin/env bash
# Onboard one company on a live/staging site using the LMS setup orchestrator.
#
# Usage examples:
#   FC_SITE=app.kesari.africa COMPANY=Kesari DRY_RUN=1 bash scripts/onboard-company.sh
#   FC_SITE=app.kesari.africa COMPANY=Kesari APPLY=1 COMPANY_NAME=Kesari DOMAIN=kesari.africa bash scripts/onboard-company.sh

set -euo pipefail

FC_SITE="${FC_SITE:-lms-saas.frappe.cloud}"
COMPANY="${COMPANY:-}"
COMPANY_NAME="${COMPANY_NAME:-}"
DOMAIN="${DOMAIN:-}"

DRY_RUN="${DRY_RUN:-1}"
APPLY="${APPLY:-0}"

RUN_VERIFY="${RUN_VERIFY:-1}"
FULL_VERIFY="${FULL_VERIFY:-0}"

SEND_TEST_EMAIL="${SEND_TEST_EMAIL:-0}"
TEST_EMAIL_RECIPIENT="${TEST_EMAIL_RECIPIENT:-}"

INCLUDE_DEMO="${INCLUDE_DEMO:-0}"
DEMO_COUNT="${DEMO_COUNT:-0}"

SMTP_SERVER="${SMTP_SERVER:-}"
SMTP_PORT="${SMTP_PORT:-}"
SMTP_EMAIL_ID="${SMTP_EMAIL_ID:-}"
SMTP_PASSWORD="${SMTP_PASSWORD:-}"
SMTP_USE_SSL="${SMTP_USE_SSL:-}"

if [[ -d "$HOME/frappe-bench" ]]; then
  cd "$HOME/frappe-bench"
elif [[ -d "/home/frappe/frappe-bench" ]]; then
  cd "/home/frappe/frappe-bench"
fi

BENCH_BIN=""
if [[ -x "./env/bin/bench" ]]; then
  BENCH_BIN="./env/bin/bench"
elif command -v bench >/dev/null 2>&1; then
  BENCH_BIN="bench"
fi

if [[ -z "$BENCH_BIN" ]]; then
  echo "error: bench not found; run from frappe-bench directory" >&2
  exit 1
fi

if [[ ! -d "sites/$FC_SITE" ]]; then
  echo "error: sites/$FC_SITE not found" >&2
  ls -1 sites/ 2>/dev/null | grep -v '^assets$' || true
  exit 1
fi

if [[ -z "$COMPANY" ]]; then
  echo "error: COMPANY is required" >&2
  echo "example: FC_SITE=app.kesari.africa COMPANY=Kesari DRY_RUN=1 bash scripts/onboard-company.sh" >&2
  exit 1
fi

if [[ "$APPLY" == "1" ]]; then
  DRY_RUN=0
fi

KWARGS_JSON="$(python3 - <<'PY'
import json
import os

def maybe(v):
    return None if v == "" else v

payload = {
    "company": os.getenv("COMPANY"),
    "dry_run": int(os.getenv("DRY_RUN", "1") or "1"),
    "apply": int(os.getenv("APPLY", "0") or "0"),
    "company_name": maybe(os.getenv("COMPANY_NAME", "")),
    "domain": maybe(os.getenv("DOMAIN", "")),
    "run_verify": int(os.getenv("RUN_VERIFY", "1") or "1"),
    "full_verify": int(os.getenv("FULL_VERIFY", "0") or "0"),
    "send_test_email": int(os.getenv("SEND_TEST_EMAIL", "0") or "0"),
    "test_email_recipient": maybe(os.getenv("TEST_EMAIL_RECIPIENT", "")),
    "include_demo": int(os.getenv("INCLUDE_DEMO", "0") or "0"),
    "demo_count": int(os.getenv("DEMO_COUNT", "0") or "0"),
    "smtp_server": maybe(os.getenv("SMTP_SERVER", "")),
    "smtp_port": int(os.getenv("SMTP_PORT", "0") or "0") or None,
    "smtp_email_id": maybe(os.getenv("SMTP_EMAIL_ID", "")),
    "smtp_password": maybe(os.getenv("SMTP_PASSWORD", "")),
    "smtp_use_ssl": int(os.getenv("SMTP_USE_SSL", "0") or "0") if os.getenv("SMTP_USE_SSL") else None,
}

payload = {k: v for k, v in payload.items() if v is not None}

print(json.dumps(payload))
PY
)"

echo "=== LMS company onboarding ==="
echo "site=$FC_SITE company=$COMPANY mode=$([[ "$DRY_RUN" == "1" ]] && echo dry-run || echo apply)"

"$BENCH_BIN" --site "$FC_SITE" execute lms_saas.setup.onboard_company.run --kwargs "$KWARGS_JSON"
