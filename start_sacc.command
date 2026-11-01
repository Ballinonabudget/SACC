#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# SACC Launcher — v3.0 (The Native Bridge)
# One server (FastAPI/uvicorn on 5174) serves both the API and the SCAA UI.
# Double-click in Finder to launch.
# ─────────────────────────────────────────────────────────────────────────────

SACC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=5174
PYTHON_BIN="$SACC_DIR/.venv-poc-313/bin/python"

# ── Cleanup on exit ──────────────────────────────────────────────────────────
cleanup() {
  echo ""
  echo "  Shutting down SACC…"
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
  lsof -ti tcp:$PORT | xargs kill -9 2>/dev/null
  echo "  Done. Goodbye."
  exit 0
}
trap cleanup INT TERM EXIT

# ── Clear stale process on port ──────────────────────────────────────────────
if lsof -ti tcp:$PORT > /dev/null 2>&1; then
  echo "→ Clearing port $PORT…"
  lsof -ti tcp:$PORT | xargs kill -9 2>/dev/null
  sleep 0.5
fi

# ── Ensure the supported SACC runtime is available ───────────────────────────
if [ ! -x "$PYTHON_BIN" ]; then
  SYSTEM_PYTHON="/opt/homebrew/bin/python3.13"
  [ -x "$SYSTEM_PYTHON" ] || SYSTEM_PYTHON="$(command -v python3)"
  echo "→ Creating SACC Python environment…"
  "$SYSTEM_PYTHON" -m venv "$SACC_DIR/.venv-poc-313"
fi

"$PYTHON_BIN" -c "import fastapi, uvicorn, google.genai" 2>/dev/null || {
  echo "→ Installing SACC dependencies…"
  "$PYTHON_BIN" -m pip install -r "$SACC_DIR/requirements-poc.txt" --quiet
}

echo ""
echo "  ┌──────────────────────────────────────────────────┐"
echo "  │         SACC v3.0 — Sneaker Archive              │"
echo "  │                                                  │"
echo "  │   UI  →  http://localhost:$PORT/SACC.html        │"
echo "  │   API →  http://localhost:$PORT/api/health       │"
echo "  │                                                  │"
echo "  │   Press Control+C to stop                       │"
echo "  └──────────────────────────────────────────────────┘"
echo ""
echo "  SACC root : $SACC_DIR"
echo ""

# ── Start FastAPI server (serves both API and SCAA static frontend) ──────────
cd "$SACC_DIR"
"$PYTHON_BIN" -m uvicorn main:app --host 127.0.0.1 --port $PORT > /tmp/sacc_api.log 2>&1 &
SERVER_PID=$!
echo "  ✓ Server started (PID $SERVER_PID)"

# ── Wait for server to be ready (up to 8s) ───────────────────────────────────
for i in 1 2 3 4 5 6 7 8; do
  sleep 1
  if curl -s "http://localhost:$PORT/api/health" > /dev/null 2>&1; then
    echo "  ✓ Server online at http://localhost:$PORT"
    break
  fi
  echo "  ⟳ Waiting for server… ($i/8)"
done

# ── Open browser ─────────────────────────────────────────────────────────────
open "http://localhost:$PORT/SACC.html"
echo "  ✓ Browser opened → http://localhost:$PORT/SACC.html"
echo ""
echo "  Log: /tmp/sacc_api.log"
echo ""

# ── Keep alive ───────────────────────────────────────────────────────────────
wait $SERVER_PID
