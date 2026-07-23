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
