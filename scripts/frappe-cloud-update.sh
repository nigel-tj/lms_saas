#!/usr/bin/env bash
# Apply lms_saas updates on Frappe Cloud after Bench Deploy + Site Update.
#
# Usage (SSH on bench):
#   export FC_SITE=lms-saas.frappe.cloud
#   bash apps/lms_saas/scripts/frappe-cloud-update.sh

set -euo pipefail

FC_SITE="${FC_SITE:-lms-saas.frappe.cloud}"

if ! command -v bench >/dev/null 2>&1; then
	cd "${HOME}/frappe-bench" 2>/dev/null || cd /home/frappe/frappe-bench
fi

if [[ ! -d "sites/$FC_SITE" ]]; then
	echo "error: sites/$FC_SITE not found" >&2
	ls -1 sites/ 2>/dev/null | grep -v '^assets$' || true
	exit 1
fi

echo "=== Frappe Cloud update for $FC_SITE ==="
bench --site "$FC_SITE" migrate
bench build --app lms_saas
bench --site "$FC_SITE" clear-cache
bench --site "$FC_SITE" enable-scheduler
bench --site "$FC_SITE" execute lms_saas.setup.verify_spec.run_all_checks
echo "Update complete for $FC_SITE"
