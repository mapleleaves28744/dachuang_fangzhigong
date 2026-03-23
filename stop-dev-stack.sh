#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"

kill_by_pidfile() {
  local name="$1"
  local file="$2"

  if [[ ! -f "$file" ]]; then
    return
  fi

  local pid
  pid="$(cat "$file" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "[stop] $name (pid=$pid)"
    kill "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$file"
}

kill_by_pattern() {
  local name="$1"
  local pattern="$2"
  local pids
  pids="$(pgrep -f "$pattern" || true)"
  if [[ -n "$pids" ]]; then
    echo "[stop] $name via pattern"
    echo "$pids" | xargs -r kill 2>/dev/null || true
  fi
}

mkdir -p "$RUN_DIR"

kill_by_pidfile "frontend" "$RUN_DIR/frontend.pid"
kill_by_pidfile "backend" "$RUN_DIR/backend.pid"
kill_by_pidfile "celery" "$RUN_DIR/celery.pid"
kill_by_pidfile "redis" "$RUN_DIR/redis.pid"

# Fallback for manually started processes.
kill_by_pattern "frontend" "python3 -m http.server 5501 --directory frontend"
kill_by_pattern "backend" "python3 backend/app.py"
kill_by_pattern "celery" "celery.*app.celery_client.*worker"

echo "[ok] Stop attempt finished"
