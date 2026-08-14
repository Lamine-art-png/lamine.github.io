#!/bin/sh
set -eu

REF="${AGROAI_CLI_REF:-main}"
VENV_ROOT="${AGROAI_CLI_HOME:-${HOME}/.local/share/agroai-cli}"
BIN_DIR="${AGROAI_BIN_DIR:-${HOME}/.local/bin}"
SPEC="https://github.com/Lamine-art-png/lamine.github.io/archive/${REF}.zip#subdirectory=sdk/python"

say() { printf '%s\n' "$*"; }
fail() { printf 'agroai installer: %s\n' "$*" >&2; exit 1; }

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
    then
      PYTHON="$candidate"
      break
    fi
  fi
done
[ -n "$PYTHON" ] || fail "Python 3.10 or newer is required"

say "Installing AGRO-AI CLI from the official AGRO-AI source (${REF})..."

if command -v pipx >/dev/null 2>&1; then
  pipx install --force "$SPEC"
  CLI="$(command -v agroai 2>/dev/null || true)"
else
  mkdir -p "$VENV_ROOT" "$BIN_DIR"
  if [ ! -x "$VENV_ROOT/venv/bin/python" ]; then
    "$PYTHON" -m venv "$VENV_ROOT/venv"
  fi
  "$VENV_ROOT/venv/bin/python" -m pip install --disable-pip-version-check --upgrade pip >/dev/null
  "$VENV_ROOT/venv/bin/python" -m pip install --disable-pip-version-check --upgrade "$SPEC"
  ln -sf "$VENV_ROOT/venv/bin/agroai" "$BIN_DIR/agroai"
  CLI="$BIN_DIR/agroai"
fi

[ -n "$CLI" ] || CLI="$(command -v agroai 2>/dev/null || true)"
[ -x "$CLI" ] || fail "installation completed but the agroai executable was not found"

VERSION="$($CLI --version 2>/dev/null || true)"
[ -n "$VERSION" ] || fail "the installed agroai executable did not pass its version check"

say "Installed: $VERSION"
case ":${PATH}:" in
  *":${BIN_DIR}:"*) : ;;
  *) say "Add ${BIN_DIR} to PATH if your shell cannot find agroai." ;;
esac
say "Next: agroai login"
