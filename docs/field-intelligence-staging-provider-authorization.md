# Field Intelligence staging provider authorization

## Completed

- GitHub environment: `field-intelligence-staging`
- Cloudflare Pages project: `agroai-field-intelligence-staging`
- Pages URL: `https://agroai-field-intelligence-staging.pages.dev`
- Private R2 bucket: `agroai-field-intelligence-staging`
- Object prefix: `staging/field-intelligence`
- Render Blueprint: root `render.yaml` on `ops/field-intelligence-staging-provision`
- Blueprint validation: passed against tested SHA `9854a3084c6223bd7ddab5e0d182c3ba363e1790`

## Account-owner authorizations still required

The connected session does not expose authenticated Render, OpenAI organization, or GitHub environment-secret administration. Complete provider authorization only inside the respective provider dashboards. Do not post credentials in GitHub or chat.

### Cloudflare

Create a bucket-scoped R2 read/write identity for `agroai-field-intelligence-staging`.

### OpenAI

Create a staging project and a project service account for the audio transcription runtime.

### Render

Review the Blueprint at:

`https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2FLamine-art-png%2Flamine.github.io%2Ftree%2Fops%2Ffield-intelligence-staging-provision`

It defines:

- `agroai-field-intelligence-staging-api`
- `agroai-field-intelligence-staging-worker`
- `agroai-field-intelligence-staging-db`

Auto-deploy is disabled. The API and worker are pinned to the tested Field Intelligence branch and SHA. Secret values are intentionally absent from source.

### GitHub

Store provider credentials and Render deployment identities only in the `field-intelligence-staging` environment. Use the exact names required by `.github/workflows/field-intelligence-staging.yml` and `agroai_api/scripts/field_intelligence_staging_contract.py`.

## Final gate

PR #258 remains draft until the protected staging workflow passes source identity, full CI, migration round trip, API/worker SHA verification, object-store probe, real transcription smoke, portal verification, restricted-user denial, deletion and audit readback.
