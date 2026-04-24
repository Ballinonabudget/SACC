#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# SACC Launcher
# Starts both the Flask API backend and the static SCAA frontend server,
# then opens the browser automatically.
# Double-click this file in Finder to launch everything.
# ─────────────────────────────────────────────────────────────────────────────

SACC_DIR="$(dirname "$0")"
SCAA_DIR="$SACC_DIR/SCAA"
API_PORT=5174
UI_PORT=5173
API_PID=""
UI_PID=""

# ── Cleanup on exit ──────────────────────────────────────────────────────────
cleanup() {
  echo ""
  echo "  Shutting down SACC servers…"
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null
  [ -n "$UI_PID"  ] && kill "$UI_PID"  2>/dev/null
  # Kill anything still on those ports
  lsof -ti tcp:$API_PORT | xargs kill -9 2>/dev/null
  lsof -ti tcp:$UI_PORT  | xargs kill -9 2>/dev/null
  echo "  Done. Goodbye."
  exit 0
}
trap cleanup INT TERM EXIT

# ── Kill stale processes on the ports ────────────────────────────────────────
for PORT in $API_PORT $UI_PORT; do
  if lsof -ti tcp:$PORT > /dev/null 2>&1; then
    echo "→ Clearing port $PORT…"
    lsof -ti tcp:$PORT | xargs kill -9 2>/dev/null
    sleep 0.5
  fi
done

# ── Install flask-cors if missing ────────────────────────────────────────────
python3 -c "import flask_cors" 2>/dev/null || {
  echo "→ Installing flask-cors…"
  python3 -m pip install flask flask-cors --quiet
}

echo ""
echo "  ┌──────────────────────────────────────────────────┐"
echo "  │         SACC — Sneaker Archive Command Center    │"
echo "  │                                                  │"
echo "  │   UI  →  http://localhost:$UI_PORT/SACC.html       │"
echo "  │   API →  http://localhost:$API_PORT/api/health     │"
echo "  │                                                  │"
echo "  │   Press Control+C to stop both servers          │"
echo "  └──────────────────────────────────────────────────┘"
echo ""

# ── Start Flask API backend ──────────────────────────────────────────────────
cd "$SACC_DIR"
python3 api.py > /tmp/sacc_api.log 2>&1 &
API_PID=$!
echo "  ✓ API server started (PID $API_PID)"

# ── Wait for API to be ready (up to 5s) ─────────────────────────────────────
for i in 1 2 3 4 5; do
  sleep 1
  if curl -s "http://localhost:$API_PORT/api/health" > /dev/null 2>&1; then
    echo "  ✓ API online at http://localhost:$API_PORT"
    break
  fi
  echo "  ⟳ Waiting for API… ($i/5)"
done

# ── Start static file server for SCAA frontend ───────────────────────────────
cd "$SCAA_DIR"
python3 -m http.server $UI_PORT > /tmp/sacc_ui.log 2>&1 &
UI_PID=$!
echo "  ✓ UI server started (PID $UI_PID)"

# ── Open browser ─────────────────────────────────────────────────────────────
sleep 0.5
open "http://localhost:$UI_PORT/SACC.html"
echo "  ✓ Browser opened → http://localhost:$UI_PORT/SACC.html"
echo ""
echo "  API log: /tmp/sacc_api.log"
echo "  UI log:  /tmp/sacc_ui.log"
echo ""

# ── Keep alive ───────────────────────────────────────────────────────────────
wait $API_PID $UI_PID
