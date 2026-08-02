#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [ "$(git rev-parse --is-shallow-repository)" != "false" ]; then
  echo "Backend release identity requires a full Git history (checkout fetch-depth: 0)." >&2
  exit 1
fi

# Render deploys the default branch commit, including merge commits. Plain
# `git log -- <path>` applies history simplification and can skip a merge commit,
# incorrectly returning an internal PR commit that Render can never report as
# its build SHA. Walk the default branch's first-parent chain and select the
# newest commit whose tree actually changes the backend deployment directory.
candidate="$(git rev-parse HEAD)"
while git rev-parse --verify --quiet "${candidate}^1" >/dev/null; do
  if ! git diff --quiet "${candidate}^1" "$candidate" -- agroai_api; then
    git cat-file -e "${candidate}^{commit}"
    printf '%s\n' "$candidate"
    exit 0
  fi
  candidate="$(git rev-parse "${candidate}^1")"
done

# Root-commit fallback for repositories whose first commit already contains the
# backend tree.
if git ls-tree -r --name-only "$candidate" -- agroai_api | grep -q .; then
  git cat-file -e "${candidate}^{commit}"
  printf '%s\n' "$candidate"
  exit 0
fi

echo "Unable to resolve the latest first-parent commit that owns the agroai_api deployment tree." >&2
exit 1
