from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


resolver = r'''#!/usr/bin/env bash
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
'''
write(".github/scripts/resolve-backend-release-sha.sh", resolver)

contract_test = r'''from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(text: str, value: str, label: str) -> None:
    if value not in text:
        raise AssertionError(f"{label}: missing {value!r}")


resolver = read(".github/scripts/resolve-backend-release-sha.sh")
deploy = read(".github/workflows/deploy.yml")
phase6 = read(".github/workflows/deploy-platform-api-marketing.yml")
diagnostics = read(".github/workflows/platform-api-private-beta-diagnostics.yml")
readiness = read(".github/workflows/production-readiness-snapshot.yml")

require(resolver, 'git log -1 --format=%H -- agroai_api', "resolver")
require(resolver, 'is-shallow-repository', "resolver")

for label, workflow in {
    "authoritative release": deploy,
    "Phase 6 proof": phase6,
    "private-beta diagnostics": diagnostics,
}.items():
    require(workflow, "resolve-backend-release-sha.sh", label)
    require(workflow, "BACKEND_RELEASE_SHA", label)

require(deploy, 'backend-release-sha: ${{ steps.backend-sha.outputs.sha }}', "authoritative release output")
require(deploy, 'backend_release_sha=${BACKEND_RELEASE_SHA}', "immutable release evidence")
require(phase6, 'health_exact_backend_sha', "Phase 6 diagnostic identity")
require(phase6, 'expected_backend_sha', "Phase 6 expected backend SHA")
require(diagnostics, 'required backend deployment SHA', "diagnostic wording")
require(readiness, 'Observed backend build SHA', "readiness truth")
require(readiness, 'Backend deployment exact', "readiness truth")

for label, workflow in {
    "authoritative release": deploy,
    "Phase 6 proof": phase6,
    "private-beta diagnostics": diagnostics,
}.items():
    if '--arg sha "$GITHUB_SHA"' in workflow:
        raise AssertionError(f"{label}: backend identity must not be compared to the release workflow SHA")

print("Backend release identity contract: ok")
'''
write("scripts/check_backend_release_identity_contract.py", contract_test)

# Authoritative Cloudflare production release.
deploy_path = ROOT / ".github/workflows/deploy.yml"
deploy = deploy_path.read_text(encoding="utf-8")
deploy = replace_once(
    deploy,
    "  deploy-edge:\n    name: Deploy API edge and queues\n    needs: validate\n    runs-on: ubuntu-latest\n",
    "  deploy-edge:\n    name: Deploy API edge and queues\n    needs: validate\n    outputs:\n      backend-release-sha: ${{ steps.backend-sha.outputs.sha }}\n    runs-on: ubuntu-latest\n",
    label="deploy-edge outputs",
)
deploy = replace_once(
    deploy,
    "      EDGE_ORIGIN_AUTH_TOKEN: ${{ secrets.EDGE_ORIGIN_AUTH_TOKEN }}\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-node@v4\n",
    "      EDGE_ORIGIN_AUTH_TOKEN: ${{ secrets.EDGE_ORIGIN_AUTH_TOKEN }}\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0\n\n      - name: Resolve immutable backend deployment commit\n        id: backend-sha\n        shell: bash\n        run: |\n          set -euo pipefail\n          backend_sha=\"$(bash .github/scripts/resolve-backend-release-sha.sh)\"\n          echo \"sha=${backend_sha}\" >> \"$GITHUB_OUTPUT\"\n          echo \"BACKEND_RELEASE_SHA=${backend_sha}\" >> \"$GITHUB_ENV\"\n          echo \"Release SHA: ${GITHUB_SHA}\"\n          echo \"Expected backend deployment SHA: ${backend_sha}\"\n\n      - uses: actions/setup-node@v4\n",
    label="deploy-edge checkout and resolver",
)
if deploy.count('--arg sha "$GITHUB_SHA"') != 2:
    raise RuntimeError("authoritative release: expected two direct release-SHA backend comparisons")
deploy = deploy.replace('--arg sha "$GITHUB_SHA"', '--arg sha "$BACKEND_RELEASE_SHA"')
deploy = replace_once(
    deploy,
    "              printf '%s' \"$payload\" > upstream-release-contract.json\n              echo \"Exact backend build, schema, storage, and Queue contract is ready\"\n",
    "              printf '%s' \"$payload\" | jq \\\n                --arg release_sha \"$GITHUB_SHA\" \\\n                --arg expected_backend_sha \"$BACKEND_RELEASE_SHA\" \\\n                '. + {release_sha: $release_sha, expected_backend_sha: $expected_backend_sha}' \\\n                > upstream-release-contract.json\n              echo \"Backend deployment commit, schema, storage, and Queue contract are ready\"\n",
    label="upstream evidence",
)
deploy = replace_once(
    deploy,
    "        env:\n          EDGE_RESULT: ${{ needs.deploy-edge.result }}\n          PORTAL_RESULT: ${{ needs.deploy-portal.result }}\n",
    "        env:\n          EDGE_RESULT: ${{ needs.deploy-edge.result }}\n          PORTAL_RESULT: ${{ needs.deploy-portal.result }}\n          BACKEND_RELEASE_SHA: ${{ needs.deploy-edge.outputs.backend-release-sha }}\n",
    label="release evidence env",
)
deploy = replace_once(
    deploy,
    "            echo \"release_sha=${GITHUB_SHA}\"\n            echo \"edge_result=${EDGE_RESULT}\"\n",
    "            echo \"release_sha=${GITHUB_SHA}\"\n            echo \"backend_release_sha=${BACKEND_RELEASE_SHA}\"\n            echo \"edge_result=${EDGE_RESULT}\"\n",
    label="release evidence body",
)
deploy_path.write_text(deploy, encoding="utf-8")

# Final Phase 6 production proof.
phase6_path = ROOT / ".github/workflows/deploy-platform-api-marketing.yml"
phase6 = phase6_path.read_text(encoding="utf-8")
phase6 = replace_once(
    phase6,
    "    steps:\n      - uses: actions/checkout@v4\n\n      - name: Fail closed on missing Cloudflare credentials\n",
    "    steps:\n      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0\n\n      - name: Resolve immutable backend deployment commit\n        shell: bash\n        run: |\n          set -euo pipefail\n          backend_sha=\"$(bash .github/scripts/resolve-backend-release-sha.sh)\"\n          echo \"BACKEND_RELEASE_SHA=${backend_sha}\" >> \"$GITHUB_ENV\"\n          echo \"Expected backend deployment SHA: ${backend_sha}\"\n\n      - name: Fail closed on missing Cloudflare credentials\n",
    label="Phase 6 checkout and resolver",
)
phase6 = replace_once(
    phase6,
    "jq -e --arg sha \"$GITHUB_SHA\" '.status == \"ok\" and .build_sha == $sha' proof/health.body",
    "jq -e --arg sha \"$BACKEND_RELEASE_SHA\" '.status == \"ok\" and .build_sha == $sha' proof/health.body",
    label="Phase 6 health identity",
)
phase6 = replace_once(
    phase6,
    "            --arg release_sha \"$GITHUB_SHA\" --argjson attempt \"$attempt\" --argjson ready \"$ready\" \\\n",
    "            --arg release_sha \"$GITHUB_SHA\" --arg expected_backend_sha \"$BACKEND_RELEASE_SHA\" --argjson attempt \"$attempt\" --argjson ready \"$ready\" \\\n",
    label="Phase 6 diagnostic args",
)
phase6 = replace_once(
    phase6,
    "            '{release_sha:$release_sha,attempts:$attempt,ready:($ready==1),http:",
    "            '{release_sha:$release_sha,expected_backend_sha:$expected_backend_sha,attempts:$attempt,ready:($ready==1),http:",
    label="Phase 6 diagnostic release identity",
)
phase6 = phase6.replace("health_exact_sha:$health_exact_sha", "health_exact_backend_sha:$health_exact_sha")
phase6 = replace_once(
    phase6,
    "            echo \"release_sha=${GITHUB_SHA}\"\n            echo \"ready=${ready}\"\n",
    "            echo \"release_sha=${GITHUB_SHA}\"\n            echo \"backend_release_sha=${BACKEND_RELEASE_SHA}\"\n            echo \"ready=${ready}\"\n",
    label="Phase 6 evidence identity",
)
phase6 = replace_once(
    phase6,
    "              echo \"- exact SHA: \\`${GITHUB_SHA}\\`\"\n              echo \"- run: \\`${GITHUB_RUN_ID}\\`\"\n",
    "              echo \"- release SHA: \\`${GITHUB_SHA}\\`\"\n              echo \"- backend deployment SHA: \\`${BACKEND_RELEASE_SHA}\\`\"\n              echo \"- run: \\`${GITHUB_RUN_ID}\\`\"\n",
    label="Phase 6 success comment identity",
)
phase6 = replace_once(
    phase6,
    "              echo \"- exact SHA: \\`${GITHUB_SHA}\\`\"\n              echo \"- run: \\`${GITHUB_RUN_ID}\\`\"\n              echo '- mode: redacted diagnostics; no credential values included'\n",
    "              echo \"- release SHA: \\`${GITHUB_SHA}\\`\"\n              echo \"- backend deployment SHA: \\`${BACKEND_RELEASE_SHA}\\`\"\n              echo \"- run: \\`${GITHUB_RUN_ID}\\`\"\n              echo '- mode: redacted diagnostics; no credential values included'\n",
    label="Phase 6 failure comment identity",
)
phase6_path.write_text(phase6, encoding="utf-8")

# Private-beta diagnostics should report the deployed backend commit, not an unrelated workflow SHA.
diag_path = ROOT / ".github/workflows/platform-api-private-beta-diagnostics.yml"
diag = diag_path.read_text(encoding="utf-8")
diag = diag.replace('  DOCS_URL: "https://agroai-pilot.com/developers"', '  DOCS_URL: "https://agroai-pilot.com/platform-api/docs/"\n  PLATFORM_URL: "https://platform.agroai-pilot.com"')
diag = replace_once(
    diag,
    "            probe public_edge_health \"${PUBLIC_API}/v1/edge-health\"\n            probe public_api_health \"${PUBLIC_API}/v1/health\"\n            probe enterprise_portal \"${PORTAL_URL}/\"\n",
    "            probe public_api_health \"${PUBLIC_API}/v1/health\"\n            probe standalone_edge_health \"${PLATFORM_URL}/v1/edge-health\"\n            probe standalone_api_health \"${PLATFORM_URL}/v1/health\"\n            probe enterprise_portal \"${PORTAL_URL}/\"\n",
    label="diagnostic public routes",
)
diag = replace_once(
    diag,
    "    steps:\n      - name: Probe redacted exact-SHA readiness\n",
    "    steps:\n      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0\n\n      - name: Resolve immutable backend deployment commit\n        shell: bash\n        run: |\n          set -euo pipefail\n          backend_sha=\"$(bash .github/scripts/resolve-backend-release-sha.sh)\"\n          echo \"BACKEND_RELEASE_SHA=${backend_sha}\" >> \"$GITHUB_ENV\"\n\n      - name: Probe redacted backend deployment readiness\n",
    label="diagnostic checkout and resolver",
)
diag = replace_once(
    diag,
    "jq -c --arg required_sha \"$GITHUB_SHA\"",
    "jq -c --arg required_sha \"$BACKEND_RELEASE_SHA\"",
    label="diagnostic backend identity",
)
diag = replace_once(
    diag,
    "            echo \"- required exact SHA: \\`${GITHUB_SHA}\\`\"\n",
    "            echo \"- required backend deployment SHA: \\`${BACKEND_RELEASE_SHA}\\`\"\n",
    label="diagnostic wording",
)
diag_path.write_text(diag, encoding="utf-8")

# Production readiness must distinguish the release orchestration SHA from the deployed backend SHA.
readiness = r'''name: Production Readiness Snapshot

on:
  push:
    branches: ["main"]
  workflow_dispatch:

permissions:
  contents: read
  issues: write

jobs:
  snapshot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Capture public readiness report
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -u
          backend_release_sha="$(bash .github/scripts/resolve-backend-release-sha.sh)"
          curl -sS --connect-timeout 10 --max-time 60 \
            "https://api-preview.agroai-pilot.com/v1/readiness" > readiness.json || printf '{}' > readiness.json
          curl -sS --connect-timeout 10 --max-time 60 \
            "https://api-preview.agroai-pilot.com/v1/health" > health.json || printf '{}' > health.json
          observed_backend_sha="$(jq -r '.build_sha // ""' health.json 2>/dev/null)"
          backend_exact=false
          if [ -n "$observed_backend_sha" ] && [ "$observed_backend_sha" = "$backend_release_sha" ]; then backend_exact=true; fi
          {
            echo "# Production readiness snapshot"
            echo
            echo "- Release SHA: \`${GITHUB_SHA}\`"
            echo "- Expected backend deployment SHA: \`${backend_release_sha}\`"
            echo "- Observed backend build SHA: \`${observed_backend_sha}\`"
            echo "- Backend deployment exact: \`${backend_exact}\`"
            echo "- run: \`${GITHUB_RUN_ID}\`"
            echo
            echo '```json'
            jq '{status,version,schema,production}' readiness.json 2>/dev/null || cat readiness.json
            echo '```'
          } > status.md
          gh issue edit 124 --repo "${GITHUB_REPOSITORY}" --body-file status.md
'''
write(".github/workflows/production-readiness-snapshot.yml", readiness)

# Extend the existing release-contract CI so this semantic cannot regress.
ci_path = ROOT / ".github/workflows/ci.yml"
ci = ci_path.read_text(encoding="utf-8")
ci = replace_once(
    ci,
    "      - '.github/workflows/deploy.yml'\n      - 'figma-enterprise-v4/**'\n",
    "      - '.github/workflows/deploy.yml'\n      - '.github/workflows/deploy-platform-api-marketing.yml'\n      - '.github/workflows/platform-api-private-beta-diagnostics.yml'\n      - '.github/workflows/production-readiness-snapshot.yml'\n      - '.github/scripts/resolve-backend-release-sha.sh'\n      - 'scripts/check_backend_release_identity_contract.py'\n      - 'figma-enterprise-v4/**'\n",
    label="CI trigger paths",
)
ci = replace_once(
    ci,
    "      - uses: actions/checkout@v4\n      - uses: actions/setup-node@v4\n        with:\n          node-version: '22'\n",
    "      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0\n      - name: Validate backend release identity semantics\n        run: |\n          python3 scripts/check_backend_release_identity_contract.py\n          test -n \"$(bash .github/scripts/resolve-backend-release-sha.sh)\"\n      - uses: actions/setup-node@v4\n        with:\n          node-version: '22'\n",
    label="CI release identity step",
)
ci_path.write_text(ci, encoding="utf-8")

# Remove one-off diagnostics/bootstrap files from the final tree.
for temporary in (
    ".github/workflows/platform-release-final-state-diagnostic.yml",
    ".github/workflows/apply-backend-release-contract-patch.yml",
    "scripts/apply_backend_release_contract_patch.py",
):
    path = ROOT / temporary
    if path.exists():
        path.unlink()

print("Applied backend deployment identity contract repair.")
