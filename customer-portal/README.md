# AGRO-AI Portal — Water Command Center

The customer portal is positioned as an enterprise **AGRO-AI Water Command Center** for day-to-day irrigation operations.

## Product navigation
- Command Center
- Intelligence
- Verification
- Reports
- Integrations

## Screen purpose
- **Command Center:** operational landing view with selected farm, selected zone/block, live source, today’s decision, confidence, data quality, reason, action, next verification step, and watch item.
- **Intelligence:** recommendation details including timing, duration/depth, confidence, quality, drivers, missing data, live/manual input trace, explanation, execution task, and verification plan.
- **Verification:** explicit lifecycle chain — Recommended, Scheduled, Applied, Observed — with polished empty-state language.
- **Reports:** professional report cards with rollout-safe messaging while generation is coming online.
- **Integrations:** WiseConn and Talgil integration cards with status, connection state, farms/targets, zones/sensors, last check, and current limitation.

## Runtime truth reflected in UI
- WiseConn runtime is live.
- Talgil runtime is live.
- Manual Intelligence Engine flow is live.
- Input normalization and live context routes are live.

## UX direction
- Premium agriculture technology visual language.
- Readable large cards and strong information hierarchy.
- Green/white/deep forest palette with soft neutrals.
- Responsive desktop/tablet/mobile layouts.
- No debug-oriented controls or raw JSON output in customer-facing screens.

## Local run
```bash
cd customer-portal
python -m http.server 4173
```

Open: `http://localhost:4173`

## Portal URL note
- Temporary URL: `https://app.agroai-pilot.com`
- `app.agroai-pilot.com` currently has a hosting conflict with Velia and must be corrected later.
- This PR intentionally does not modify hosting, DNS, Cloudflare, Railway, or secrets.
