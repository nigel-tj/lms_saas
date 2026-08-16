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
#    2. (skipped)             — `bench build` is intentionally NOT run by
#                                this script. Re-running it races the CDN
#                                cache invalidation and breaks the live
#                                site (every /assets/ file returns 404).
#                                Asset rebuilds are the Frappe Cloud
#                                `Deploy` hook's job, or run manually
#                                with `bench build --app lms_saas --force`
#                                when debugging a broken CDN.
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
#   10. configure_live_email.run        — reconcile the live outgoing Email
#                                          Account from lms_live_smtp_* keys
#                                          in site_config. No-op when SMTP
#                                          keys are absent; creates/updates
#                                          the default outgoing account and
#                                          retries the stuck Email Queue
#                                          when they are present. Idempotent.
#   11. verify_spec.run_all_checks       — the operator's verification
#                                          suite. Catches workspace drift,
#                                          role-home desync, audit pipeline
#                                          gaps, and brand-chain leaks.
#
#  WHY EACH LmsSaAs STEP IS NEEDED
#  -----------------------------
#  Steps 1, 3, 4 are the standard Frappe bench post-deploy — they run for
#  EVERY app, so a misbehaving site config can't tell which app needs what.
#  Step 2 (`bench build`) is intentionally NOT run by this script. The
#  Frappe Cloud `Deploy` hook already builds the assets, and re-running
#  the build races the CDN cache invalidation — the documented Frappe
#  Cloud symptom is a whole-site 404 storm on every /assets/ file until
#  the next Deploy. If the build is genuinely out of date, run it
#  MANUALLY with `bench build --app lms_saas --force` — not from this
#  script.
#  Steps 5–8 are lms_saas-only self-heal: the install/after_install hook
#  writes a lot of workspace, home-page, and dashboard-card state at
#  install time. If a deploy lands while the desk is open, those refs can
#  be stale by the time the next user logs in. Each `_reconcile_*` /
#  `_set_*` function is idempotent — safe to re-run on every deploy, even
#  when nothing changed.
#
#  Step 9 is the smoke detector: it diff-asserts the live site's shape
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
#    --skip-build  ALREADY THE DEFAULT. The script never runs `bench
#                  build` — re-running it races the CDN cache
#                  invalidation and leaves the live site returning 404s
#                  on every /assets/ file. Kept as a flag for symmetry
#                  with Frappe's `bench build` CLI, but passing it has
#                  no effect (the build is skipped either way).
#    --build       opt-in rebuild. Use ONLY when an asset is genuinely
#                  out of date and you cannot wait for the next Frappe
#                  Cloud Deploy. Forces `bench build --app lms_saas
#                  --force` so the cache is bypassed.
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
# R32: SKIP_BUILD defaults to 1 — the script never runs `bench build`
# automatically. Asset rebuilds are the Frappe Cloud `Deploy` hook's job
# (or a manual `bench build --app lms_saas --force` if the operator is
# debugging a broken CDN). Re-running the build from this script races
# the CDN cache invalidation and leaves the live site returning 404s on
# every /assets/ file until the next Deploy. Local dev benches can opt
# back in with `--build` (the FC host auto-detect is irrelevant there).
SKIP_BUILD=1
while [[ $# -gt 0 ]]; do
	case "$1" in
		--dry-run)    DRY_RUN=1; shift ;;
		--check-only) CHECK_ONLY=1; shift ;;
		--skip-build) SKIP_BUILD=1; shift ;;
		--build)      SKIP_BUILD=0; shift ;;  # opt-in re-build
		--help|-h)
			grep '^#' "$0" | sed 's/^# \?//'
			exit 0
			;;
		*) echo "unknown flag: $1" >&2; exit 2 ;;
	esac
done

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
	# Only consider directories inside sites/ — earlier versions of this
	# script globbed every path, which picked up `common_site_config.json`,
	# `apps.json`, `apps.txt`, etc. as "sites" and confused the
	# auto-detect when a bench has multiple real sites.
	available_sites=$(find sites/ -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | grep -v '^assets$' || true)
	count=$(printf '%s\n' "$available_sites" | grep -c . || true)
	if [[ "$count" -eq 1 ]]; then
		FC_SITE="$available_sites"
		echo "auto-detected single site on bench: $FC_SITE"
	elif [[ "$count" -gt 1 ]]; then
		# Prefer a site whose name literally starts with "lms" — the
		# operator's domain name is the strongest signal. Fall back to a
		# site containing "lms" anywhere (catches domains like
		# `lending-client.frappe.cloud`). Last-resort fallback uses the
		# first site alphabetically and warns the operator.
		lms_site=$(printf '%s\n' "$available_sites" | grep -i '^lms' | head -1 || true)
		if [[ -z "$lms_site" ]]; then
			lms_site=$(printf '%s\n' "$available_sites" | grep -i 'lms' | head -1 || true)
		fi
		if [[ -n "$lms_site" ]]; then
			FC_SITE="$lms_site"
			echo "auto-detected lms site on bench: $FC_SITE"
			echo "  (other sites on this bench: $(printf '%s\n' "$available_sites" | grep -v "^$FC_SITE\$" | tr '\n' ' '))"
		else
			echo "warning: bench has multiple sites and none contain 'lms'." >&2
			echo "  Picking the alphabetically-first site as a guess:" >&2
			echo "    $(printf '%s\n' "$available_sites" | sort | head -1)" >&2
			echo "  Set FC_SITE explicitly to silence this warning:" >&2
			echo "    FC_SITE=<site> bash apps/lms_saas/scripts/frappe-cloud-update.sh" >&2
			FC_SITE=$(printf '%s\n' "$available_sites" | sort | head -1)
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
		# --force bypasses the bench asset cache (whose CDN mapping can
		# drift) and regenerates every asset from source. This is the
		# explicit opt-in path; the script never runs `bench build`
		# automatically because re-running it from `Deploy` hook context
		# races the CDN cache invalidation and breaks the live site.
		run bench build --app lms_saas --force
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

# R44: reset company currency to USD + provision test users + live repair.
# The currency reset ensures the portal shows $ (not ZAR) after a deploy.
# The provision_test_users ensures all demo users have the correct branch
# assignment (Main Branch - LD) and roles. Idempotent — safe to re-run.
if [[ "${LMS_SKIP_CURRENCY_RESET:-0}" != "1" ]]; then
	# R45: if LMS_COMPANY_OVERRIDE is set, rename the live Company to the
	# operator-requested name (e.g. "Kesari" → "LMS Demo Co") so live matches
	# local. Comma-separated key=value list, e.g.:
	#   LMS_COMPANY_OVERRIDE="company=LMS Demo Co,abbr=LD,currency=USD,country=Zimbabwe"
	if [[ -n "${LMS_COMPANY_OVERRIDE:-}" ]]; then
		echo "  → R45: reconcile Company name/currency/country per LMS_COMPANY_OVERRIDE"
		# Build the kwargs as a Python dict LITERAL (not JSON) from the
		# comma-separated key=value string. R48 lesson:
		#   - bench execute does `eval(kwargs)` on the --kwargs value.
		#   - JSON uses double quotes around keys, but bench's argument
		#     parser would then try to unquote the JSON string and fail.
		#   - Wrapping the JSON in '...' (the old code) was wrong: the
		#     wrapping quotes got concatenated into the value, and eval
		#     failed with "argument after ** must be a mapping, not str"
		#     — the function was called with no kwargs and the rename
		#     silently did nothing.
		# The fix: hand bench a valid Python dict literal directly. Use
		# single quotes around both keys and values (no spaces in keys,
		# values are user input — escape any single quotes inside).
		override_kwargs=$(LMS_COMPANY_OVERRIDE="$LMS_COMPANY_OVERRIDE" python3 -c '
import os
raw = os.environ.get("LMS_COMPANY_OVERRIDE", "")
parts = []
for kv in raw.split(","):
    kv = kv.strip()
    if not kv or "=" not in kv:
        continue
    k, v = kv.split("=", 1)
    k = k.strip()
    v = v.strip()
    # Escape any single quotes in the value.
    v_escaped = v.replace("'"'"'", "\\'"'"'")
    parts.append(f"'"'"'{k}'"'"': '"'"'{v_escaped}'"'"'")
print("{" + ", ".join(parts) + ", " + "'"'"'apply'"'"': 1}")
')
		# Hand the dict literal to bench execute. NO outer quoting — the
		# entire literal IS the value of --kwargs.
		run bench --site "$FC_SITE" execute \
			lms_saas.setup.live_repair.reconcile_company_name \
			--kwargs "$override_kwargs" || true
	fi
	echo "  → R44: sync lms_currency site_config key to match company default_currency"
	run bench --site "$FC_SITE" execute lms_saas.setup.set_company_currency_country._sync_site_config_currency || true
	echo "  → R44: repair live site state"
	run bench --site "$FC_SITE" execute lms_saas.setup.live_repair.repair_live_site_state || true
	echo "  → R44: provision test users"
	run bench --site "$FC_SITE" execute lms_saas.setup.live_repair.provision_test_users || true
else
	echo "  LMS_SKIP_CURRENCY_RESET=1 — skipping currency sync + provision"
fi

# R48: reconcile the live outgoing Email Account from site_config SMTP keys.
# configure_live_email.run is idempotent and returns {ok: False, reason: ...}
# when lms_live_smtp_* keys are absent — so this is a safe no-op on sites
# that haven't configured SMTP yet, and a one-shot fix on sites that have.
# Without this step, every deploy ships with no outgoing Email Account and
# every frappe.sendmail call lands in the Email Queue as 'Error'.
echo "  → R48: reconcile live outgoing Email Account (SMTP)…"
if [[ "$DRY_RUN" -eq 1 ]]; then
	echo "  would run: bench --site $FC_SITE execute lms_saas.setup.configure_live_email.run"
else
	bench --site "$FC_SITE" execute lms_saas.setup.configure_live_email.run 2>&1 | sed 's/^/    /' || true
fi

# R49: clear the Email Account footer so "Sent via ERPNext" (or any other
# stale third-party footer) doesn't leak below the LMS branded footer.
# Idempotent — no-op when the footer is already empty.
echo "  → R49: reconcile Email Account footer (clear stale branding)…"
if [[ "$DRY_RUN" -eq 1 ]]; then
	echo "  would run: bench --site $FC_SITE execute lms_saas.setup.configure_live_email.reconcile_email_footer"
else
	bench --site "$FC_SITE" execute lms_saas.setup.configure_live_email.reconcile_email_footer 2>&1 | sed 's/^/    /' || true
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
	# Provision test users if they don't exist yet (idempotent, admin-only).
	echo "  → Provisioning test users (idempotent)…"
	bench --site "$FC_SITE" execute lms_saas.setup.live_repair.provision_test_users 2>&1 | sed 's/^/    /' || true
	# QA-2026-08-03-#23: Re-link the demo borrower User to a Customer that
	# owns at least one Loan. Surgical fix that runs after provision_test_users
	# so a fresh re-seed always shows real loans in the borrower portal.
	echo "  → Re-linking demo borrower User → Customer with active loans…"
	bench --site "$FC_SITE" execute lms_saas.setup.live_repair.link_borrower_to_demo_customer 2>&1 | sed 's/^/    /' || true
	# Seed demo collateral for borrowers with active loans (idempotent, admin-only).
	echo "  → Seeding demo collateral (idempotent)…"
	bench --site "$FC_SITE" execute lms_saas.setup.live_repair.seed_demo_collateral 2>&1 | sed 's/^/    /' || true
	echo "=== Update complete for $FC_SITE ==="
fi
