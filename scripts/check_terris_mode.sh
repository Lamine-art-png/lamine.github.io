#!/usr/bin/env bash
# check_terris_mode.sh — Report Terris LLM mode from the running backend.
#
# Prints whether Terris is in Structured Safe mode (no LLM key) or
# Connected Intelligence mode (LLM configured).  NEVER prints the API key.
#
# Usage: bash scripts/check_terris_mode.sh [--api-url http://localhost:8000]
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

API_URL="${1:-http://127.0.0.1:8000}"
BASE_PATH="/v1/fcgma-demo"

echo ""
echo "=== Terris Mode Check ==="
echo "Querying: ${API_URL}${BASE_PATH}/terris/briefing"
echo ""

# Probe the briefing endpoint for llm_mode
HTTP_CODE=$(curl -s -o /tmp/_terris_mode_check.json -w "%{http_code}" \
  "${API_URL}${BASE_PATH}/terris/briefing" 2>/dev/null || echo "000")

if [[ "$HTTP_CODE" == "000" ]]; then
  echo "ERROR: Cannot reach ${API_URL}${BASE_PATH}."
  echo "Start the backend first: bash scripts/run_fcgma_demo.sh"
  echo ""
  exit 1
fi

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "ERROR: Backend returned HTTP ${HTTP_CODE}."
  cat /tmp/_terris_mode_check.json 2>/dev/null || true
  echo ""
  exit 1
fi

LLM_MODE=$(python3 -c "
import json, sys
try:
    d = json.load(open('/tmp/_terris_mode_check.json'))
    print(d.get('llm_mode', 'unknown'))
except Exception as e:
    print('unknown')
" 2>/dev/null)

echo "Terris mode: ${LLM_MODE}"
echo ""

case "$LLM_MODE" in
  connected_intelligence)
    echo "  Status : CONNECTED INTELLIGENCE MODE"
    echo "  Detail : LLM key is configured. Terris will narrate answers using"
    echo "           the LLM, grounded in deterministic backend tool results."
    ;;
  structured_safe)
    echo "  Status : STRUCTURED SAFE MODE"
    echo "  Detail : No LLM key configured. Terris returns deterministic"
    echo "           structured answers without LLM narration."
    echo ""
    echo "  To enable Connected Intelligence Mode:"
    echo "    bash scripts/configure_terris_llm.sh"
    ;;
  *)
    echo "  Status : UNKNOWN (${LLM_MODE})"
    echo "  This may indicate a configuration issue."
    ;;
esac

echo ""

# Check .env.local without printing the key
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_LOCAL="${SCRIPT_DIR}/../agroai_api/.env.local"

if [[ -f "${ENV_LOCAL}" ]]; then
  PROVIDER=$(grep "^TERRIS_LLM_PROVIDER=" "${ENV_LOCAL}" | cut -d= -f2 | tr -d '"' || echo "")
  MODEL=$(grep "^TERRIS_LLM_MODEL=" "${ENV_LOCAL}" | cut -d= -f2 | tr -d '"' || echo "")
  KEY_SET=$(grep -q "^TERRIS_LLM_API_KEY=.\+" "${ENV_LOCAL}" 2>/dev/null && echo "yes" || echo "no")

  if [[ -n "$PROVIDER" ]]; then
    echo "  Provider : ${PROVIDER}"
    echo "  Model    : ${MODEL:-default}"
    echo "  Key set  : ${KEY_SET}"
    echo "  (Key value is never printed)"
  else
    echo "  .env.local present but TERRIS_LLM_PROVIDER not set."
  fi
else
  echo "  .env.local not found — API key not configured locally."
fi

echo ""
rm -f /tmp/_terris_mode_check.json
