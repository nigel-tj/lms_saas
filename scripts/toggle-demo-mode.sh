#!/usr/bin/env bash
# Toggle sandbox / demo mode. See lms_saas/scripts/toggle_demo_mode.py
# for the full rationale.
#
# Usage:
#   bash scripts/toggle-demo-mode.sh status                 # show current posture
#   bash scripts/toggle-demo-mode.sh enable [site]          # disable sandbox, re-seed
#   bash scripts/toggle-demo-mode.sh restore [site]         # re-arm sandbox
#
# Works on:
#   * Local monorepo dev bench (uses ./frappe-bench/env/bin/bench)
#   * Frappe Cloud bench (uses the system `bench` from /usr/local/bin)
#
# Both forms land on the same `bench --site <site> execute
# lms_saas.scripts.toggle_demo_mode.<action>` incantation.

set -euo pipefail

ACTION="${1:-status}"
SITE="${2:-app.kesari.africa}"

# Pick a bench binary: prefer the local venv, fall back to PATH.
if [[ -x "./env/bin/bench" ]]; then
	BENCH=./env/bin/bench
elif command -v bench >/dev/null 2>&1; then
	BENCH=bench
else
	echo "error: bench not found (looked for ./env/bin/bench and PATH)" >&2
	exit 1
fi

run() {
	local label="$1"
	shift
	echo "→ ${label}"
	"$BENCH" --site "$SITE" "$@"
}

case "$ACTION" in
	status)
		run "Demo / sandbox status on ${SITE}" \
			execute lms_saas.scripts.toggle_demo_mode.status
		;;
	enable)
		echo "Enabling demo mode on ${SITE} (disabling sandbox, re-seeding data)…"
		run "Enable demo mode" \
			execute lms_saas.scripts.toggle_demo_mode.enable_for_demo
		echo
		echo "Done. Sign-in credentials (if password reset ran):"
		echo "  administrator@example.com / Welcome1!"
		echo "  manager@kesari.africa      / Welcome1!"
		echo "  officer@kesari.africa      / Welcome1!"
		;;
	restore)
		echo "Restoring sandbox mode on ${SITE}…"
		run "Restore sandbox mode" \
			execute lms_saas.scripts.toggle_demo_mode.restore_sandbox
		;;
	*)
		echo "Usage: $0 {status|enable|restore} [site]" >&2
		exit 1
		;;
esac
