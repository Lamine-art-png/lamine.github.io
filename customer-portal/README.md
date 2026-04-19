# AGRO-AI Customer Portal

Customer portal MVP intended for future deployment at `app.agroai-pilot.com`.

## Local preview

```bash
cd customer-portal
python -m http.server 4173
```

Open `http://localhost:4173`.

## API base configuration

Default API base is `https://api.agroai-pilot.com`.

You can override without source edits by using one of these:

1. Query param (one-off):
   - `http://localhost:4173?apiBase=https://your-api.example.com`
2. In-browser saved override via the portal header input (stored in `localStorage` as `AGROAI_API_BASE`).
3. Optional pre-injected global before app load:
   - `window.AGROAI_API_BASE = "https://your-api.example.com"`

## Live endpoints wired in the portal

- `GET /v1/wiseconn/auth`
- `GET /v1/wiseconn/farms`
- `GET /v1/wiseconn/farms/{farm_id}/zones`
- `GET /v1/wiseconn/zones/{zone_id}/irrigations`
- `GET /v1/decisioning/blocks/{block_id}/water-state`
- `GET /v1/decisioning/blocks/{block_id}/water-state/history`
- `GET /v1/execution/blocks/{block_id}/decisions`
- `GET /v1/execution/blocks/{block_id}/verifications`
- `GET /v1/reports/roi` (if enabled in the deployed API)

## Static deploy note (`app.agroai-pilot.com`)

1. Deploy `customer-portal/` as static files.
2. Point `app.agroai-pilot.com` to that static host.
3. Keep API base set to `https://api.agroai-pilot.com` for production.
4. Do not alter Railway secrets, DNS, or infra outside explicit change control.
