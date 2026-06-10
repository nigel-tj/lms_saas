#!/usr/bin/env bash
set -euo pipefail

SITE="${1:-lms.localhost}"
BENCH_DIR="${BENCH_DIR:-$(cd "$(dirname "$0")/../../frappe-bench" && pwd)}"

export PATH="${HOME}/.local/bin:${PATH}"

cd "$BENCH_DIR"
bench --site "$SITE" backup --with-files

echo "Backup completed for site: $SITE"
echo "Location: $BENCH_DIR/sites/$SITE/private/backups/"
