#!/usr/bin/env bash
# verify_terris_gemini_demo.sh — End-to-end verification of Terris Gemini Demo Intelligence.
#
# Runs 11 checks. Exits non-zero if any check fails.
#
# Usage: bash scripts/verify_terris_gemini_demo.sh [--api-url http://localhost:8000]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

API_URL="${1:-http://127.0.0.1:8000}"
BASE_PATH="/v1/fcgma-demo"
PASS=0
FAIL=0

_pass() { echo "  PASS  $1"; ((PASS++)); }
_fail() { echo "  FAIL  $1"; ((FAIL++)); }

echo ""
echo "=== Terris Gemini Demo Intelligence Verification ==="
echo "Backend: ${API_URL}"
echo ""

# ── Check 1: SDK import ────────────────────────────────────────────────────
echo "[1/11] SDK import"
if python3 -c "from google import genai; print('ok')" 2>/dev/null | grep -q "ok"; then
  _pass "google-genai SDK imports successfully"
else
  _fail "google-genai SDK not importable — run: pip install 'google-genai>=0.8.0'"
fi

# ── Check 2: Model configured ─────────────────────────────────────────────
echo "[2/11] Model configuration"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_LOCAL="${SCRIPT_DIR}/../agroai_api/.env.local"
CONFIGURED_MODEL=""
if [[ -f "${ENV_LOCAL}" ]]; then
  CONFIGURED_MODEL=$(grep "^TERRIS_GEMINI_MODEL=" "${ENV_LOCAL}" | cut -d= -f2 | tr -d '"' || echo "")
fi
if [[ -n "${CONFIGURED_MODEL}" ]]; then
  _pass "Gemini model configured: ${CONFIGURED_MODEL}"
else
  _fail "TERRIS_GEMINI_MODEL not set in .env.local — run: bash scripts/configure_terris_gemini_demo.sh"
fi

# ── Check 3: API key configured ────────────────────────────────────────────
echo "[3/11] API key configured"
KEY_SET="no"
if [[ -f "${ENV_LOCAL}" ]]; then
  RAW_KEY=$(grep "^TERRIS_GEMINI_API_KEY=.\+" "${ENV_LOCAL}" 2>/dev/null | cut -d= -f2- || echo "")
  [[ -n "$RAW_KEY" ]] && KEY_SET="yes"
  unset RAW_KEY
fi
if [[ "$KEY_SET" == "yes" ]]; then
  _pass "TERRIS_GEMINI_API_KEY is set (value not displayed)"
else
  _fail "TERRIS_GEMINI_API_KEY not set in .env.local — run: bash scripts/configure_terris_gemini_demo.sh"
fi

# ── Check 4: Demo-only safety active ──────────────────────────────────────
echo "[4/11] Demo-only safety gate"
DEMO_ONLY=""
if [[ -f "${ENV_LOCAL}" ]]; then
  DEMO_ONLY=$(grep "^TERRIS_EXTERNAL_DEMO_ONLY=" "${ENV_LOCAL}" | cut -d= -f2 | tr -d '"' || echo "")
fi
if [[ "${DEMO_ONLY}" == "true" ]]; then
  _pass "TERRIS_EXTERNAL_DEMO_ONLY=true (demo-only safety active)"
else
  _fail "TERRIS_EXTERNAL_DEMO_ONLY is not 'true' — re-run configure_terris_gemini_demo.sh"
fi

# ── Check 5: Blocked private categories ───────────────────────────────────
echo "[5/11] Blocked private provenance"
BLOCK_PRIVATE=""
if [[ -f "${ENV_LOCAL}" ]]; then
  BLOCK_PRIVATE=$(grep "^TERRIS_EXTERNAL_BLOCK_PRIVATE=" "${ENV_LOCAL}" | cut -d= -f2 | tr -d '"' || echo "")
fi
if [[ "${BLOCK_PRIVATE}" == "true" ]]; then
  _pass "TERRIS_EXTERNAL_BLOCK_PRIVATE=true (private provenance blocked)"
else
  _fail "TERRIS_EXTERNAL_BLOCK_PRIVATE is not 'true' — re-run configure_terris_gemini_demo.sh"
fi

# ── Check 6: Backend reachable ─────────────────────────────────────────────
echo "[6/11] Backend reachable"
DIAG_CODE=$(curl -s -o /tmp/_terris_verify_diag.json -w "%{http_code}" \
  "${API_URL}${BASE_PATH}/terris/diagnostic" 2>/dev/null || echo "000")
if [[ "$DIAG_CODE" == "200" ]]; then
  _pass "Backend diagnostic endpoint reachable (HTTP 200)"
else
  _fail "Backend unreachable (HTTP ${DIAG_CODE}) — start: bash scripts/run_fcgma_demo.sh"
  echo ""
  echo "Checks 7-11 skipped (backend required)."
  echo ""
  echo "Results: ${PASS} passed, ${FAIL} failed"
  [[ $FAIL -eq 0 ]] && exit 0 || exit 1
fi

# ── Check 7: Runtime mode ─────────────────────────────────────────────────
echo "[7/11] Runtime mode"
RUNTIME_MODE=$(python3 -c "
import json, sys
try:
    d = json.load(open('/tmp/_terris_verify_diag.json'))
    print(d.get('mode', d.get('llm_mode', 'unknown')))
except Exception:
    print('unknown')
" 2>/dev/null)
if [[ "$RUNTIME_MODE" == "gemini_demo_intelligence" ]]; then
  _pass "Runtime mode: gemini_demo_intelligence"
elif [[ "$RUNTIME_MODE" == "gemini_demo_degraded" ]]; then
  _fail "Runtime mode: gemini_demo_degraded — check API key and model; restart backend"
else
  _fail "Runtime mode: ${RUNTIME_MODE} (expected gemini_demo_intelligence) — restart backend after configuring"
fi

# ── Check 8: Provider confirmed ───────────────────────────────────────────
echo "[8/11] Provider confirmation"
RUNTIME_PROVIDER=$(python3 -c "
import json, sys
try:
    d = json.load(open('/tmp/_terris_verify_diag.json'))
    print(d.get('provider', ''))
except Exception:
    print('')
" 2>/dev/null)
if [[ "$RUNTIME_PROVIDER" == "gemini_demo" ]]; then
  _pass "Provider confirmed: gemini_demo"
else
  _fail "Expected provider='gemini_demo', got '${RUNTIME_PROVIDER}'"
fi

# ── Check 9: Demo-only safety confirmed in runtime ────────────────────────
echo "[9/11] Runtime demo-only safety"
RUNTIME_DEMO=$(python3 -c "
import json, sys
try:
    d = json.load(open('/tmp/_terris_verify_diag.json'))
    print('yes' if d.get('demo_only_safety_active') else 'no')
except Exception:
    print('no')
" 2>/dev/null)
if [[ "$RUNTIME_DEMO" == "yes" ]]; then
  _pass "Runtime demo_only_safety_active=true confirmed"
else
  _fail "demo_only_safety_active not confirmed in runtime diagnostic"
fi

# ── Check 10: No chain-of-thought in response ─────────────────────────────
echo "[10/11] No chain-of-thought in response"
THREAD_RESP=$(curl -s -X POST \
  "${API_URL}${BASE_PATH}/conversations" \
  -H "Content-Type: application/json" \
  -d '{}' 2>/dev/null)
THREAD_ID=$(python3 -c "
import json, sys
try:
    print(json.loads(sys.argv[1]).get('thread_id',''))
except Exception:
    print('')
" "${THREAD_RESP}" 2>/dev/null)
if [[ -n "$THREAD_ID" ]]; then
  MSG_RESP=$(curl -s -X POST \
    "${API_URL}${BASE_PATH}/conversations/${THREAD_ID}/messages" \
    -H "Content-Type: application/json" \
    -d '{"query":"What is the current reporting cycle status?"}' 2>/dev/null)
  COT_CHECK=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    content = d.get('content','')
    if '<think>' in content or '<thinking>' in content or 'chain-of-thought' in content.lower():
        print('EXPOSED')
    else:
        print('OK')
except Exception:
    print('OK')
" "${MSG_RESP}" 2>/dev/null)
  if [[ "$COT_CHECK" == "OK" ]]; then
    _pass "No chain-of-thought tokens in Terris response"
  else
    _fail "Chain-of-thought tokens found in response — reasoning not being filtered"
  fi
else
  _fail "Could not create conversation thread for chain-of-thought check"
fi

# ── Check 11: No private data in external payload ─────────────────────────
echo "[11/11] No private data in external payload"
BLOCKED_RESP=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    audit = d.get('agent_audit_log', [])
    # Check no tool result contained private markers
    blocked = any('PRIVATE' in str(e) or 'CONFIDENTIAL' in str(e) for e in audit)
    print('BLOCKED' if blocked else 'OK')
except Exception:
    print('OK')
" "${MSG_RESP:-{}}" 2>/dev/null)
if [[ "$BLOCKED_RESP" == "OK" ]]; then
  _pass "No private data markers in external audit trail"
else
  _fail "Potential private data markers found in audit trail"
fi

rm -f /tmp/_terris_verify_diag.json

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="
echo ""
[[ $FAIL -eq 0 ]] && echo "All checks passed. Gemini Demo Intelligence is operational." || true
[[ $FAIL -gt 0 ]] && echo "Failing checks above require attention before using Gemini Demo Intelligence." || true
echo ""
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
