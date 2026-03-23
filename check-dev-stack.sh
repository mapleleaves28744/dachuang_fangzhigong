#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

check_url() {
  local name="$1"
  local url="$2"
  local code
  code="$(curl -sS -o /tmp/fzg_check_tmp.out -w '%{http_code}' "$url" || true)"
  if [[ "$code" == "200" ]]; then
    echo "[ok] $name ($url)"
  else
    echo "[fail] $name ($url) => HTTP $code"
    head -c 300 /tmp/fzg_check_tmp.out || true
    echo
    return 1
  fi
}

echo "[info] Checking core services..."
check_url "health" "http://127.0.0.1:5000/health"

echo "[info] Inspecting async capability..."
health_json="$(curl -sS http://127.0.0.1:5000/health || true)"
celery_enabled="$(HEALTH_JSON="$health_json" python3 -c "import os, json; j=json.loads(os.environ.get('HEALTH_JSON') or '{}'); print(str(bool(j.get('celery_enabled', False))).lower())" 2>/dev/null || echo false)"
celery_worker_available="$(HEALTH_JSON="$health_json" python3 -c "import os, json; j=json.loads(os.environ.get('HEALTH_JSON') or '{}'); print(str(bool(j.get('celery_worker_available', False))).lower())" 2>/dev/null || echo false)"

if [[ "$celery_enabled" == "true" && "$celery_worker_available" != "true" ]]; then
  echo "[warn] Celery client is enabled but no worker is available; graph sync will fallback to sync mode"
fi

check_url "frontend-index-via-backend" "http://127.0.0.1:5000/index.html"
check_url "dashboard-via-backend" "http://127.0.0.1:5000/dashboard.html"
check_url "knowledge-map-via-backend" "http://127.0.0.1:5000/knowledge-map.html"

echo "[info] Checking Q&A API..."
ask_code="$(curl -sS -o /tmp/fzg_ask_tmp.out -w '%{http_code}' 'http://127.0.0.1:5000/api/ask?user_id=default_user&question=%E6%B5%8B%E8%AF%95' || true)"
if [[ "$ask_code" == "200" ]] && grep -q '"success": true' /tmp/fzg_ask_tmp.out; then
  echo "[ok] ask api"
else
  echo "[fail] ask api => HTTP $ask_code"
  head -c 400 /tmp/fzg_ask_tmp.out || true
  echo
  exit 1
fi

echo "[ok] All checks passed"
