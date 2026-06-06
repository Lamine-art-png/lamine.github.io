#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# AGRO-AI Water Intelligence Copilot — Local Demo Runner
# Fox Canyon Applied-Water Mission Control
#
# Usage:
#   chmod +x scripts/run_fcgma_demo.sh
#   ./scripts/run_fcgma_demo.sh
#
# Optional environment:
#   CIMIS_APP_KEY=your-key      # Enables live CIMIS weather context
#   WISECONN_API_KEY=your-key   # Enables live WiseConn controller telemetry
#   ANTHROPIC_API_KEY=your-key  # Enables LLM copilot formatting
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
API_DIR="$ROOT_DIR/agroai_api"
PORTAL_DIR="$ROOT_DIR/customer-portal"

API_PORT="${API_PORT:-8000}"
PORTAL_PORT="${PORTAL_PORT:-8080}"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  AGRO-AI Water Intelligence Copilot — Fox Canyon Demo        ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  API:    http://localhost:${API_PORT}                              ║"
echo "║  Portal: http://localhost:${PORTAL_PORT}/fcgma-demo.html           ║"
echo "║                                                              ║"
echo "║  DEMONSTRATION ENVIRONMENT                                   ║"
echo "║  Not an official Fox Canyon reporting system                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found. Please install Python 3.9+."
  exit 1
fi

# Install dependencies if needed
echo "→ Checking dependencies…"
cd "$API_DIR"
if ! python3 -c "import fastapi, uvicorn, reportlab" &>/dev/null 2>&1; then
  echo "→ Installing Python dependencies…"
  pip install -r requirements.txt -q
fi

# Set demo defaults
export DATABASE_URL="${DATABASE_URL:-sqlite:///./fcgma_demo.db}"
export ENABLE_SCHEDULER="${ENABLE_SCHEDULER:-false}"

# Load local environment overrides — Terris LLM credentials, etc.
# This file is git-ignored and never committed.
ENV_LOCAL="${API_DIR}/.env.local"
if [[ -f "${ENV_LOCAL}" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ENV_LOCAL}"
  set +a
  echo "→ Loaded local configuration (.env.local)"
  # Report Terris mode without printing the key
  if [[ -n "${TERRIS_LLM_API_KEY:-}" ]]; then
    echo "→ Terris: Connected Intelligence mode (${TERRIS_LLM_PROVIDER:-anthropic} / ${TERRIS_LLM_MODEL:-default})"
  else
    echo "→ Terris: Structured Safe mode (no LLM key — run scripts/configure_terris_llm.sh to enable)"
  fi
else
  echo "→ Terris: Structured Safe mode (.env.local not found)"
fi

echo "→ Starting API server on port ${API_PORT}…"
echo "→ Demo portal: http://localhost:${PORTAL_PORT}/fcgma-demo.html"
echo ""
echo "Press Ctrl+C to stop."
echo ""

# Start portal static server in background
cd "$PORTAL_DIR"
python3 -m http.server "$PORTAL_PORT" --bind 127.0.0.1 &
PORTAL_PID=$!
echo "→ Portal server started (PID $PORTAL_PID)"

# Start API server (foreground)
cd "$API_DIR"
trap "kill $PORTAL_PID 2>/dev/null; echo ''; echo 'Stopped.'" EXIT
python3 -m uvicorn app.main:app --reload --port "$API_PORT" --host 127.0.0.1
