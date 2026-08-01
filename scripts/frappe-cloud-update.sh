#!/usr/bin/env bash
# =============================================================================
#  Frappe Cloud post-update script for lms_saas
# =============================================================================
#
#  WHAT THIS DOES
#  --------------
#  Runs the lms_saas-specific post-deploy reconcile steps that the Frappe
#  Cloud dashboard's generic `Benches → Deploy` + `Sites → Update` flow does
#  NOT do for us. Concretely:
#
#    1. bench migrate         — apply pending schema migrations (patches.txt)
#    2. bench build           — re-bundle lms_saas JS so the browser stops
#                                loading stale `?v=...` cache-bust query
#                                strings on lms_portal.js, lms_desk.js, etc.
#    3. clear-cache           — drop document + Redis + browser cache
#    4. enable-scheduler      — ensure background jobs (SMS queue, audit
#                                pipeline, KYC re-checks) are running
#    5. _reconcile_loan_dashboard        — re-link LMS Number Cards /
#                                          Charts to the Loan Dashboard
#                                          workspace (idempotent)
#    6. _set_portal_role_home_pages      — re-point LMS Portal Staff /
#                                          Loan Officer / Collector /
#                                          Branch Manager to their landing
#                                          workspace
#    7. _set_admin_home_page             — re-point Admin / System Manager
#                                          to the admin landing workspace
#    8. _setup_navbar_branding           — re-apply the operator's brand
#                                          (Website Settings.app_name +
#                                          System Settings.app_name +
#                                          Navbar Settings.app_logo) so
#                                          the desk chrome reflects the
#                                          current lms_brand_portal_title
#                                          in site_config. Idempotent.
#    9. verify_spec.run_all_checks       — the operator's verification
#                                          suite. Catches workspace drift,
#                                          role-home desync, audit pipeline
#                                          gaps, and brand-chain leaks.
#
#  WHY EACH LmsSaAs STEP IS NEEDED
#  -----------------------------
#  Steps 1–4 are the standard Frappe bench post-deploy — but they run for
#  EVERY app, so a misbehaving site config can't tell which app needs what.
#  NB: the `bench build` step (2) is auto-skipped on Frappe Cloud because
#  the `Deploy` hook already built the bundle, and re-running it races the
#  CDN cache invalidation — the documented Frappe Cloud symptom is a
#  whole-site 404 storm on every /assets/ file until the next Deploy.
#  Steps 5–7 are lms_saas-only self-heal: the install/after_install hook
#  writes a lot of workspace, home-page, and dashboard-card state at
#  install time. If a deploy lands while the desk is open, those refs can
#  be stale by the time the next user logs in. Each `_reconcile_*` /
#  `_set_*` function is idempotent — safe to re-run on every deploy, even
#  when nothing changed.
#
#  Step 8 is the smoke detector: it diff-asserts the live site's shape
#  against the lms_saas expected shape. A red ✗ line means a deploy broke
#  something the framework's standard migrate would NOT catch.
#
#  USAGE
#  -----
#  On the bench host, after `Benches → Deploy` and `Sites → Update`:
#
#    # Auto-detect the only site (the common case — bench has one site):
#    bash apps/lms_saas/scripts/frappe-cloud-update.sh
#
#    # Explicit site:
#    FC_SITE=lms-other-client.frappe.cloud \
#      bash apps/lms_saas/scripts/frappe-cloud-update.sh
#
#  FLAGS
#  -----
#    --dry-run     print what WOULD run, do not execute any bench command
#    --check-only  skip bench migrate / build / cache; just run the
#                  lms_saas reconcile + verify_spec steps (cheap, ~10s)
#    --skip-build  skip `bench build --app lms_saas` (use when the bench
#                  already auto-rebuilt via deploy hooks). This is the
#                  DEFAULT on Frappe Cloud — the Deploy hook has already
#                  built the bundle and re-running it from this script
#                  races the CDN cache invalidation and commonly leaves
#                  the whole site returning 404s on every asset.
#    --build       force the build on Frappe Cloud despite the auto-skip.
#                  Off the default everywhere; only set this if you know
#                  the CDN has invalidated and you cannot re-deploy.
#    --help        show usage and exit
#
#  ENVIRONMENT
#  -----------
#    FC_SITE              site folder name (overrides auto-detect)
#    LMS_SKIP_SITE_CONFIG 1 to skip re-applying site_config keys (set
#                          when the operator doesn't want FC_SITE host_name
#                          overrides during a rebrand)
#    LMS_SKIP_REBRAND     1 to skip the navbar-branding re-apply step (use
#                          when you intentionally want the desk to keep a
#                          different brand than the portal for a window)
#    FRAPPE_CLOUD=1       Force the FC auto-detect (set automatically by
#                          Frappe Cloud hosts; the script also detects
#                          the sentinel env var `FC_FONTATIONS`).
#
#  EXIT CODES
#  ----------
#    0  success, no drift
#    2  bench command failed (migrate / build / cache)
#    3  verify_spec reported drift (run --dry-run next to see the diff)
#
#  IDEMPOTENCY
#  -----------
#  Every bench execute below targets a function that explicitly checks for
#  the desired state before writing. Safe to re-run as many times as
#  needed; safe to run after a no-op git pull. Total runtime ~1 minute
#  on a typical bench.
# =============================================================================

set -euo pipefail

# ── Args ──
DRY_RUN=0
CHECK_ONLY=0
SKIP_BUILD=0
while [[ $# -gt 0 ]]; do
	case "$1" in
		--dry-run)    DRY_RUN=1; shift ;;
		--check-only) CHECK_ONLY=1; shift ;;
		--skip-build) SKIP_BUILD=1; shift ;;
		--build)      SKIP_BUILD=0; shift ;;  # force the build on demand
		--help|-h)
			grep '^#' "$0" | sed 's/^# \?//'
			exit 0
			;;
		*) echo "unknown flag: $1" >&2; exit 2 ;;
	esac
done

# R32: on Frappe Cloud the dashboard's `Deploy` step ALREADY runs
# `bench build --app lms_saas` via the bench deploy hook. Re-running it
# from this script races the CDN cache invalidation and frequently
# leaves the live site's `/assets/` directory returning 404s for every
# JS / CSS / image file until the next Deploy. Auto-skip the build step
# on Frappe Cloud so the operator doesn't have to remember `--skip-build`.
#
# Detection: the bench host sets `FC_FONTATIONS` (the Sentry tracker
# sentinel) or `FRAPPE_CLOUD=1` on Frappe Cloud. Local benches never set
# either, so the default stays "run the build" for the dev workflow.
if [[ "${SKIP_BUILD:-0}" == "0" ]]; then
	if [[ -n "${FC_FONTATIONS:-}" || "${FRAPPE_CLOUD:-}" == "1" ]]; then
		echo "  ↳ detected Frappe Cloud — skipping bench build (the Deploy hook already ran it)"
		echo "    (override with --build if you really want to rebuild)"
		SKIP_BUILD=1
	fi
fi

# ── bench cd ──
if ! command -v bench >/dev/null 2>&1; then
	for d in "${HOME}/frappe-bench" "/home/frappe/frappe-bench" "./frappe-bench"; do
		if [[ -x "$d/env/bin/bench" ]]; then
			cd "$d"
			break
		fi
	done
fi

# ── auto-detect FC_SITE ──
# Priority:
#   1. FC_SITE env var (explicit override)
#   2. The only site on the bench (most common case)
#   3. The site whose name contains "lms" (case-insensitive)
#   4. error with helpful list
if [[ -z "${FC_SITE:-}" ]]; then
	available_sites=$(ls -1 sites/ 2>/dev/null | grep -v '^assets$' || true)
	count=$(printf '%s\n' "$available_sites" | grep -c . || true)
	if [[ "$count" -eq 1 ]]; then
		FC_SITE="$available_sites"
		echo "auto-detected single site on bench: $FC_SITE"
	elif [[ "$count" -gt 1 ]]; then
		lms_site=$(printf '%s\n' "$available_sites" | grep -i '^lms' | head -1 || true)
		if [[ -n "$lms_site" ]]; then
			FC_SITE="$lms_site"
			echo "auto-detected lms site on bench: $FC_SITE"
			echo "  (other sites on this bench: $(printf '%s\n' "$available_sites" | grep -v "^$FC_SITE\$" | tr '\n' ' '))"
		else
			echo "error: bench has multiple sites and none match 'lms*':" >&2
			printf '  %s\n' $available_sites >&2
			echo "  Set FC_SITE explicitly:" >&2
			echo "    FC_SITE=<site> bash apps/lms_saas/scripts/frappe-cloud-update.sh" >&2
			exit 2
		fi
	else
		echo "error: no sites found in sites/. Set FC_SITE explicitly." >&2
		exit 2
	fi
fi

if [[ ! -d "sites/$FC_SITE" ]]; then
	echo "error: sites/$FC_SITE not found" >&2
	ls -1 sites/ 2>/dev/null | grep -v '^assets$' || true
	exit 2
fi

# ── preflight ──
echo "=== Frappe Cloud update for $FC_SITE ==="
if [[ "$DRY_RUN" -eq 1 ]]; then
	echo "(DRY RUN — bench commands will be echoed, not executed)"
fi

run() {
	if [[ "$DRY_RUN" -eq 1 ]]; then
		echo "  would run: $*"
	else
		echo "  → $*"
		"$@"
	fi
}

# ── steps 1–4: standard bench post-deploy ──
if [[ "$CHECK_ONLY" -eq 0 ]]; then
	run bench --site "$FC_SITE" migrate
	if [[ "$SKIP_BUILD" -eq 0 ]]; then
		run bench build --app lms_saas
	fi
	run bench --site "$FC_SITE" clear-cache
	run bench --site "$FC_SITE" enable-scheduler
else
	echo "  --check-only: skipping migrate / build / clear-cache / enable-scheduler"
fi

# ── steps 5–9: lms_saas reconcile + verify ──
run bench --site "$FC_SITE" execute lms_saas.install._reconcile_loan_dashboard
run bench --site "$FC_SITE" execute lms_saas.install._set_portal_role_home_pages
run bench --site "$FC_SITE" execute lms_saas.install._set_admin_home_page
# R32: re-apply the operator's brand to Website Settings + System Settings
# + Navbar Settings. The after_install hook writes these at install time,
# but a deploy does NOT re-run after_install — so the DB values can drift
# from the lms_brand_portal_title in site_config. Idempotent.
if [[ "${LMS_SKIP_REBRAND:-0}" != "1" ]]; then
	run bench --site "$FC_SITE" execute lms_saas.install._setup_navbar_branding
else
	echo "  LMS_SKIP_REBRAND=1 — skipping _setup_navbar_branding"
fi

# verify_spec is the smoke detector — capture its output separately so we can
# set the right exit code (3 = drift) without poisoning the dry-run path.
verify_log=$(mktemp)
if [[ "$DRY_RUN" -eq 1 ]]; then
	echo "  would run: bench --site $FC_SITE execute lms_saas.setup.verify_spec.run_all_checks"
	rm -f "$verify_log"
else
	echo "  → bench --site $FC_SITE execute lms_saas.setup.verify_spec.run_all_checks"
	if ! bench --site "$FC_SITE" execute lms_saas.setup.verify_spec.run_all_checks \
			> "$verify_log" 2>&1; then
		echo "  ❌ verify_spec raised an exception — see log:"
		sed 's/^/    /' "$verify_log"
		rm -f "$verify_log"
		exit 2
	fi
fi

# Surface the verify_spec output to the operator either way (success or
# failure). The output ends with a "FAILED" line iff drift was detected.
if [[ -f "$verify_log" ]]; then
	cat "$verify_log"
	if grep -qE '^FAILED|✗|Drift detected|drift detected' "$verify_log"; then
		rm -f "$verify_log"
		echo "  ❌ verify_spec reported drift — see above. Re-run after correcting the underlying issue."
		exit 3
	fi
	rm -f "$verify_log"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
	echo "  (dry run complete — no bench commands were executed)"
else
	echo "=== Update complete for $FC_SITE ==="
fi
