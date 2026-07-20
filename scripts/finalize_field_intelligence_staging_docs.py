from __future__ import annotations

from pathlib import Path


def replace(path: str, old: str, new: str, *, required: bool = True) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        if required:
            raise SystemExit(f"missing replacement marker in {path}: {old!r}")
        return
    target.write_text(text.replace(old, new), encoding="utf-8")


# Bound the workflow lookup to the exact feature head. One response is valid
# JSON and old PR/base runs cannot satisfy the gate.
replace(
    ".github/workflows/field-intelligence-staging.yml",
    'gh api --paginate "repos/${GITHUB_REPOSITORY}/actions/runs?event=pull_request&per_page=100" > /tmp/pr-runs.json',
    'gh api "repos/${GITHUB_REPOSITORY}/actions/runs?event=pull_request&head_sha=${STAGE_SHA}&per_page=100" > /tmp/pr-runs.json',
)

# Upgrade the placeholder-only environment template to the immutable identity
# contract without introducing any credential value.
env_path = Path("agroai_api/.env.staging.example")
env = env_path.read_text(encoding="utf-8")
env = env.replace(
    "FIELD_STAGING_PORTAL_PROJECT=agroai-portal-staging\n",
    "FIELD_STAGING_PORTAL_PROJECT=agroai-portal-staging\nPRODUCTION_PORTAL_PROJECT=agroai-portal\n",
)
env = env.replace(
    "PRODUCTION_DATABASE_HOST_FINGERPRINT=      # production DB hostname only (for refusal checks)",
    "PRODUCTION_DATABASE_RESOURCE_FINGERPRINT=  # host:port/database, no credentials",
)
env = env.replace(
    "# --- Staging deploy hooks (staging-only credentials) --------------------------\n"
    "FIELD_STAGING_DEPLOY_HOOK=                 # staging API service deploy hook\n"
    "FIELD_STAGING_WORKER_DEPLOY_HOOK=          # optional: dedicated worker service hook",
    "# --- Immutable staging deployment identities ---------------------------------\n"
    "FIELD_STAGING_DEPLOY_PROVIDER=render\n"
    "FIELD_STAGING_API_SERVICE_ID=              # immutable staging API service id\n"
    "FIELD_STAGING_DEPLOY_HOOK=                 # must resolve to the id above\n"
    "PRODUCTION_API_SERVICE_ID=                 # non-secret production id\n"
    "FIELD_STAGING_WORKER_MODE=dedicated        # dedicated or in_process\n"
    "FIELD_STAGING_WORKER_SERVICE_ID=\n"
    "FIELD_STAGING_WORKER_DEPLOY_HOOK=\n"
    "PRODUCTION_WORKER_SERVICE_ID=              # non-secret production id",
)
env = env.replace(
    "FIELD_STAGING_OBJECT_BUCKET=               # e.g. agroai-field-staging\n",
    "FIELD_STAGING_OBJECT_BUCKET=               # e.g. agroai-field-staging\n"
    "FIELD_STAGING_OBJECT_ACCOUNT_ID=           # non-secret provider account id\n"
    "PRODUCTION_OBJECT_BUCKET_FINGERPRINT=      # account-id:bucket-name\n",
)
if "FIELD_RELEASE_PORTAL_SHA=" not in env:
    env += (
        "\n# --- Exact release identity on the staging API service ------------------------\n"
        "# FIELD_RELEASE_PORTAL_SHA=<exact staged SHA>\n"
        "# FIELD_RELEASE_EDGE_SHA=<exact declared staging release SHA>\n"
    )
env_path.write_text(env, encoding="utf-8")

# Keep the runbook truthful and aligned with the new linear migration and exact
# merge-ref dispatch contract.
runbook_path = Path("docs/field-intelligence-staging-runbook.md")
runbook = runbook_path.read_text(encoding="utf-8")
for old, new in {
    "024→022→024": "027→026→027",
    "024 -> 022 -> 024": "027 -> 026 -> 027",
    "024 -> 022": "027 -> 026",
    "022 -> 024": "026 -> 027",
    "024_field_intelligence_launch": "027_field_intelligence_launch",
}.items():
    runbook = runbook.replace(old, new)
runbook = runbook.replace(
    "`confirm=STAGE_FIELD_INTELLIGENCE`, `sha=<exact branch head>`, optional\n`run_smoke=true`.",
    "`confirm=STAGE_FIELD_INTELLIGENCE`, `sha=<exact branch head>`,\n"
    "`merge_sha=<current PR #258 merge commit>`, optional `run_smoke=true`.\n"
    "The workflow requires all mandatory PR workflows to exist and be terminal\n"
    "and successful for the exact head and current `main` base.",
)
if "## Immutable identity gates" not in runbook:
    runbook += """

## Immutable identity gates

Before any deploy hook is called, the staging contract requires and compares:

- staging and production API service IDs;
- staging and production worker service IDs;
- normalized database identities (`host:port/database`);
- normalized object-store identities (`account-id:bucket-name`);
- staging and production Cloudflare Pages project names;
- recognized provider deploy hooks whose embedded service ID exactly matches
  the declared staging service.

Missing production fingerprints fail closed. A naming convention such as
`staging` is additional defense, not the isolation proof.

## Current provisioning status

No staging infrastructure is provisioned by source code. Until the protected
`field-intelligence-staging` environment contains the isolated API, database,
worker, R2, transcription, Pages, internal-account, and immutable fingerprint
values, the workflow fails before network deployment. Production remains
untouched and the server-side release state remains disabled there.
"""
runbook_path.write_text(runbook, encoding="utf-8")
