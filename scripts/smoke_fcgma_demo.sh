#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
# AGRO-AI FCGMA Local Demo Smoke Test
# Starts the backend and portal (if not already running), then
# runs the Python runtime-verification script against the live API.
# Exits non-zero on any failure.
# ────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO_ROOT/agroai_api"
PORTAL_DIR="$REPO_ROOT/customer-portal"
VERIFY_SCRIPT="$REPO_ROOT/scripts/verify_fcgma_runtime.py"

API_PORT=8000
PORTAL_PORT=8080

BACKEND_PID=""
PORTAL_PID=""

cleanup() {
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "$PORTAL_PID"  ]] && kill "$PORTAL_PID"  2>/dev/null || true
}
trap cleanup EXIT

# ── Check if services are already running ────────────────────
api_running() { curl -s --max-time 2 "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; }
portal_running() { curl -s --max-time 2 "http://127.0.0.1:${PORTAL_PORT}/" >/dev/null 2>&1; }

echo "━━━  AGRO-AI FCGMA Smoke Test  ━━━"
echo ""

# ── Backend ──────────────────────────────────────────────────
if api_running; then
  echo "✓  Backend already running on :${API_PORT}"
else
  echo "→  Starting backend on :${API_PORT}…"
  cd "$API_DIR"
  python3 -m uvicorn app.main:app \
    --host 127.0.0.1 --port "$API_PORT" \
    --log-level warning &
  BACKEND_PID=$!
  echo "   PID: $BACKEND_PID"

  # Wait up to 15s for startup
  for i in $(seq 1 15); do
    sleep 1
    if api_running; then
      echo "✓  Backend started (${i}s)"
      break
    fi
    if [[ $i -eq 15 ]]; then
      echo "✗  Backend did not start after 15s" >&2
      exit 1
    fi
  done
fi

# ── Portal ───────────────────────────────────────────────────
if portal_running; then
  echo "✓  Portal already running on :${PORTAL_PORT}"
else
  echo "→  Starting portal static server on :${PORTAL_PORT}…"
  cd "$PORTAL_DIR"
  python3 -m http.server "$PORTAL_PORT" --bind 127.0.0.1 &>/dev/null &
  PORTAL_PID=$!
  sleep 1
  echo "✓  Portal started  (PID: $PORTAL_PID)"
fi

echo ""
echo "Backend:  http://127.0.0.1:${API_PORT}"
echo "Portal:   http://127.0.0.1:${PORTAL_PORT}/fcgma-demo.html"
echo ""

# ── Route verification ────────────────────────────────────────
echo "━━━  Running API verification  ━━━"
cd "$REPO_ROOT"
python3 "$VERIFY_SCRIPT"
EXIT_CODE=$?

echo ""
if [[ $EXIT_CODE -eq 0 ]]; then
  echo "━━━  Smoke test PASSED  ━━━"
  echo ""
  echo "Open the portal at:  http://127.0.0.1:${PORTAL_PORT}/fcgma-demo.html"
else
  echo "━━━  Smoke test FAILED  ━━━" >&2
fi

exit $EXIT_CODE
