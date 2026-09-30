#!/usr/bin/env bash
# Wait until the production portal serves the release built from GITHUB_SHA
# (deployed only by the Cloudflare Production Release workflow, deploy.yml).
# Prints "current" when production serves this commit, or "superseded" when a
# newer commit on main is already live (this commit's release was replaced).
# Exits non-zero when neither happens within the timeout.
#
#   wait-for-portal-release.sh <portal-url> <sha> [timeout-seconds]
set -euo pipefail
portal="${1:?portal url}"
sha="${2:?sha}"
timeout="${3:-2400}"
deadline=$(( $(date +%s) + timeout ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  live="$(curl --silent --show-error --max-time 20 --retry 3 --retry-all-errors \
    -H 'Cache-Control: no-cache' "${portal%/}/deployment.json?wait=$(date +%s)" \
    | jq -r '.build_sha // empty' 2>/dev/null || true)"
  if [ "$live" = "$sha" ]; then
    echo "current"
    exit 0
  fi
  if [ -n "$live" ] && [ -n "${GH_TOKEN:-}" ]; then
    relation="$(gh api "repos/${GITHUB_REPOSITORY}/compare/${sha}...${live}" -q .status 2>/dev/null || true)"
    if [ "$relation" = "ahead" ]; then
      echo "superseded"
      exit 0
    fi
  fi
  echo "waiting for release ${sha}: production serves ${live:-unknown}" >&2
  sleep 20
done
echo "production never served release ${sha}" >&2
exit 1
