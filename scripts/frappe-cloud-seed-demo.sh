#!/usr/bin/env bash
# Demo portfolio seed for Frappe Cloud (run over SSH after migrate).
#
# Usage:
#   export FC_SITE=lms-saas.frappe.cloud
#   bash apps/lms_saas/scripts/frappe-cloud-seed-demo.sh
#
# From laptop (requires FC SSH private key from dashboard → Bench → SSH):
#   ssh -i ~/.ssh/frappe-cloud.pem -p 2222 bench-42841-000002-f20nm@n1-mumbai-frappe.frappe.cloud \
#     'bash -s' < apps/lms_saas/scripts/frappe-cloud-seed-demo.sh

set -euo pipefail

FC_SITE="${FC_SITE:-lms-saas.frappe.cloud}"
SEED_COUNT="${LMS_SEED_COUNT:-16}"

if ! command -v bench >/dev/null 2>&1; then
	cd "${HOME}/frappe-bench" 2>/dev/null || cd /home/frappe/frappe-bench
fi

if [[ ! -d "sites/$FC_SITE" ]]; then
	echo "error: sites/$FC_SITE not found" >&2
	ls -1 sites/ 2>/dev/null | grep -v '^assets$' || true
	exit 1
fi

echo "=== Demo seed for $FC_SITE (count=$SEED_COUNT) ==="

# Temporarily relax gates; seed_demo sets consent_given on compliance records.
bench --site "$FC_SITE" set-config -p lms_enforce_four_eyes 0
bench --site "$FC_SITE" set-config -p lms_require_consent 0

seed_out="$(bench --site "$FC_SITE" execute lms_saas.setup.seed_demo.run_bulk --kwargs "{\"count\": $SEED_COUNT}" 2>&1)" || {
	echo "$seed_out"
	echo "Bulk seed failed — trying single run() ..."
	bench --site "$FC_SITE" execute lms_saas.setup.seed_demo.run
}

printf '%s\n' "$seed_out"

bench --site "$FC_SITE" set-config -p lms_enforce_four_eyes 1
bench --site "$FC_SITE" set-config -p lms_require_consent 1
bench --site "$FC_SITE" clear-cache

echo "--- verify_spec ---"
bench --site "$FC_SITE" execute lms_saas.setup.verify_spec.run_all_checks

loan_count="$(bench --site "$FC_SITE" console <<'PY'
import frappe
print(frappe.db.count("Loan", {"docstatus": 1}))
PY
)"
echo "Submitted loans on site: $loan_count"
echo "Demo seed finished."
