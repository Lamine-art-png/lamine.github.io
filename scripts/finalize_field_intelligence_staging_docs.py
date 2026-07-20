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


workflow = ".github/workflows/field-intelligence-staging.yml"
replace(
    workflow,
    'gh api --paginate "repos/${GITHUB_REPOSITORY}/actions/runs?event=pull_request&per_page=100" > /tmp/pr-runs.json',
    'gh api "repos/${GITHUB_REPOSITORY}/actions/runs?event=pull_request&head_sha=${STAGE_SHA}&per_page=100" > /tmp/pr-runs.json',
)
replace(
    workflow,
    'FIELD_STAGING_OBJECT_PREFIX: ${{ vars.FIELD_STAGING_OBJECT_PREFIX }}',
    "FIELD_STAGING_OBJECT_PREFIX: ${{ vars.FIELD_STAGING_OBJECT_PREFIX || 'staging/field-intelligence' }}",
)
replace(
    workflow,
    'FIELD_STAGING_RELEASE_STATE: ${{ vars.FIELD_STAGING_RELEASE_STATE }}',
    "FIELD_STAGING_RELEASE_STATE: ${{ vars.FIELD_STAGING_RELEASE_STATE || 'internal' }}",
)
replace(
    workflow,
    '          assert (rollout.get("release_alignment") or {}).get("aligned") is True, rollout\n'
    '          print(json.dumps({"schema_ready": True, "field_blockers": 0, "rollout": rollout.get("effective_state"), "aligned": True}))',
    '          alignment = rollout.get("release_alignment") or {}\n'
    '          assert alignment.get("api_sha") == os.environ["STAGE_SHA"], alignment\n'
    '          assert alignment.get("worker_shas") == [os.environ["STAGE_SHA"]], alignment\n'
    '          assert alignment.get("database_heads") == ["027_field_intelligence_launch"], alignment\n'
    '          allowed_external = {"portal_sha_unreported", "edge_sha_unreported"}\n'
    '          unexpected = set(alignment.get("mismatches") or []) - allowed_external\n'
    '          assert not unexpected, {"unexpected_alignment_mismatches": sorted(unexpected), "alignment": alignment}\n'
    '          print(json.dumps({"schema_ready": True, "field_blockers": 0, "rollout": rollout.get("effective_state"), "api_worker_database_aligned": True, "externally_verified_later": sorted(set(alignment.get("mismatches") or []) & allowed_external)}))',
)

contract_path = Path("agroai_api/scripts/field_intelligence_staging_contract.py")
contract = contract_path.read_text(encoding="utf-8")
contract = contract.replace(
    '    "FIELD_STAGING_INTERNAL_ORGANIZATION_IDS",\n    "FIELD_STAGING_PORTAL_PROJECT",',
    '    "FIELD_STAGING_INTERNAL_ORGANIZATION_IDS",\n    "FIELD_STAGING_SMOKE_TOKEN",\n    "FIELD_STAGING_PORTAL_PROJECT",',
)
contract = contract.replace(
    '    "FIELD_STAGING_SMOKE_TOKEN",\n    "FIELD_STAGING_RESTRICTED_SMOKE_TOKEN",',
    '    "FIELD_STAGING_RESTRICTED_SMOKE_TOKEN",',
)
contract_path.write_text(contract, encoding="utf-8")

test_path = Path("agroai_api/tests/unit/test_field_intelligence_staging_contract.py")
test_text = test_path.read_text(encoding="utf-8")
if '"FIELD_STAGING_SMOKE_TOKEN": "staging-admin-token"' not in test_text:
    test_text = test_text.replace(
        '    "FIELD_STAGING_INTERNAL_ORGANIZATION_IDS": "org-staging-internal",\n',
        '    "FIELD_STAGING_INTERNAL_ORGANIZATION_IDS": "org-staging-internal",\n'
        '    "FIELD_STAGING_SMOKE_TOKEN": "staging-admin-token",\n',
    )
test_text = test_text.replace('assert "pulls/258" in text', 'assert "pulls/${STAGING_PR}" in text')
test_path.write_text(test_text, encoding="utf-8")

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
        "\n# --- Optional API-side release labels -----------------------------------------\n"
        "# Internal staging verifies the live portal separately in the workflow.\n"
        "# FIELD_RELEASE_PORTAL_SHA=<exact staged SHA when managed by the provider>\n"
        "# FIELD_RELEASE_EDGE_SHA=<exact edge SHA when a staging edge exists>\n"
    )
env_path.write_text(env, encoding="utf-8")

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
    "The workflow requires every mandatory PR workflow to be present, terminal,\n"
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

For the direct-provider `internal` topology, API, worker, and database identity
are proven through the backend; the portal is then fetched live and verified
against its public deployment metadata. Portal/edge labels absent from the API
are not represented as deployed surfaces.

## Current provisioning status

No staging infrastructure is provisioned by source code. Until the protected
`field-intelligence-staging` environment contains the isolated API, database,
worker, R2, transcription, Pages, internal-account, and immutable fingerprint
values, the workflow fails before network deployment. Production remains
untouched and the server-side release state remains disabled there.
"""
runbook_path.write_text(runbook, encoding="utf-8")
