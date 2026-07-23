#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [ "$(git rev-parse --is-shallow-repository)" != "false" ]; then
  echo "Backend release identity requires a full Git history (checkout fetch-depth: 0)." >&2
  exit 1
fi

backend_sha="$(git log -1 --format=%H -- agroai_api)"
if [ -z "$backend_sha" ]; then
  echo "Unable to resolve the latest commit that owns the agroai_api deployment tree." >&2
  exit 1
fi

git cat-file -e "${backend_sha}^{commit}"
printf '%s\n' "$backend_sha"
