#!/usr/bin/env bash
# configure_terris_llm.sh — Interactive Terris LLM configuration wizard.
#
# Writes TERRIS_LLM_PROVIDER, TERRIS_LLM_MODEL, TERRIS_LLM_API_KEY, and
# TERRIS_LLM_REASONING_EFFORT to agroai_api/.env.local (git-ignored).
# The key is captured silently and is NEVER printed, echoed, or logged.
#
# Usage: bash scripts/configure_terris_llm.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_LOCAL="${REPO_ROOT}/agroai_api/.env.local"

echo ""
echo "=== Terris LLM Configuration ==="
echo "This wizard writes your LLM provider credentials to:"
echo "  ${ENV_LOCAL}"
echo ""
echo "The file is git-ignored. Your API key will NEVER be printed or logged."
echo ""

# ── Provider ──────────────────────────────────────────────────────────────────
echo "Select LLM provider:"
echo "  1) OpenAI   (default) — gpt-5.5 with reasoning"
echo "  2) Anthropic           — claude-sonnet-4-6"
echo ""
read -r -p "Enter 1 or 2 [1]: " PROVIDER_CHOICE
PROVIDER_CHOICE="${PROVIDER_CHOICE:-1}"

case "$PROVIDER_CHOICE" in
  2)
    PROVIDER="anthropic"
    DEFAULT_MODEL="claude-sonnet-4-6"
    ;;
  *)
    PROVIDER="openai"
    DEFAULT_MODEL="gpt-5.5"
    ;;
esac

# ── Model ─────────────────────────────────────────────────────────────────────
if [[ "$PROVIDER" == "openai" ]]; then
  echo ""
  echo "Select model:"
  echo "  1) gpt-5.5      (default — full reasoning, highest quality)"
  echo "  2) gpt-5.4      (strong reasoning, faster)"
  echo "  3) gpt-5.4-mini (balanced cost/performance)"
  echo "  4) Custom       (enter any valid model ID)"
  echo ""
  read -r -p "Enter 1-4 [1]: " MODEL_CHOICE
  MODEL_CHOICE="${MODEL_CHOICE:-1}"
  case "$MODEL_CHOICE" in
    2) MODEL="gpt-5.4" ;;
    3) MODEL="gpt-5.4-mini" ;;
    4)
      read -r -p "Model name: " CUSTOM_MODEL
      MODEL="${CUSTOM_MODEL:-}"
      ;;
    *) MODEL="gpt-5.5" ;;
  esac
else
  read -r -p "Model name [${DEFAULT_MODEL}]: " MODEL_INPUT
  MODEL="${MODEL_INPUT:-${DEFAULT_MODEL}}"
fi

# ── Validate model ────────────────────────────────────────────────────────────
TRIMMED_MODEL="${MODEL//[[:space:]]/}"
if [[ -z "$TRIMMED_MODEL" ]]; then
  echo "ERROR: Model name cannot be empty or whitespace. Configuration aborted." >&2
  exit 1
fi
if [[ "$MODEL" =~ ^[0-9]+$ ]]; then
  echo "ERROR: Model name cannot be numeric-only (got: '${MODEL}')." >&2
  echo "       Provide a valid model ID such as 'gpt-5.5' or 'claude-sonnet-4-6'." >&2
  exit 1
fi

# ── Reasoning effort (OpenAI only) ────────────────────────────────────────────
REASONING_EFFORT="xhigh"
if [[ "$PROVIDER" == "openai" ]]; then
  echo ""
  echo "Reasoning effort (controls extended thinking depth):"
  echo "  1) xhigh  (default — full reasoning, highest quality)"
  echo "  2) high   (strong reasoning, faster)"
  echo "  3) medium (balanced)"
  echo ""
  read -r -p "Enter 1-3 [1]: " EFFORT_CHOICE
  EFFORT_CHOICE="${EFFORT_CHOICE:-1}"
  case "$EFFORT_CHOICE" in
    2) REASONING_EFFORT="high" ;;
    3) REASONING_EFFORT="medium" ;;
    *) REASONING_EFFORT="xhigh" ;;
  esac
fi

# ── API key (hidden input) ─────────────────────────────────────────────────────
echo ""
echo "Enter your ${PROVIDER} API key (input is hidden — key will not be displayed):"
read -r -s API_KEY
echo ""  # newline after hidden input

if [[ -z "${API_KEY:-}" || "${API_KEY}" =~ ^[[:space:]]*$ ]]; then
  echo "ERROR: API key cannot be empty or whitespace. Configuration aborted." >&2
  exit 1
fi

# Verify key starts with expected prefix
if [[ ! "$API_KEY" =~ ^sk- ]]; then
  echo "WARNING: Key does not start with 'sk-' — please verify it is correct."
fi

# ── Backup and write to .env.local ────────────────────────────────────────────
mkdir -p "$(dirname "${ENV_LOCAL}")"

if [[ -f "${ENV_LOCAL}" ]]; then
  BACKUP="${ENV_LOCAL}.bak.$(date +%Y%m%d%H%M%S)"
  cp "${ENV_LOCAL}" "${BACKUP}"
  chmod 600 "${BACKUP}"
  echo "  Backup created: ${BACKUP}"

  # Remove existing TERRIS_LLM lines and any orphaned bare model-name lines
  grep -v "^TERRIS_LLM_" "${ENV_LOCAL}" \
    | grep -v "^gpt-" \
    | grep -v "^claude-" \
    > "${ENV_LOCAL}.tmp" || true
  mv "${ENV_LOCAL}.tmp" "${ENV_LOCAL}"
fi

# Append new TERRIS_LLM block
{
  printf 'TERRIS_LLM_PROVIDER=%s\n' "${PROVIDER}"
  printf 'TERRIS_LLM_MODEL=%s\n' "${MODEL}"
  printf 'TERRIS_LLM_API_KEY=%s\n' "${API_KEY}"
  printf 'TERRIS_LLM_REASONING_EFFORT=%s\n' "${REASONING_EFFORT}"
} >> "${ENV_LOCAL}"

# Unset key from shell memory immediately — never lingers in env
unset API_KEY

# Lock file permissions (owner read/write only)
chmod 600 "${ENV_LOCAL}"

echo ""
echo "Configuration saved to ${ENV_LOCAL} (permissions: 600)"
echo "  Provider         : ${PROVIDER}"
echo "  Model            : ${MODEL}"
echo "  Reasoning effort : ${REASONING_EFFORT}"
echo "  Key              : *** (stored securely, never printed)"
echo ""
echo "Restart the backend to activate Connected Intelligence Mode:"
echo "  bash scripts/run_fcgma_demo.sh"
echo ""
echo "Verify mode with:"
echo "  bash scripts/check_terris_mode.sh"
echo ""
