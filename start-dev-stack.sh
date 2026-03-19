#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$ROOT_DIR/.logs"
START_FRONTEND_5501="${START_FRONTEND_5501:-false}"

mkdir -p "$RUN_DIR" "$LOG_DIR"

is_port_listening() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn | grep -q ":${port} "
  else
    netstat -ltn 2>/dev/null | grep -q ":${port} "
  fi
}

is_celery_running() {
  pgrep -af "python3 -m celery -A app.celery_client worker" >/dev/null 2>&1
}

wait_for_port() {
  local port="$1"
  local retries="${2:-20}"
  local sleep_seconds="${3:-0.5}"
  local i
  for ((i = 1; i <= retries; i++)); do
    if is_port_listening "$port"; then
      return 0
    fi
    sleep "$sleep_seconds"
  done
  return 1
}

ensure_redis() {
  if is_port_listening 6379; then
    echo "[ok] Redis already listening on :6379"
    return
  fi

  if ! command -v redis-server >/dev/null 2>&1; then
    echo "[warn] redis-server not found; Celery async tasks may be unavailable"
    return
  fi

  echo "[start] Redis"
  nohup redis-server --bind 127.0.0.1 --port 6379 > "$LOG_DIR/redis.log" 2>&1 &
  echo $! > "$RUN_DIR/redis.pid"
  sleep 1

  if is_port_listening 6379; then
    echo "[ok] Redis started"
  else
    echo "[warn] Redis failed to start; check $LOG_DIR/redis.log"
  fi
}

ensure_celery() {
  if is_celery_running; then
    echo "[ok] Celery worker already running"
    return
  fi

  if ! is_port_listening 6379; then
    echo "[warn] Redis is not ready; skip Celery startup"
    return
  fi

  echo "[start] Celery worker"
  (
    cd "$BACKEND_DIR"
    nohup env \
      CELERY_BROKER_URL="redis://127.0.0.1:6379/0" \
      CELERY_RESULT_BACKEND="redis://127.0.0.1:6379/1" \
      python3 -m celery -A app.celery_client worker -l info -P solo \
      > "$LOG_DIR/celery.log" 2>&1 &
    echo $! > "$RUN_DIR/celery.pid"
  )
  sleep 1

  if is_celery_running; then
    echo "[ok] Celery worker started"
  else
    echo "[warn] Celery worker failed to start; check $LOG_DIR/celery.log"
  fi
}

ensure_backend() {
  if is_port_listening 5000; then
    echo "[ok] Backend already listening on :5000"
    return
  fi

  echo "[start] Backend API"
  (
    cd "$ROOT_DIR"
    nohup python3 backend/app.py > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$RUN_DIR/backend.pid"
  )
  if wait_for_port 5000 40 0.5; then
    echo "[ok] Backend started"
  else
    echo "[error] Backend failed to start; check $LOG_DIR/backend.log"
    return 1
  fi
}

ensure_frontend() {
  if is_port_listening 5501; then
    echo "[ok] Frontend already listening on :5501"
    return
  fi

  echo "[start] Frontend static server"
  (
    cd "$ROOT_DIR"
    nohup python3 -m http.server 5501 --directory frontend > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$RUN_DIR/frontend.pid"
  )
  if wait_for_port 5501 20 0.5; then
    echo "[ok] Frontend started"
  else
    echo "[error] Frontend failed to start; check $LOG_DIR/frontend.log"
    return 1
  fi
}

print_status() {
  echo
  echo "===== Service Status ====="
  curl -sS http://127.0.0.1:5000/health || true
  echo
  echo "Single-port access (recommended for remote forwarding):"
  echo "Home: http://127.0.0.1:5000/index.html"
  echo "Dashboard: http://127.0.0.1:5000/dashboard.html"
  echo "Knowledge Map: http://127.0.0.1:5000/knowledge-map.html"
  echo
  if [[ "$START_FRONTEND_5501" == "true" ]]; then
    echo "Frontend: http://127.0.0.1:5501/index.html"
    echo "Dashboard: http://127.0.0.1:5501/dashboard.html"
    echo "Knowledge Map: http://127.0.0.1:5501/knowledge-map.html"
  fi
  echo "Logs: $LOG_DIR"
}

echo "[info] Starting dev stack under $ROOT_DIR"
ensure_redis
ensure_celery
ensure_backend
if [[ "$START_FRONTEND_5501" == "true" ]]; then
  ensure_frontend
else
  echo "[skip] Frontend :5501 disabled (single-port mode). Set START_FRONTEND_5501=true to enable."
fi
print_status
