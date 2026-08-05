#!/usr/bin/env bash
# apps/lms_saas/scripts/role-sweep.sh — top-level entry for the role-by-role sweep
#
# Convenience wrapper around apps/lms_saas/scripts/role-sweep/run.sh — keeps the
# historical short command name that operators used for the standalone scripts.

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$HERE/role-sweep/run.sh" "$@"
