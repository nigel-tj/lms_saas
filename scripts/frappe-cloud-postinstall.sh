#!/usr/bin/env bash
# Post-install + verify for LMS SaaS on Frappe Cloud (run over SSH on the bench).
#
# Usage (on Frappe Cloud bench after SSH):
#   export FC_SITE=app.kesari.africa
#   bash apps/lms_saas/scripts/frappe-cloud-postinstall.sh
#
# Or one-shot from your laptop (requires FC SSH key from dashboard):
#   ssh -i ~/.ssh/frappe-cloud.pem -p 2222 bench-42841-000002-f20nm@n1-mumbai-frappe.frappe.cloud \
#     'bash -s' < scripts/frappe-cloud-postinstall.sh

set -euo pipefail

FC_SITE="${FC_SITE:-lms-saas.frappe.cloud}"
COMPLIANCE_EMAIL="${LMS_COMPLIANCE_EMAIL:-ops@kesari.africa}"
RISK_DISCLOSURE="${LMS_RISK_DISCLOSURE:-Loans involve credit risk. Terms and fees apply. Kesari sandbox.}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { printf '%s\n' "$*"; }
warn()  { printf "${YELLOW}%s${NC}\n" "$*" >&2; }
err()   { printf "${RED}error:${NC} %s\n" "$*" >&2; }
ok()    { printf "${GREEN}%s${NC}\n" "$*"; }

if ! command -v bench >/dev/null 2>&1; then
	if [[ -d "$HOME/frappe-bench" ]]; then
		cd "$HOME/frappe-bench"
	elif [[ -d "/home/frappe/frappe-bench" ]]; then
		cd "/home/frappe/frappe-bench"
	else
		err "bench not found; run from frappe-bench directory"
		exit 1
	fi
fi

if [[ ! -d "sites/$FC_SITE" ]]; then
	err "Site directory sites/$FC_SITE not found on this bench."
	info "Available sites:"
	ls -1 sites/ 2>/dev/null | grep -v '^assets$' || true
	exit 1
fi

info "=== Frappe Cloud post-install for $FC_SITE ==="

info "--- Installed apps ---"
bench --site "$FC_SITE" list-apps

missing_apps=0
installed_apps="$(bench --site "$FC_SITE" list-apps 2>/dev/null | awk 'NF {print $1}')"
for app in frappe erpnext lending hrms lms_saas; do
	if ! printf '%s\n' "$installed_apps" | grep -qx "$app"; then
		warn "Missing app: $app"
		missing_apps=1
	fi
done
if [[ "$missing_apps" -eq 1 ]]; then
	err "Install missing apps via Frappe Cloud dashboard, then re-run this script."
	exit 1
fi

info "--- migrate (runs after_migrate → after_install hook) ---"
bench --site "$FC_SITE" migrate

info "--- build lms_saas assets ---"
bench build --app lms_saas

if [[ "${LMS_SKIP_SITE_CONFIG:-0}" != "1" ]]; then
info "--- site config (Kesari sandbox defaults) ---"
bench --site "$FC_SITE" set-config -p developer_mode 0
bench --site "$FC_SITE" set-config -p lms_enforce_four_eyes True
bench --site "$FC_SITE" set-config -p lms_require_consent True
bench --site "$FC_SITE" set-config -p lms_max_loan_amount 50000
bench --site "$FC_SITE" set-config -p lms_max_active_customers 500
bench --site "$FC_SITE" set-config lms_sandbox_end_date 2027-12-31
bench --site "$FC_SITE" set-config -p lms_payments_enabled False
bench --site "$FC_SITE" set-config -p lms_aml_enabled False
bench --site "$FC_SITE" set-config -p lms_aml_require_clear True
bench --site "$FC_SITE" set-config -p lms_credit_bureau_enabled False
bench --site "$FC_SITE" set-config -p lms_collections_escalation_enabled False
bench --site "$FC_SITE" set-config -p lms_digest_enabled False
bench --site "$FC_SITE" set-config -p lms_weekly_kpi_enabled True
bench --site "$FC_SITE" set-config lms_compliance_report_recipients "$COMPLIANCE_EMAIL"
bench --site "$FC_SITE" set-config -p lms_risk_disclosure "\"$RISK_DISCLOSURE\""
fi

info "--- clear-cache + scheduler ---"
bench --site "$FC_SITE" clear-cache
bench --site "$FC_SITE" enable-scheduler

info "--- verify_spec ---"
verify_out="$(bench --site "$FC_SITE" execute lms_saas.setup.verify_spec.run_all_checks 2>&1)" || true
printf '%s\n' "$verify_out"

if printf '%s' "$verify_out" | grep -q '"ok": false'; then
	warn "verify_spec reported failures — re-run migrate and build, then try again."
else
	ok "verify_spec passed"
fi

if bench --site "$FC_SITE" execute lms_saas.setup.verify_styling.run_all >/dev/null 2>&1; then
	info "--- verify_styling ---"
	bench --site "$FC_SITE" execute lms_saas.setup.verify_styling.run_all
fi

info ""
info "=== DNS checklist (if https://$FC_SITE/login does not load) ==="
info "1. Frappe Cloud dashboard → Site → Domains → add custom domain"
info "2. At your DNS host, add the A/CNAME records shown in FC"
info "3. Enable SSL in Frappe Cloud → wait for propagation"
info "4. Until DNS is live, use the *.frappe.cloud URL from the FC site page"

ok "Post-install finished for $FC_SITE"
