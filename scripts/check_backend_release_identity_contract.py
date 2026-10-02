from __future__ import annotations

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

# The resolver deliberately walks the first-parent release chain. A historical
# contract expected `git log -1 -- ...`, but path history simplification can
# select an internal PR commit that was never the default-branch/Render release
# identity. Keep the contract tied to the safer first-parent tree-diff semantics.
require(resolver, 'git rev-parse --is-shallow-repository', "resolver")
require(resolver, 'candidate="$(git rev-parse HEAD)"', "resolver")
require(resolver, '"${candidate}^1"', "resolver")
require(resolver, 'git diff --quiet "${candidate}^1" "$candidate" -- agroai_api', "resolver")
require(resolver, 'candidate="$(git rev-parse "${candidate}^1")"', "resolver")
require(resolver, 'git cat-file -e "${candidate}^{commit}"', "resolver")

# Prevent regression to the old path-simplified lookup that cannot represent
# the actual merge/default-branch release commit reliably.
if 'git log -1 --format=%H -- agroai_api' in resolver:
    raise AssertionError("resolver: path-simplified git log must not replace first-parent release resolution")

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

# The paid Intelligence API proof must run for every backend release Render can
# deploy. Render rebuilds on any agroai_api/** change (the tree the resolver
# walks), so a narrow file list would let unrelated backend changes ship
# without re-proving the commercial contract.
commercial = read(".github/workflows/intelligence-api-commercial-production-verification.yml")
commercial_paths = commercial.split("paths:", 1)[1].split("workflow_dispatch:", 1)[0] if "paths:" in commercial else ""
for required_path in (
    "agroai_api/**",
    ".github/scripts/resolve-backend-release-sha.sh",
    ".github/workflows/intelligence-api-commercial-production-verification.yml",
):
    if f"- {required_path}" not in commercial_paths:
        raise AssertionError(f"commercial production proof: push paths must include {required_path!r}")
require(commercial, "resolve-backend-release-sha.sh", "commercial production proof")
require(commercial, 'value.get("build_sha") == expected', "commercial production proof exact identity")
if '--arg sha "$GITHUB_SHA"' in commercial:
    raise AssertionError("commercial production proof: backend identity must not be compared to the workflow SHA")

print("Backend release identity contract: ok")
