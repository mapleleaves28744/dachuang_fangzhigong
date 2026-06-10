#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"
DURATION_SEC="${DURATION_SEC:-8}"
LEVELS="${LEVELS:-20,50,100}"
BURST="${BURST:-40}"

/usr/bin/python3 scripts/testing/concurrency_benchmark.py --base-url "$BASE_URL" --duration-sec "$DURATION_SEC" --levels "$LEVELS"
/usr/bin/python3 scripts/testing/security_suite.py --base-url "$BASE_URL" --burst "$BURST"
/usr/bin/python3 scripts/testing/usability_eval.py --base-url "$BASE_URL"
/usr/bin/env bash scripts/testing/sync_report_dashboard.sh
/usr/bin/python3 docs/testing/generate_test_report_artifacts.py

echo "All testing artifacts generated under docs/testing and frontend/assets/data"
