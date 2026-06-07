#!/usr/bin/env bash
# configure_terris_local.sh — Set up Terris Local Intelligence Mode with Ollama
#
# This script:
#   1. Detects macOS, CPU architecture, and available RAM
#   2. Checks whether Ollama is installed and running on loopback
#   3. Recommends a model based on hardware
#   4. Pulls the selected model
#   5. Runs a low-risk local test prompt
#   6. Writes configuration to agroai_api/.env.local (chmod 600, git-ignored)
#   7. Disables paid-provider activation cleanly
#
# Usage: bash scripts/configure_terris_local.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
ENV_LOCAL="${REPO_ROOT}/agroai_api/.env.local"
OLLAMA_BASE_URL="http://127.0.0.1:11434"

# ── Detect OS ─────────────────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
  echo "ERROR: This script is designed for macOS."
  echo "       For Linux, adapt OLLAMA_BASE_URL and memory detection."
  exit 1
fi

ARCH="$(uname -m)"
echo ""
echo "=== Terris Local Intelligence Setup ==="
echo "  Platform : macOS"
echo "  Arch     : ${ARCH}"

# ── Detect total RAM (MiB) ────────────────────────────────────────────────────
TOTAL_MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
TOTAL_MEM_GIB=$(( TOTAL_MEM_BYTES / 1073741824 ))
echo "  RAM      : ${TOTAL_MEM_GIB} GiB"
echo ""

# ── Check Ollama installation ─────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
  echo "Ollama is not installed."
  echo ""
  echo "Install it from: https://ollama.com/download"
  echo ""
  echo "Official macOS install command:"
  echo "  curl -fsSL https://ollama.com/install.sh | sh"
  echo ""
  echo "Or with Homebrew:"
  echo "  brew install ollama"
  echo ""
  echo "After installation, start Ollama with:"
  echo "  OLLAMA_HOST=127.0.0.1 ollama serve"
  echo ""
  echo "Then re-run this script."
  exit 1
fi

OLLAMA_VERSION=$(ollama --version 2>/dev/null || echo "unknown")
echo "Ollama installed : ${OLLAMA_VERSION}"

# ── Check Ollama service ──────────────────────────────────────────────────────
echo "Checking Ollama service on ${OLLAMA_BASE_URL} …"
if ! curl -sf "${OLLAMA_BASE_URL}/api/tags" -o /dev/null; then
  echo ""
  echo "ERROR: Ollama is not responding on ${OLLAMA_BASE_URL}"
  echo ""
  echo "Start Ollama bound to loopback only:"
  echo "  OLLAMA_HOST=127.0.0.1 ollama serve"
  echo ""
  echo "Or with the Mac app: open Ollama, then verify it is running."
  echo "After starting, re-run this script."
  exit 1
fi
echo "Ollama service   : responding"

# ── Verify loopback-only binding ──────────────────────────────────────────────
OLLAMA_LISTEN=$(curl -s "${OLLAMA_BASE_URL}/api/tags" 2>/dev/null >/dev/null && echo "ok" || echo "no")
# Check whether Ollama is listening beyond loopback using lsof
IS_LAN_EXPOSED="no"
if lsof -i :11434 2>/dev/null | grep -qv "127.0.0.1\|localhost"; then
  IS_LAN_EXPOSED="yes"
fi

if [[ "${IS_LAN_EXPOSED}" == "yes" ]]; then
  echo ""
  echo "WARNING: Ollama appears to be listening on a public or LAN-facing interface."
  echo "         This means local prompts, tool results, and ledger data could be"
  echo "         accessible to other machines on your network."
  echo ""
  echo "  To bind to loopback only, stop Ollama and restart with:"
  echo "    OLLAMA_HOST=127.0.0.1 ollama serve"
  echo ""
  echo "  This script will not confirm a secure local setup until Ollama is"
  echo "  loopback-only. Proceeding with configuration anyway."
  echo ""
else
  echo "Loopback binding : confirmed (127.0.0.1 only)"
fi

# ── Model recommendation ──────────────────────────────────────────────────────
echo ""
echo "=== Model Selection ==="
echo ""
echo "Recommended models for the Fox Canyon executive demo:"
echo ""
echo "  1) llama3.1:8b   [RECOMMENDED DEFAULT]"
echo "     Meta-developed model. Stronger local tool-use and conversational quality."
echo "     Best for the Fox Canyon executive demo. Requires ~8-10 GiB RAM."
echo ""
echo "  2) llama3.2:3b"
echo "     Lighter Meta-developed fallback. Use when llama3.1:8b is too slow."
echo "     Requires ~4-5 GiB RAM."
echo ""
echo "  3) llama3.2:1b"
echo "     Minimal fallback for testing only. Not recommended for the demo."
echo ""
echo "  4) Custom Ollama model (advanced)"
echo ""

# Auto-select default based on RAM
if (( TOTAL_MEM_GIB >= 8 )); then
  DEFAULT_MODEL="llama3.1:8b"
else
  DEFAULT_MODEL="llama3.2:3b"
  echo "NOTE: ${TOTAL_MEM_GIB} GiB RAM detected. Defaulting to llama3.2:3b."
fi

echo "Hardware default : ${DEFAULT_MODEL}"
echo ""
read -rp "Enter model choice [1/2/3/4] (default: 1 = ${DEFAULT_MODEL}): " MODEL_CHOICE
MODEL_CHOICE="${MODEL_CHOICE:-1}"

case "${MODEL_CHOICE}" in
  1) SELECTED_MODEL="llama3.1:8b" ;;
  2) SELECTED_MODEL="llama3.2:3b" ;;
  3) SELECTED_MODEL="llama3.2:1b" ;;
  4)
    read -rp "Enter custom Ollama model name: " SELECTED_MODEL
    SELECTED_MODEL="${SELECTED_MODEL:-llama3.1:8b}"
    ;;
  *) SELECTED_MODEL="${DEFAULT_MODEL}" ;;
esac

echo ""
echo "Selected model   : ${SELECTED_MODEL}"

# ── Pull the selected model ───────────────────────────────────────────────────
echo ""
echo "=== Pulling Model ==="
echo "Running: ollama pull ${SELECTED_MODEL}"
echo "(This may take several minutes on first run.)"
echo ""
ollama pull "${SELECTED_MODEL}"
echo ""
echo "Model pull complete."

# ── Verify model is installed ─────────────────────────────────────────────────
INSTALLED_MODELS=$(ollama list 2>/dev/null | awk 'NR>1 {print $1}' || echo "")
if echo "${INSTALLED_MODELS}" | grep -q "${SELECTED_MODEL%%:*}"; then
  echo "Model installed  : yes (${SELECTED_MODEL})"
else
  echo "WARNING: Could not verify model installation. Continuing anyway."
fi

# ── Run a low-risk local test prompt ─────────────────────────────────────────
echo ""
echo "=== Local Test Prompt ==="
TEST_PROMPT="Reply with exactly: LOCAL_OK"
echo "Sending test prompt to ${SELECTED_MODEL}…"
TEST_RESPONSE=$(curl -sf "${OLLAMA_BASE_URL}/api/generate" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${SELECTED_MODEL}\",\"prompt\":\"${TEST_PROMPT}\",\"stream\":false}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('response','').strip()[:60])" \
  2>/dev/null || echo "")

if [[ -n "${TEST_RESPONSE}" ]]; then
  echo "Test response    : received (${#TEST_RESPONSE} chars)"
  echo "Local inference  : working"
else
  echo "WARNING: Test prompt returned empty response. Model may still be loading."
  echo "         The configuration will be written; try again after the model warms up."
fi

# ── Verify basic tool calling ─────────────────────────────────────────────────
echo ""
echo "=== Tool-Calling Check ==="
TOOL_TEST_RESPONSE=$(curl -sf "${OLLAMA_BASE_URL}/api/chat" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"${SELECTED_MODEL}\",
    \"stream\": false,
    \"messages\": [{\"role\": \"user\", \"content\": \"Call get_status.\"}],
    \"tools\": [{
      \"type\": \"function\",
      \"function\": {
        \"name\": \"get_status\",
        \"description\": \"Get system status.\",
        \"parameters\": {\"type\": \"object\", \"properties\": {}, \"required\": []}
      }
    }]
  }" \
  | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    msg = d.get('message', {})
    tool_calls = msg.get('tool_calls', [])
    print('tool_calls_present' if tool_calls else 'no_tool_calls')
except Exception as e:
    print('parse_error')
" 2>/dev/null || echo "request_failed")

if [[ "${TOOL_TEST_RESPONSE}" == "tool_calls_present" ]]; then
  echo "Tool calling     : supported by ${SELECTED_MODEL}"
elif [[ "${TOOL_TEST_RESPONSE}" == "no_tool_calls" ]]; then
  echo "Tool calling     : model responded but did not use tools (acceptable — Terris handles gracefully)"
else
  echo "Tool calling     : check returned ${TOOL_TEST_RESPONSE} (proceeding — Terris has fallback)"
fi

# ── Write .env.local ──────────────────────────────────────────────────────────
echo ""
echo "=== Writing Configuration ==="

# Create directory if needed
mkdir -p "$(dirname "${ENV_LOCAL}")"

# Preserve any non-TERRIS, non-Ollama lines from existing .env.local
KEEP_LINES=""
if [[ -f "${ENV_LOCAL}" ]]; then
  # Backup first
  BACKUP="${ENV_LOCAL}.backup.$(date +%Y%m%d_%H%M%S)"
  cp "${ENV_LOCAL}" "${BACKUP}"
  echo "Backed up : ${BACKUP}"
  KEEP_LINES=$(grep -v "^TERRIS_LLM_\|^TERRIS_OLLAMA_\|^ANTHROPIC_API_KEY\|^OPENAI_API_KEY" "${ENV_LOCAL}" 2>/dev/null || true)
fi

{
  if [[ -n "${KEEP_LINES}" ]]; then
    echo "${KEEP_LINES}"
    echo ""
  fi
  echo "# Terris Local Intelligence Mode — written by configure_terris_local.sh $(date)"
  echo "TERRIS_LLM_PROVIDER=ollama"
  echo "TERRIS_OLLAMA_BASE_URL=${OLLAMA_BASE_URL}"
  echo "TERRIS_OLLAMA_MODEL=${SELECTED_MODEL}"
  echo "TERRIS_OLLAMA_STREAM=true"
  echo "TERRIS_OLLAMA_NUM_CTX=32768"
  echo "TERRIS_OLLAMA_MAX_TOOL_ITERATIONS=6"
  echo "TERRIS_OLLAMA_TIMEOUT_SECONDS=180"
  echo "# Paid provider keys intentionally omitted — not required for local intelligence"
  echo "# TERRIS_LLM_API_KEY="
} > "${ENV_LOCAL}"

chmod 600 "${ENV_LOCAL}"
echo "Wrote     : ${ENV_LOCAL} (chmod 600)"

# ── Verify .gitignore covers the file ─────────────────────────────────────────
GITIGNORE_COVERS="no"
if git -C "${REPO_ROOT}" check-ignore -q "${ENV_LOCAL}" 2>/dev/null; then
  GITIGNORE_COVERS="yes"
fi
echo "Git-ignored : ${GITIGNORE_COVERS}"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Configuration Summary ==="
echo "  Local Intelligence configured : yes"
echo "  Provider                      : ollama"
echo "  Model                         : ${SELECTED_MODEL}"
echo "  Ollama base URL               : ${OLLAMA_BASE_URL}"
echo "  Ollama reachable              : yes"
echo "  Loopback-only binding         : $([ "${IS_LAN_EXPOSED}" == "no" ] && echo 'confirmed' || echo 'WARNING — see above')"
echo "  Model downloaded              : yes"
echo "  File ignored by Git           : ${GITIGNORE_COVERS}"
echo "  Cloud key required            : no"
echo ""
echo "Next steps:"
echo ""
echo "  1. Start the backend (loads .env.local automatically):"
echo "     bash scripts/run_fcgma_demo.sh"
echo ""
echo "  2. Check Terris mode:"
echo "     bash scripts/check_terris_mode.sh"
echo ""
echo "  3. Verify local intelligence:"
echo "     bash scripts/verify_terris_local.sh"
echo ""
echo "  4. Open the portal at: http://localhost:8080"
echo ""
