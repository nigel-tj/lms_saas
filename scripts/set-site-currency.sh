#!/usr/bin/env bash
# =============================================================================
#  One-time operator script: set site currency + country
# =============================================================================
#
#  This is NOT a deploy script. It's a one-time configuration step the
#  operator runs when they want to change the site's currency (e.g. from
#  ZAR to USD). Run it once, then never again — the frappe-cloud-update.sh
#  script will keep site_config.json in sync with the company currency on
#  every deploy.
#
#  Usage:
#    bash apps/lms_saas/scripts/set-site-currency.sh --currency USD --country Zimbabwe
#    bash apps/lms_saas/scripts/set-site-currency.sh --currency KES --country Kenya
#    bash apps/lms_saas/scripts/set-site-currency.sh --dry-run --currency NGN --country Nigeria
#
#  Auto-detects the site (same logic as frappe-cloud-update.sh).
#  Idempotent — safe to re-run.

set -euo pipefail

CURRENCY=""
COUNTRY=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --currency)  CURRENCY="$2"; shift 2 ;;
        --country)   COUNTRY="$2"; shift 2 ;;
        --dry-run)   DRY_RUN=1; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$CURRENCY" ]]; then
    echo "ERROR: --currency is required (e.g. USD, KES, NGN, ZAR)"
    exit 1
fi
if [[ -z "$COUNTRY" ]]; then
    echo "ERROR: --country is required (e.g. Zimbabwe, Kenya, Nigeria)"
    exit 1
fi

# Auto-detect site
SITE="${FC_SITE:-}"
if [[ -z "$SITE" ]]; then
    SITES=$(ls sites/ 2>/dev/null | grep -v -E '\.json$|\.txt$|assets|apps' | head -5)
    SITE_COUNT=$(echo "$SITES" | wc -l)
    if [[ "$SITE_COUNT" -eq 1 ]]; then
        SITE="$SITES"
    elif [[ "$SITE_COUNT" -gt 1 ]]; then
        SITE=$(echo "$SITES" | grep -i '^lms' | head -1)
        if [[ -z "$SITE" ]]; then
            echo "ERROR: Multiple sites found. Set FC_SITE=<site> and re-run."
            echo "Available: $SITES"
            exit 1
        fi
    else
        echo "ERROR: No sites found."
        exit 1
    fi
fi

echo "=== Set site currency ==="
echo "  Site:     $SITE"
echo "  Currency: $CURRENCY"
echo "  Country:  $COUNTRY"
echo "  Dry run:  $DRY_RUN"
echo ""

APPLY=""
if [[ "$DRY_RUN" -eq 0 ]]; then
    APPLY='"apply": 1,'
fi

bench --site "$SITE" execute lms_saas.setup.set_company_currency_country.run \
    --kwargs "{${APPLY}\"currency\": \"${CURRENCY}\", \"country\": \"${COUNTRY}\"}"

if [[ "$DRY_RUN" -eq 0 ]]; then
    echo ""
    echo "  Syncing site_config.json..."
    bench --site "$SITE" execute lms_saas.setup.set_company_currency_country._sync_site_config_currency
    bench --site "$SITE" clear-cache
    echo ""
    echo "  Done. The portal will now show ${CURRENCY} instead of the previous currency."
else
    echo ""
    echo "  Dry run — nothing was written. Re-run without --dry-run to apply."
fi