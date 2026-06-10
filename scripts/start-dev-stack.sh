#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
RUN_DIR="$BACKEND_DIR/run"
BACKEND_LOG_DIR="$BACKEND_DIR/logs"
FRONTEND_LOG_DIR="$ROOT_DIR/frontend/logs"
START_FRONTEND_5501="${START_FRONTEND_5501:-false}"
PYTHON_BIN="${PYTHON_BIN:-}"

python_candidate_is_ready() {
  local candidate="$1"
  "$candidate" -c "import flask, flask_cors, requests, celery, redis, sqlalchemy, pymysql" >/dev/null 2>&1
}

resolve_python_bin() {
  local candidates=()
  local candidate

  if [[ -n "$PYTHON_BIN" ]]; then
    candidates+=("$PYTHON_BIN")
  fi

  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    candidates+=("$VIRTUAL_ENV/bin/python3")
  fi

  candidates+=(
    "$ROOT_DIR/.venv/bin/python3"
    "$BACKEND_DIR/.venv/bin/python3"
    "/usr/bin/python3"
  )

  for candidate in "${candidates[@]}"; do
    if [[ -n "$candidate" && -x "$candidate" ]] && python_candidate_is_ready "$candidate"; then
      echo "$candidate"
      return 0
    fi
  done

  command -v python3
}

PYTHON_BIN="$(resolve_python_bin)"

mkdir -p "$RUN_DIR" "$BACKEND_LOG_DIR" "$FRONTEND_LOG_DIR"

start_detached() {
  local log_file="$1"
  local pid_file="$2"
  shift 2

  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "$@" </dev/null >"$log_file" 2>&1 &
  else
    nohup "$@" </dev/null >"$log_file" 2>&1 &
  fi

  echo $! > "$pid_file"
}

is_port_listening() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn | grep -q ":${port} "
  else
    netstat -ltn 2>/dev/null | grep -q ":${port} "
  fi
}

is_celery_running() {
  pgrep -af "python3 -m celery -A app.server:celery_client worker" >/dev/null 2>&1
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
  start_detached "$BACKEND_LOG_DIR/redis.log" "$RUN_DIR/redis.pid" redis-server --bind 127.0.0.1 --port 6379
  sleep 1

  if is_port_listening 6379; then
    echo "[ok] Redis started"
  else
    echo "[warn] Redis failed to start; check $BACKEND_LOG_DIR/redis.log"
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
    start_detached "$BACKEND_LOG_DIR/celery.log" "$RUN_DIR/celery.pid" env \
      CELERY_BROKER_URL="redis://127.0.0.1:6379/0" \
      CELERY_RESULT_BACKEND="redis://127.0.0.1:6379/1" \
      "$PYTHON_BIN" -m celery -A app.server:celery_client worker -l info -P solo \
  )
  sleep 1

  if is_celery_running; then
    echo "[ok] Celery worker started"
  else
    echo "[warn] Celery worker failed to start; check $BACKEND_LOG_DIR/celery.log"
  fi
}

ensure_backend() {
  if is_port_listening 5000; then
    echo "[ok] Backend already listening on :5000"
    return
  fi

  echo "[start] Backend API"
  (
    cd "$BACKEND_DIR"
    start_detached "$BACKEND_LOG_DIR/backend.log" "$RUN_DIR/backend.pid" "$PYTHON_BIN" -m app.server
  )
  if wait_for_port 5000 40 0.5; then
    echo "[ok] Backend started"
  else
    echo "[error] Backend failed to start; check $BACKEND_LOG_DIR/backend.log"
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
    start_detached "$FRONTEND_LOG_DIR/frontend.log" "$RUN_DIR/frontend.pid" "$PYTHON_BIN" -m http.server 5501 --directory frontend
  )
  if wait_for_port 5501 20 0.5; then
    echo "[ok] Frontend started"
  else
    echo "[error] Frontend failed to start; check $FRONTEND_LOG_DIR/frontend.log"
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
  echo "Backend logs : $BACKEND_LOG_DIR"
  echo "Frontend logs: $FRONTEND_LOG_DIR"
}

echo "[info] Starting dev stack under $ROOT_DIR"
echo "[info] Using Python: $PYTHON_BIN"
ensure_redis
ensure_celery
ensure_backend
if [[ "$START_FRONTEND_5501" == "true" ]]; then
  ensure_frontend
else
  echo "[skip] Frontend :5501 disabled (single-port mode). Set START_FRONTEND_5501=true to enable."
fi
print_status
