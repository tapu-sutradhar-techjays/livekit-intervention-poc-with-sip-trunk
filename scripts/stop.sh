#!/usr/bin/env bash
# Stop the three spike services and force-end any active LiveKit rooms
# (which sends BYE to Twilio so PSTN billing stops). Idempotent.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)"
cd "$REPO_ROOT"

PIDS="$REPO_ROOT/.pids"

# --- end live LiveKit rooms first so SIP carrier legs drop cleanly --------
if [ -f .env ]; then
    echo "→ ending any active LiveKit rooms..."
    if ! uv run python scripts/end_call.py --all 2>&1 | sed 's/^/  /'; then
        echo "  (end_call exited non-zero; continuing with process shutdown)" >&2
    fi
fi

# --- kill by PID file -----------------------------------------------------
stop_one() {
    local name=$1
    local pidfile="$PIDS/$name.pid"
    if [ ! -f "$pidfile" ]; then
        return
    fi
    local pid
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
        echo "→ stopping $name (pid $pid)..."
        # Kill children first (uv → python; npm → node → vite)
        pkill -TERM -P "$pid" 2>/dev/null || true
        kill -TERM "$pid" 2>/dev/null || true
        for _ in 1 2 3 4 5 6 7 8; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.3
        done
        if kill -0 "$pid" 2>/dev/null; then
            pkill -KILL -P "$pid" 2>/dev/null || true
            kill -KILL "$pid" 2>/dev/null || true
        fi
    fi
    rm -f "$pidfile"
}

stop_one worker
stop_one api
stop_one frontend

# --- belt-and-braces: kill anything matching the command lines ------------
pkill -f "src.worker"         2>/dev/null || true
pkill -f "uvicorn src.server" 2>/dev/null || true
pkill -f "node.*vite"         2>/dev/null || true

# --- verify clean ---------------------------------------------------------
sleep 1
echo
echo "→ verifying clean state..."

remaining=$(pgrep -fl "src\\.worker|uvicorn src\\.server|node.*vite" 2>/dev/null || true)
if [ -n "$remaining" ]; then
    echo "  ⚠ still running:" >&2
    echo "$remaining" >&2
    exit 1
fi
echo "  ✓ no spike processes running"

ports=$(lsof -nP -iTCP:8001,5173 -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$ports" ]; then
    echo "  ⚠ ports still bound:" >&2
    echo "$ports" >&2
    exit 1
fi
echo "  ✓ ports 8001 + 5173 free"

if [ -f .env ]; then
    echo
    echo "→ active LiveKit rooms (should be empty):"
    uv run python scripts/list_rooms.py 2>&1 | sed 's/^/  /' || true
fi
