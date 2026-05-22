# EarthDaily Demo Runbook

## T-24h

```bash
cd agroai-cloudflare-worker/api-native
npm install
npm run typecheck
npm test
npm run migrate:staging
wrangler secret list --env staging
npm run deploy:staging
```

Demo mode is acceptable when EarthDaily live credentials are absent. Configure secrets with Wrangler only; never commit them:

```bash
wrangler secret put EARTHDAILY_CLIENT_ID --env staging
wrangler secret put EARTHDAILY_SECRET --env staging
wrangler secret put EARTHDAILY_AUTH_URL --env staging
wrangler secret put EARTHDAILY_API_URL --env staging
wrangler secret put AGROAI_LLM_API_KEY --env staging
```

## Smoke

```bash
curl <staging>/health
curl <staging>/api/v1/partners/earthdaily/status
curl -X POST <staging>/api/v1/partners/earthdaily/end-to-end \
  -H "content-type: application/json" \
  -d '{}' | jq
```

## T-1h

Open `customer-portal/index.html` against the staging worker host and set:

```js
window.AGROAI_EDGE_API_BASE = "https://<staging-worker-host>";
```

Click **Run EarthDaily -> AGRO-AI Decision Workflow**. Confirm all 8 panels populate in under 3 seconds and that the mode badge says `demo` when no live creds are configured.

## Call Narrative

1. EarthDaily data in: Panel 3 shows imagery, indices, weather, anomaly, and soil moisture.
2. AGRO-AI normalizes: Panel 4 shows 6 component scores.
3. AGRO-AI decides: Panel 5 shows action, timing, volume, confidence, risks, and reasoning.
4. AGRO-AI reports: Panel 6 shows executive, advisor, grower, and water savings output.
5. It is a real API: Panel 7 shows envelope, request_id, and decision_id.
6. EarthDaily integration ask: Panel 8 shows sandbox/feed, API path, update cadence, STAC + JSON, and technical owner.

## Failure Modes

- Endpoint down: the frontend automatically hits `/api/v1/demo/earthdaily/sample-response`.
- LLM down or missing key: deterministic fallback report renders.
- Live creds invalid: `/status` returns `live_ready=false`; demo mode takes over when `DEMO_MODE=true`.

## Security Checks

- `/status` exposes only booleans and data product names, never secret values.
- CORS uses the `ALLOWED_ORIGINS` allowlist; wildcard is not used.
- `X-Request-Id` is returned on every Worker response.
- `input_hash` is SHA-256 over canonical JSON and is not reversible.
- Audit rows contain metadata only, no secrets, raw prompts, or full provider payloads.

