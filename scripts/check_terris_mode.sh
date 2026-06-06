#!/usr/bin/env bash
# check_terris_mode.sh — Report Terris LLM mode from the running backend.
#
# Distinguishes five states:
#   connected_intelligence — LLM key loaded and active
#   structured_safe        — No LLM key in the running process
#   restart_required       — Key set in .env.local but backend not yet reloaded
#   config_invalid         — .env.local exists but contains an invalid configuration
#   request_failed         — Cannot reach the backend
#
# Usage: bash scripts/check_terris_mode.sh [--api-url http://localhost:8000]
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

API_URL="${1:-http://127.0.0.1:8000}"
BASE_PATH="/v1/fcgma-demo"
DIAG_URL="${API_URL}${BASE_PATH}/terris/diagnostic"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_LOCAL="${SCRIPT_DIR}/../agroai_api/.env.local"
TMP_DIAG="/tmp/_terris_diag_check.json"

echo ""
echo "=== Terris Mode Check ==="
echo "Querying: ${DIAG_URL}"
echo ""

# ── Query diagnostic endpoint ─────────────────────────────────────────────────
HTTP_CODE=$(curl -s -o "${TMP_DIAG}" -w "%{http_code}" \
  "${DIAG_URL}" 2>/dev/null || echo "000")

if [[ "$HTTP_CODE" == "000" ]]; then
  echo "STATUS : request_failed"
  echo "DETAIL : Cannot reach ${API_URL}${BASE_PATH}"
  echo "         Start the backend first: bash scripts/run_fcgma_demo.sh"
  echo ""
  rm -f "${TMP_DIAG}"
  exit 1
fi

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "STATUS : request_failed"
  echo "DETAIL : Backend returned HTTP ${HTTP_CODE}"
  cat "${TMP_DIAG}" 2>/dev/null || true
  echo ""
  rm -f "${TMP_DIAG}"
  exit 1
fi

# Parse runtime mode from the diagnostic endpoint
RUNTIME_MODE=$(python3 -c "
import json, sys
try:
    d = json.load(open('${TMP_DIAG}'))
    print(d.get('mode', d.get('llm_mode', 'unknown')))
except Exception:
    print('unknown')
" 2>/dev/null)

RUNTIME_PROVIDER=$(python3 -c "
import json, sys
try:
    d = json.load(open('${TMP_DIAG}'))
    print(d.get('provider', ''))
except Exception:
    print('')
" 2>/dev/null)

RUNTIME_MODEL=$(python3 -c "
import json, sys
try:
    d = json.load(open('${TMP_DIAG}'))
    print(d.get('model', ''))
except Exception:
    print('')
" 2>/dev/null)

RUNTIME_EFFORT=$(python3 -c "
import json, sys
try:
    d = json.load(open('${TMP_DIAG}'))
    print(d.get('reasoning_effort', ''))
except Exception:
    print('')
" 2>/dev/null)

RUNTIME_KEY_SET=$(python3 -c "
import json, sys
try:
    d = json.load(open('${TMP_DIAG}'))
    print('yes' if d.get('key_configured') else 'no')
except Exception:
    print('no')
" 2>/dev/null)

rm -f "${TMP_DIAG}"

# ── Check .env.local for configured key ──────────────────────────────────────
LOCAL_KEY_SET="no"
LOCAL_PROVIDER=""
LOCAL_MODEL=""
LOCAL_EFFORT=""
LOCAL_VALID="yes"

if [[ -f "${ENV_LOCAL}" ]]; then
  LOCAL_PROVIDER=$(grep "^TERRIS_LLM_PROVIDER=" "${ENV_LOCAL}" | cut -d= -f2 | tr -d '"' || echo "")
  LOCAL_MODEL=$(grep "^TERRIS_LLM_MODEL=" "${ENV_LOCAL}" | cut -d= -f2 | tr -d '"' || echo "")
  LOCAL_EFFORT=$(grep "^TERRIS_LLM_REASONING_EFFORT=" "${ENV_LOCAL}" | cut -d= -f2 | tr -d '"' || echo "")
  RAW_KEY=$(grep "^TERRIS_LLM_API_KEY=.\+" "${ENV_LOCAL}" 2>/dev/null | cut -d= -f2- || echo "")
  [[ -n "$RAW_KEY" ]] && LOCAL_KEY_SET="yes"

  # Validate model — reject numeric-only
  if [[ "$LOCAL_MODEL" =~ ^[0-9]+$ ]]; then
    LOCAL_VALID="no"
    echo "WARNING: .env.local contains an invalid numeric-only model: '${LOCAL_MODEL}'"
    echo "         Run: bash scripts/configure_terris_llm.sh  to fix this."
    echo ""
  fi
  unset RAW_KEY
fi

# ── Determine effective state ─────────────────────────────────────────────────
if [[ "$RUNTIME_MODE" == "connected_intelligence" ]]; then
  EFFECTIVE_STATE="connected_intelligence"
elif [[ "$RUNTIME_MODE" == "structured_safe" && "$LOCAL_KEY_SET" == "yes" && "$LOCAL_VALID" == "yes" ]]; then
  EFFECTIVE_STATE="restart_required"
elif [[ "$LOCAL_VALID" == "no" ]]; then
  EFFECTIVE_STATE="config_invalid"
else
  EFFECTIVE_STATE="structured_safe"
fi

echo "Runtime mode   : ${RUNTIME_MODE}"
echo "Effective state: ${EFFECTIVE_STATE}"
echo ""

case "$EFFECTIVE_STATE" in
  connected_intelligence)
    echo "  Status  : CONNECTED INTELLIGENCE MODE"
    echo "  Detail  : LLM key is active in the running backend."
    echo "            Terris narrates deterministic tool results using the LLM."
    echo "  Provider: ${RUNTIME_PROVIDER}"
    echo "  Model   : ${RUNTIME_MODEL}"
    echo "  Effort  : ${RUNTIME_EFFORT}"
    ;;
  restart_required)
    echo "  Status  : RESTART REQUIRED"
    echo "  Detail  : A key is set in .env.local but the running backend"
    echo "            has not loaded it yet (still showing Structured Safe mode)."
    echo ""
    echo "  Fix: Stop the backend and restart:"
    echo "    bash scripts/run_fcgma_demo.sh"
    echo ""
    echo "  .env.local settings:"
    echo "    Provider : ${LOCAL_PROVIDER:-not set}"
    echo "    Model    : ${LOCAL_MODEL:-not set}"
    echo "    Effort   : ${LOCAL_EFFORT:-xhigh}"
    echo "    Key set  : yes  (value never printed)"
    ;;
  config_invalid)
    echo "  Status  : CONFIG INVALID"
    echo "  Detail  : .env.local contains an invalid configuration (e.g., numeric model ID)."
    echo ""
    echo "  Fix: Re-run the configuration wizard:"
    echo "    bash scripts/configure_terris_llm.sh"
    ;;
  structured_safe)
    echo "  Status  : STRUCTURED SAFE MODE"
    echo "  Detail  : No LLM key configured. Terris returns deterministic"
    echo "            structured answers without LLM narration."
    echo ""
    echo "  To enable Connected Intelligence Mode:"
    echo "    bash scripts/configure_terris_llm.sh"
    ;;
  *)
    echo "  Status  : UNKNOWN (${EFFECTIVE_STATE})"
    echo "  This may indicate a configuration issue."
    ;;
esac

echo ""
