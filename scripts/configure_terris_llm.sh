#!/usr/bin/env bash
# configure_terris_llm.sh — Interactive Terris LLM configuration wizard.
#
# Writes TERRIS_LLM_PROVIDER, TERRIS_LLM_MODEL, TERRIS_LLM_API_KEY to
# agroai_api/.env.local (git-ignored).  The key is captured silently and
# never printed, echoed, or logged.
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
echo "  1) Anthropic (default) — claude-sonnet-4-6"
echo "  2) OpenAI               — gpt-4o"
echo ""
read -r -p "Enter 1 or 2 [1]: " PROVIDER_CHOICE
PROVIDER_CHOICE="${PROVIDER_CHOICE:-1}"

case "$PROVIDER_CHOICE" in
  2)
    PROVIDER="openai"
    DEFAULT_MODEL="gpt-4o"
    ;;
  *)
    PROVIDER="anthropic"
    DEFAULT_MODEL="claude-sonnet-4-6"
    ;;
esac

# ── Model ─────────────────────────────────────────────────────────────────────
read -r -p "Model name [${DEFAULT_MODEL}]: " MODEL_INPUT
MODEL="${MODEL_INPUT:-${DEFAULT_MODEL}}"

# ── API key (hidden input) ─────────────────────────────────────────────────────
echo ""
echo "Enter your ${PROVIDER} API key (input is hidden — key will not be displayed):"
read -r -s API_KEY
echo ""  # newline after hidden input

if [[ -z "$API_KEY" ]]; then
  echo "ERROR: API key cannot be empty. Configuration aborted." >&2
  exit 1
fi

# Verify key starts with expected prefix (Anthropic: sk-ant-, OpenAI: sk-)
if [[ "$PROVIDER" == "anthropic" && ! "$API_KEY" =~ ^sk- ]]; then
  echo "WARNING: Key does not start with 'sk-' — please verify it is correct."
fi

# ── Write to .env.local ───────────────────────────────────────────────────────
mkdir -p "$(dirname "${ENV_LOCAL}")"

# Remove existing Terris lines if present
if [[ -f "${ENV_LOCAL}" ]]; then
  grep -v "^TERRIS_LLM_" "${ENV_LOCAL}" > "${ENV_LOCAL}.tmp" && mv "${ENV_LOCAL}.tmp" "${ENV_LOCAL}" || true
fi

cat >> "${ENV_LOCAL}" << EOF
TERRIS_LLM_PROVIDER=${PROVIDER}
TERRIS_LLM_MODEL=${MODEL}
TERRIS_LLM_API_KEY=${API_KEY}
EOF

# Unset key from shell memory
unset API_KEY

echo ""
echo "Configuration saved to ${ENV_LOCAL}"
echo "  Provider : ${PROVIDER}"
echo "  Model    : ${MODEL}"
echo "  Key      : *** (stored securely, not printed)"
echo ""
echo "Restart the backend to activate Connected Intelligence Mode:"
echo "  bash scripts/run_fcgma_demo.sh"
echo ""
echo "Verify mode with: bash scripts/check_terris_mode.sh"
