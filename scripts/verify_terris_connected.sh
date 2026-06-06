#!/usr/bin/env bash
# verify_terris_connected.sh — End-to-end verification of Terris Connected Intelligence.
#
# Sends a test query to Terris and confirms the response shows
# connected_intelligence mode, not structured_safe.
#
# Prerequisites:
#   1. Backend running: bash scripts/run_fcgma_demo.sh
#   2. LLM configured: bash scripts/configure_terris_llm.sh
#
# Usage: bash scripts/verify_terris_connected.sh [--api-url http://localhost:8000]
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

API_URL="${1:-http://127.0.0.1:8000}"
BASE_PATH="/v1/fcgma-demo"
TMP_THREAD="/tmp/_terris_verify_thread.json"
TMP_MSG="/tmp/_terris_verify_msg.json"
TMP_POLL="/tmp/_terris_verify_poll.json"

echo ""
echo "=== Terris Connected Intelligence Verification ==="
echo "API: ${API_URL}${BASE_PATH}"
echo ""

# ── Step 1: Check diagnostic endpoint ────────────────────────────────────────
echo "Step 1: Checking runtime configuration…"
DIAG_CODE=$(curl -s -o /tmp/_terris_verify_diag.json -w "%{http_code}" \
  "${API_URL}${BASE_PATH}/terris/diagnostic" 2>/dev/null || echo "000")

if [[ "$DIAG_CODE" == "000" ]]; then
  echo "FAIL: Cannot reach backend at ${API_URL}"
  echo "      Start the backend: bash scripts/run_fcgma_demo.sh"
  rm -f /tmp/_terris_verify_diag.json
  exit 1
fi

RUNTIME_MODE=$(python3 -c "
import json
try:
    d = json.load(open('/tmp/_terris_verify_diag.json'))
    print(d.get('mode', 'unknown'))
except Exception:
    print('unknown')
" 2>/dev/null)
rm -f /tmp/_terris_verify_diag.json

if [[ "$RUNTIME_MODE" != "connected_intelligence" ]]; then
  echo "FAIL: Backend is in '${RUNTIME_MODE}' mode, not connected_intelligence."
  echo ""
  echo "  Check current mode:  bash scripts/check_terris_mode.sh"
  echo "  Configure LLM:       bash scripts/configure_terris_llm.sh"
  echo "  Restart backend:     bash scripts/run_fcgma_demo.sh"
  exit 1
fi

echo "  OK — Runtime mode: connected_intelligence"

# ── Step 2: Create conversation thread ───────────────────────────────────────
echo ""
echo "Step 2: Creating conversation thread…"
THREAD_CODE=$(curl -s -o "${TMP_THREAD}" -w "%{http_code}" \
  -X POST "${API_URL}${BASE_PATH}/terris/conversation" \
  -H "Content-Type: application/json" \
  -d '{"title":"verify-connected-test"}' 2>/dev/null || echo "000")

if [[ "$THREAD_CODE" != "200" ]]; then
  echo "FAIL: Could not create conversation thread (HTTP ${THREAD_CODE})"
  rm -f "${TMP_THREAD}"
  exit 1
fi

THREAD_ID=$(python3 -c "
import json
try:
    d = json.load(open('${TMP_THREAD}'))
    print(d.get('thread_id', ''))
except Exception:
    print('')
" 2>/dev/null)
rm -f "${TMP_THREAD}"

if [[ -z "$THREAD_ID" ]]; then
  echo "FAIL: thread_id missing from response"
  exit 1
fi

echo "  OK — Thread: ${THREAD_ID}"

# ── Step 3: Start async message job ──────────────────────────────────────────
echo ""
echo "Step 3: Sending test query to Terris…"
JOB_CODE=$(curl -s -o "${TMP_MSG}" -w "%{http_code}" \
  -X POST "${API_URL}${BASE_PATH}/terris/conversation/${THREAD_ID}/message-start" \
  -H "Content-Type: application/json" \
  -d '{"query":"Where does the 2026-Q1 reporting cycle stand?"}' 2>/dev/null || echo "000")

if [[ "$JOB_CODE" != "200" ]]; then
  echo "FAIL: Could not start message job (HTTP ${JOB_CODE})"
  rm -f "${TMP_MSG}"
  exit 1
fi

JOB_ID=$(python3 -c "
import json
try:
    d = json.load(open('${TMP_MSG}'))
    print(d.get('job_id', ''))
except Exception:
    print('')
" 2>/dev/null)
rm -f "${TMP_MSG}"

if [[ -z "$JOB_ID" ]]; then
  echo "FAIL: job_id missing from response"
  exit 1
fi

echo "  OK — Job: ${JOB_ID}"
echo "  Waiting for response (up to 30 seconds)…"

# ── Step 4: Poll until complete ───────────────────────────────────────────────
RESULT_MODE=""
RESULT_CONTENT=""
for i in $(seq 1 60); do
  sleep 0.5
  POLL_CODE=$(curl -s -o "${TMP_POLL}" -w "%{http_code}" \
    "${API_URL}${BASE_PATH}/terris/job/${JOB_ID}" 2>/dev/null || echo "000")

  if [[ "$POLL_CODE" != "200" ]]; then
    continue
  fi

  JOB_STATUS=$(python3 -c "
import json
try:
    d = json.load(open('${TMP_POLL}'))
    print(d.get('status',''))
except Exception:
    print('')
" 2>/dev/null)

  if [[ "$JOB_STATUS" == "complete" ]]; then
    RESULT_MODE=$(python3 -c "
import json
try:
    d = json.load(open('${TMP_POLL}'))
    r = d.get('result', {})
    print(r.get('llm_mode', ''))
except Exception:
    print('')
" 2>/dev/null)

    RESULT_CONTENT=$(python3 -c "
import json
try:
    d = json.load(open('${TMP_POLL}'))
    r = d.get('result', {})
    content = r.get('content','')
    print(content[:120].replace('\n',' '))
except Exception:
    print('')
" 2>/dev/null)
    break
  fi

  if [[ "$JOB_STATUS" == "error" ]]; then
    ERROR=$(python3 -c "
import json
try:
    d = json.load(open('${TMP_POLL}'))
    print(d.get('error','unknown error'))
except Exception:
    print('unknown error')
" 2>/dev/null)
    rm -f "${TMP_POLL}"
    echo "FAIL: Job error: ${ERROR}"
    exit 1
  fi
done

rm -f "${TMP_POLL}"

# ── Step 5: Assert connected_intelligence mode ────────────────────────────────
echo ""
echo "Step 4: Verifying response mode…"

if [[ "$RESULT_MODE" == "connected_intelligence" ]]; then
  echo "  OK — Response mode: connected_intelligence"
  echo ""
  echo "  Response preview:"
  echo "    \"${RESULT_CONTENT}…\""
  echo ""
  echo "=== VERIFICATION PASSED ==="
  echo ""
  echo "Terris is operating in Connected Intelligence mode."
  echo "LLM narration is active and grounded in deterministic backend tools."
  echo ""
  exit 0
elif [[ -z "$RESULT_MODE" ]]; then
  echo "FAIL: No response received within 30 seconds."
  exit 1
else
  echo "FAIL: Response mode is '${RESULT_MODE}', expected connected_intelligence."
  echo ""
  echo "  The backend is running but Terris used Structured Safe mode for this response."
  echo "  Check: bash scripts/check_terris_mode.sh"
  exit 1
fi
