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

RUNTIME_SDK_AVAIL=$(python3 -c "
import json, sys
try:
    d = json.load(open('${TMP_DIAG}'))
    print('yes' if d.get('sdk_available') else 'no')
except Exception:
    print('no')
" 2>/dev/null)

RUNTIME_LAST_ERR=$(python3 -c "
import json, sys
try:
    d = json.load(open('${TMP_DIAG}'))
    err = d.get('last_error_redacted') or ''
    print(err[:80])
except Exception:
    print('')
" 2>/dev/null)

# ── Parse Ollama-specific health fields ──────────────────────────────────────
RUNTIME_OLLAMA_REACHABLE=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print('yes' if d.get('ollama_reachable') else 'no')
except Exception:
    print('no')
" "${TMP_DIAG}" 2>/dev/null || echo "no")

RUNTIME_OLLAMA_LOOPBACK=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print('yes' if d.get('ollama_loopback_only') else 'no')
except Exception:
    print('unknown')
" "${TMP_DIAG}" 2>/dev/null || echo "unknown")

RUNTIME_MODEL_INSTALLED=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print('yes' if d.get('model_installed') else 'no')
except Exception:
    print('unknown')
" "${TMP_DIAG}" 2>/dev/null || echo "unknown")

RUNTIME_CLOUD_KEY_REQUIRED=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print('yes' if d.get('cloud_key_required') else 'no')
except Exception:
    print('unknown')
" "${TMP_DIAG}" 2>/dev/null || echo "unknown")

# ── Parse Gemini Demo-specific health fields ──────────────────────────────────
RUNTIME_DEMO_ONLY=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print('yes' if d.get('demo_only_safety_active') else 'no')
except Exception:
    print('no')
" "${TMP_DIAG}" 2>/dev/null || echo "no")

RUNTIME_BLOCK_PRIVATE=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print('yes' if d.get('blocked_private_provenance') else 'no')
except Exception:
    print('no')
" "${TMP_DIAG}" 2>/dev/null || echo "no")

RUNTIME_ALLOWED_PROV=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get('allowed_provenance', ''))
except Exception:
    print('')
" "${TMP_DIAG}" 2>/dev/null || echo "")

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
if [[ "$RUNTIME_MODE" == "gemini_demo_intelligence" ]]; then
  EFFECTIVE_STATE="gemini_demo_intelligence"
elif [[ "$RUNTIME_MODE" == "gemini_demo_degraded" ]]; then
  EFFECTIVE_STATE="gemini_demo_degraded"
elif [[ "$RUNTIME_MODE" == "local_intelligence" ]]; then
  EFFECTIVE_STATE="local_intelligence"
elif [[ "$RUNTIME_MODE" == "local_degraded" ]]; then
  EFFECTIVE_STATE="local_degraded"
elif [[ "$RUNTIME_MODE" == "connected_intelligence" ]]; then
  EFFECTIVE_STATE="connected_intelligence"
elif [[ "$RUNTIME_MODE" == "connected_degraded" ]]; then
  EFFECTIVE_STATE="connected_degraded"
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
  gemini_demo_intelligence)
    echo "  Status  : GEMINI DEMO INTELLIGENCE MODE"
    echo "  Detail  : Gemini free-tier active. Illustrative and sanitized data only."
    echo "            Terris uses Google Gemini backed by deterministic AGRO-AI tools."
    echo "            Demo-only safety gate is active — private data never leaves this server."
    echo "  Provider: gemini_demo"
    echo "  Model   : ${RUNTIME_MODEL}"
    echo "  Demo-only safety    : ${RUNTIME_DEMO_ONLY}"
    echo "  Private data blocked: ${RUNTIME_BLOCK_PRIVATE}"
    [[ -n "$RUNTIME_ALLOWED_PROV" ]] && echo "  Allowed provenance  : ${RUNTIME_ALLOWED_PROV}"
    echo "  SDK     : available"
    ;;
  gemini_demo_degraded)
    echo "  Status  : GEMINI DEMO DEGRADED"
    echo "  Detail  : Gemini is configured but the last call failed."
    echo "            Terris is using deterministic structured fallback."
    echo "  Provider: gemini_demo"
    echo "  Model   : ${RUNTIME_MODEL}"
    [[ -n "$RUNTIME_LAST_ERR" ]] && echo "  Last err: ${RUNTIME_LAST_ERR}"
    echo ""
    echo "  Fix options:"
    echo "    - Verify API key:  bash scripts/configure_terris_gemini_demo.sh"
    echo "    - Check rate limit: free tier allows 15 RPM / 1 million TPD"
    echo "    - Restart backend: bash scripts/run_fcgma_demo.sh"
    echo "    - Verify mode:     bash scripts/verify_terris_gemini_demo.sh"
    ;;
  local_intelligence)
    echo "  Status  : LOCAL INTELLIGENCE MODE"
    echo "  Detail  : Ollama running, model installed, loopback-only, tool-calling active."
    echo "            Terris uses a local Meta Llama model backed by deterministic AGRO-AI tools."
    echo "            Zero per-token cost. No cloud key required. No external inference."
    echo "  Provider: ollama"
    echo "  Model   : ${RUNTIME_MODEL}"
    echo "  Reachable : ${RUNTIME_OLLAMA_REACHABLE}"
    echo "  Loopback  : ${RUNTIME_OLLAMA_LOOPBACK}"
    echo "  Model OK  : ${RUNTIME_MODEL_INSTALLED}"
    echo "  Cloud key : ${RUNTIME_CLOUD_KEY_REQUIRED}"
    ;;
  local_degraded)
    echo "  Status  : LOCAL DEGRADED"
    echo "  Detail  : Ollama is configured but not fully operational."
    echo "            Terris is using deterministic structured fallback."
    echo "  Provider  : ollama"
    echo "  Model     : ${RUNTIME_MODEL}"
    echo "  Reachable : ${RUNTIME_OLLAMA_REACHABLE}"
    echo "  Model OK  : ${RUNTIME_MODEL_INSTALLED}"
    [[ -n "$RUNTIME_LAST_ERR" ]] && echo "  Last err  : ${RUNTIME_LAST_ERR}"
    echo ""
    echo "  Fix options:"
    if [[ "${RUNTIME_OLLAMA_REACHABLE}" == "no" ]]; then
      echo "    - Start Ollama:    OLLAMA_HOST=127.0.0.1 ollama serve"
    fi
    if [[ "${RUNTIME_MODEL_INSTALLED}" == "no" ]]; then
      echo "    - Pull model:      ollama pull ${RUNTIME_MODEL}"
    fi
    echo "    - Re-configure:    bash scripts/configure_terris_local.sh"
    echo "    - Restart backend: bash scripts/run_fcgma_demo.sh"
    ;;
  connected_intelligence)
    echo "  Status  : CONNECTED INTELLIGENCE MODE"
    echo "  Detail  : SDK active, key loaded, provider check passed."
    echo "            Terris uses a real reasoning-capable LLM backed by deterministic tools."
    echo "  Provider: ${RUNTIME_PROVIDER}"
    echo "  Model   : ${RUNTIME_MODEL}"
    echo "  Effort  : ${RUNTIME_EFFORT}"
    echo "  SDK     : available"
    ;;
  connected_degraded)
    echo "  Status  : CONNECTED DEGRADED"
    echo "  Detail  : Configuration exists but the last provider call failed."
    echo "            Terris is using deterministic fallback."
    echo "  Provider: ${RUNTIME_PROVIDER}"
    echo "  Model   : ${RUNTIME_MODEL}"
    echo "  SDK     : ${RUNTIME_SDK_AVAIL}"
    [[ -n "$RUNTIME_LAST_ERR" ]] && echo "  Last err: ${RUNTIME_LAST_ERR}"
    echo ""
    echo "  Fix options:"
    echo "    - Verify API key:  bash scripts/configure_terris_llm.sh"
    echo "    - Install SDK:     pip install openai>=1.54.0 anthropic>=0.39.0"
    echo "    - Restart backend: bash scripts/run_fcgma_demo.sh"
    echo "    - Use local mode:  bash scripts/configure_terris_local.sh"
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
    echo "    bash scripts/configure_terris_local.sh   (for Ollama local)"
    echo "    bash scripts/configure_terris_llm.sh     (for paid providers)"
    ;;
  structured_safe)
    echo "  Status  : STRUCTURED SAFE MODE"
    echo "  Detail  : No LLM configured. Terris returns deterministic"
    echo "            structured answers without LLM narration."
    echo ""
    echo "  To enable Local Intelligence Mode (free, recommended for demo):"
    echo "    bash scripts/configure_terris_local.sh"
    echo ""
    echo "  To enable Connected Intelligence Mode (paid API required):"
    echo "    bash scripts/configure_terris_llm.sh"
    ;;
  *)
    echo "  Status  : UNKNOWN (${EFFECTIVE_STATE})"
    echo "  This may indicate a configuration issue."
    ;;
esac

echo ""
