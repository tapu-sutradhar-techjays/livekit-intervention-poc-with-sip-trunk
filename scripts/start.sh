#!/usr/bin/env bash
# Bring up the three spike services (worker, FastAPI, Vite) in the background.
# Logs to .logs/, PIDs to .pids/. Idempotent: errors if anything's already running.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)"
cd "$REPO_ROOT"

LOGS="$REPO_ROOT/.logs"
PIDS="$REPO_ROOT/.pids"
mkdir -p "$LOGS" "$PIDS"

# --- preflight -------------------------------------------------------------

if [ ! -f .env ]; then
    echo "✗ .env not found — copy .env.example and fill it in." >&2
    exit 1
fi

check_port() {
    local port=$1
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        echo "✗ port $port already in use — run ./scripts/stop.sh first" >&2
        exit 1
    fi
}
check_port 8001
check_port 5173

check_pid() {
    local name=$1
    local pidfile="$PIDS/$name.pid"
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        echo "✗ $name already running (pid $(cat "$pidfile")) — run ./scripts/stop.sh first" >&2
        exit 1
    fi
    rm -f "$pidfile"
}
check_pid worker
check_pid api
check_pid frontend

# --- start ----------------------------------------------------------------

echo "→ starting worker..."
: > "$LOGS/worker.log"
nohup uv run python -m src.worker dev > "$LOGS/worker.log" 2>&1 &
echo $! > "$PIDS/worker.pid"

echo "→ starting FastAPI on :8001..."
: > "$LOGS/api.log"
nohup uv run uvicorn src.server.main:app --host 127.0.0.1 --port 8001 \
    > "$LOGS/api.log" 2>&1 &
echo $! > "$PIDS/api.pid"

echo "→ starting Vite on :5173..."
: > "$LOGS/frontend.log"
if [ ! -d frontend/node_modules ]; then
    echo "  (installing frontend deps first…)"
    (cd frontend && npm install --silent)
fi
(cd frontend && nohup npm run dev > "$LOGS/frontend.log" 2>&1 & echo $! > "$PIDS/frontend.pid")

# --- wait for ready -------------------------------------------------------

wait_for() {
    local name=$1 logfile=$2 ok_pat=$3 err_pat=$4 timeout=${5:-30}
    local start=$SECONDS
    while true; do
        if grep -qE "$ok_pat" "$logfile" 2>/dev/null; then
            echo "  ✓ $name ready"
            return 0
        fi
        if grep -qE "$err_pat" "$logfile" 2>/dev/null; then
            echo "  ✗ $name errored — tail $logfile:" >&2
            tail -20 "$logfile" >&2
            return 1
        fi
        if (( SECONDS - start > timeout )); then
            echo "  ✗ $name not ready after ${timeout}s — tail $logfile:" >&2
            tail -20 "$logfile" >&2
            return 1
        fi
        sleep 0.5
    done
}

echo
echo "→ waiting for services..."
wait_for "worker"   "$LOGS/worker.log"   "registered worker"  "Traceback|ModuleNotFoundError|invalid"   45 || exit 1
wait_for "fastapi"  "$LOGS/api.log"      "Uvicorn running"    "Traceback|Address already in use|ERROR" 15 || exit 1
wait_for "frontend" "$LOGS/frontend.log" "Local:|ready in"    "EADDRINUSE|error during"                30 || exit 1

# --- summary --------------------------------------------------------------

echo
echo "All services up."
echo
printf "  %-9s pid=%-6s log=%s\n" "worker"   "$(cat "$PIDS/worker.pid")"   "$LOGS/worker.log"
printf "  %-9s pid=%-6s log=%s    http://127.0.0.1:8001\n" "fastapi"  "$(cat "$PIDS/api.pid")"      "$LOGS/api.log"
printf "  %-9s pid=%-6s log=%s    http://localhost:5173\n" "frontend" "$(cat "$PIDS/frontend.pid")" "$LOGS/frontend.log"
echo
echo "Tail logs: tail -f $LOGS/{worker,api,frontend}.log"
echo "Stop:      ./scripts/stop.sh"
