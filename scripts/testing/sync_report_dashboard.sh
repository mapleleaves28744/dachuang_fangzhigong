#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

/usr/bin/python3 docs/testing/generate_full_test_report.py

echo "Synced report + dashboard data: docs/testing and frontend/assets/data"