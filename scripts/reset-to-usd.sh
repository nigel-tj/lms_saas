#!/usr/bin/env bash
# R44: Reset live site to USD currency (not ZAR).
#
# Run on the Frappe Cloud bench after deploying:
#   bash apps/lms_saas/scripts/reset-to-usd.sh
#
# This script:
#   1. Ensures USD currency exists and is enabled
#   2. Sets all companies to USD
#   3. Sets Global Defaults to USD
#   4. Writes lms_currency=USD to site_config.json
#   5. Runs live_repair + provision_test_users
#   6. Clears cache
#
# Idempotent — safe to re-run.

set -euo pipefail

SITE="${FC_SITE:-}"
if [[ -z "$SITE" ]]; then
    # Auto-detect: pick the only site, or the one starting with 'lms'
    SITES=$(ls sites/ | grep -v -E '\.json$|\.txt$|assets|apps' | head -5)
    SITE_COUNT=$(echo "$SITES" | wc -l)
    if [[ "$SITE_COUNT" -eq 1 ]]; then
        SITE="$SITES"
    elif [[ "$SITE_COUNT" -gt 1 ]]; then
        SITE=$(echo "$SITES" | grep -i '^lms' | head -1)
        if [[ -z "$SITE" ]]; then
            echo "ERROR: Multiple sites found. Set FC_SITE=<site> and re-run."
            echo "Available sites:"
            echo "$SITES"
            exit 1
        fi
    else
        echo "ERROR: No sites found."
        exit 1
    fi
fi

echo "=== Reset to USD — site: $SITE ==="

bench --site "$SITE" execute lms_saas.setup.set_company_currency_country.run \
    --kwargs '{"currency": "USD", "country": "Zimbabwe"}' || true

bench --site "$SITE" execute lms_saas.setup.live_repair.repair_live_site_state || true

bench --site "$SITE" execute lms_saas.setup.live_repair.provision_test_users || true

bench --site "$SITE" clear-cache
bench --site "$SITE" clear-website-cache

echo "=== Done. Verify: ==="
echo "  Companies: bench --site $SITE execute frappe.client.get_value --kwargs '{\"doctype\":\"Company\",\"filters\":{\"name\":\"LMS Demo Co\"},\"fieldname\":\"default_currency\"}'"
echo "  Portal: visit /lms/officer — amounts should show \$ not ZAR"