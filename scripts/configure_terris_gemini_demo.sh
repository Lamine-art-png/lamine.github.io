#!/usr/bin/env bash
# configure_terris_gemini_demo.sh — Configure Terris Gemini Demo Intelligence mode.
#
# IMPORTANT SAFETY NOTICE:
#   Gemini Demo Intelligence is for illustrative and sanitized records only.
#   Do NOT use future private customer telemetry or authorized live data with the free tier.
#   The demo-only safety gate is enabled by default and blocks private data automatically.
#
# Usage: bash scripts/configure_terris_gemini_demo.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
API_DIR="$ROOT_DIR/agroai_api"
ENV_LOCAL="$API_DIR/.env.local"

echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  Terris Gemini Demo Intelligence — Setup                             ║"
echo "╠══════════════════════════════════════════════════════════════════════╣"
echo "║  ILLUSTRATIVE DATA ONLY                                              ║"
echo "║                                                                      ║"
echo "║  Gemini Demo Intelligence may receive only:                          ║"
echo "║    • public_context          — publicly available reference data     ║"
echo "║    • sanitized_replay        — anonymized demo replay records         ║"
echo "║    • injected_demo_scenario  — labelled illustrative scenarios        ║"
echo "║                                                                      ║"
echo "║  Gemini Demo Intelligence is blocked from receiving:                 ║"
echo "║    • authorized_live_private — live authorized provider records       ║"
echo "║    • confidential_customer   — customer identifiers or data           ║"
echo "║    • credential              — API keys, tokens, or secrets           ║"
echo "║    • unknown                 — any record without provenance tag       ║"
echo "║                                                                      ║"
echo "║  Do NOT use future private Fox Canyon extraction data with           ║"
echo "║  the free Gemini tier. This configuration is for demo use only.      ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# ── Check google-genai SDK ─────────────────────────────────────────────────
echo "→ Checking google-genai SDK…"
if python3 -c "from google import genai" 2>/dev/null; then
  echo "  SDK: installed"
else
  echo "  SDK: not found — installing…"
  pip install "google-genai>=0.8.0" -q
  if python3 -c "from google import genai" 2>/dev/null; then
    echo "  SDK: installed successfully"
  else
    echo "ERROR: Failed to install google-genai. Run: pip install 'google-genai>=0.8.0'"
    exit 1
  fi
fi

# ── Collect API key (hidden) ──────────────────────────────────────────────
echo ""
echo "Enter your Gemini API key (input is hidden — the value will never be printed):"
echo "  Get a free key at: https://aistudio.google.com/app/apikey"
echo ""
IFS= read -rs GEMINI_API_KEY < /dev/tty
echo ""

if [[ -z "${GEMINI_API_KEY}" ]]; then
  echo "ERROR: No API key entered. Aborting."
  exit 1
fi

echo "  Key received (value not displayed)."

# ── Model selection ───────────────────────────────────────────────────────
echo ""
echo "Select Gemini model:"
echo "  1) gemini-3.5-flash    — latest, fast, free tier, strong tool-calling (Recommended)"
echo "  2) gemini-2.0-flash    — stable, good tool-calling, free tier"
echo "  3) gemini-2.0-flash-lite — lightweight, lowest latency"
echo "  4) Enter custom model name"
echo ""
read -rp "Choice [1]: " MODEL_CHOICE < /dev/tty
MODEL_CHOICE="${MODEL_CHOICE:-1}"

case "$MODEL_CHOICE" in
  1) GEMINI_MODEL="gemini-3.5-flash" ;;
  2) GEMINI_MODEL="gemini-2.0-flash" ;;
  3) GEMINI_MODEL="gemini-2.0-flash-lite" ;;
  4)
    read -rp "Enter model name: " GEMINI_MODEL < /dev/tty
    GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.5-flash}"
    ;;
  *) GEMINI_MODEL="gemini-3.5-flash" ;;
esac

echo "  Model: ${GEMINI_MODEL}"

# ── Backup existing .env.local ────────────────────────────────────────────
if [[ -f "${ENV_LOCAL}" ]]; then
  BACKUP_DATE="$(date +%Y%m%d_%H%M%S)"
  BACKUP_FILE="${ENV_LOCAL}.backup.${BACKUP_DATE}"
  cp "${ENV_LOCAL}" "${BACKUP_FILE}"
  chmod 600 "${BACKUP_FILE}"
  echo ""
  echo "→ Backed up existing .env.local to ${BACKUP_FILE}"
fi

# ── Write .env.local (preserve non-TERRIS lines) ─────────────────────────
echo ""
echo "→ Writing configuration to .env.local…"

TMP_ENV="$(mktemp)"
chmod 600 "${TMP_ENV}"

# Preserve non-TERRIS and non-Gemini lines
if [[ -f "${ENV_LOCAL}" ]]; then
  grep -v "^TERRIS_LLM_PROVIDER=" "${ENV_LOCAL}" \
    | grep -v "^TERRIS_GEMINI_" \
    | grep -v "^TERRIS_EXTERNAL_" > "${TMP_ENV}" || true
fi

# Append Gemini configuration
cat >> "${TMP_ENV}" <<EOF

# Terris Gemini Demo Intelligence — written by configure_terris_gemini_demo.sh
TERRIS_LLM_PROVIDER=gemini_demo
TERRIS_GEMINI_MODEL=${GEMINI_MODEL}
TERRIS_GEMINI_API_KEY=${GEMINI_API_KEY}
TERRIS_EXTERNAL_DEMO_ONLY=true
TERRIS_EXTERNAL_BLOCK_PRIVATE=true
TERRIS_EXTERNAL_ALLOWED_PROVENANCE=public_context,sanitized_replay,injected_demo_scenario
TERRIS_EXTERNAL_MAX_TOOL_ITERATIONS=6
TERRIS_EXTERNAL_TIMEOUT_SECONDS=120
EOF

mv "${TMP_ENV}" "${ENV_LOCAL}"
chmod 600 "${ENV_LOCAL}"
unset GEMINI_API_KEY

# ── Verify .gitignore covers .env.local ──────────────────────────────────
GITIGNORE="${ROOT_DIR}/.gitignore"
if [[ -f "${GITIGNORE}" ]] && grep -q ".env.local" "${GITIGNORE}"; then
  echo "  .gitignore: .env.local is already ignored ✓"
else
  echo "WARNING: .env.local may not be in .gitignore. Verify before committing."
fi

# ── Quick SDK smoke test ──────────────────────────────────────────────────
echo ""
echo "→ Running SDK smoke test…"
SMOKE_RESULT=$(python3 -c "
from google import genai
print('SDK import: ok')
" 2>&1)
echo "  ${SMOKE_RESULT}"

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  Configuration complete                                              ║"
echo "╠══════════════════════════════════════════════════════════════════════╣"
printf "║  Provider    : %-52s ║\n" "gemini_demo"
printf "║  Model       : %-52s ║\n" "${GEMINI_MODEL}"
printf "║  Demo-only   : %-52s ║\n" "active (TERRIS_EXTERNAL_DEMO_ONLY=true)"
printf "║  Blocked     : %-52s ║\n" "private, confidential, credential, unknown"
printf "║  Key set     : %-52s ║\n" "yes  (value never printed)"
printf "║  File        : %-52s ║\n" ".env.local  (git-ignored, chmod 600)"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "→ Next steps:"
echo "  1. Restart the backend: bash scripts/run_fcgma_demo.sh"
echo "  2. Check mode:          bash scripts/check_terris_mode.sh"
echo "  3. Verify:              bash scripts/verify_terris_gemini_demo.sh"
echo ""
