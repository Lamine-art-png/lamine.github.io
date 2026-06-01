# AGRO-AI Water Command Center V2

A parallel enterprise rebuild of the customer-facing irrigation intelligence
console, built with React + TypeScript + Vite. The existing `customer-portal`
remains the fallback evaluation surface until V2 passes review. **No hosting,
DNS, Cloudflare, Railway, or secret changes are made in this PR.**

Core product story: **AGRO-AI turns scattered irrigation data into verified
water decisions.**

## Architecture

```
apps/agroai-command-center-v2/
  index.html
  vite.config.ts        # static build, base "./" for Cloudflare Pages
  playwright.config.ts   # 1440 / 1280 / 1024 / 390 projects
  vitest.config.ts       # node unit tests (store logic)
  src/
    main.tsx, App.tsx     # route switch over a typed store
    styles/               # tokens.css, global.css, components.css (native CSS)
    api/                  # contracts.ts, client.ts, health.ts, runtimeStatus.ts
    state/commandStore.ts # useSyncExternalStore store + representative scenarios
    components/           # AppShell, Header, Sidebar, ExecutiveStrip,
                          # SourceIntelligence, DecisionPipeline, VerifiedDecision,
                          # AnalysisTrace, EvidenceChain, ReconciliationTable,
                          # ExecutiveReportPreview, SourceDrawer,
                          # IntegrationSetupDrawer, WorkspaceSwitcher,
                          # StatusBadge, EntryScreen, ProviderStatusList,
                          # GuidedWalkthrough, Toast
    pages/                # Command, Sources, Reports, Integrations, Audit, Settings
  test/                   # *.spec.ts (Playwright e2e) + store.test.ts (vitest)
```

State lives in one typed store (`commandStore.ts`) bound to React through
`useSyncExternalStore`; components select stable slices. No HTML string
templates, no monolithic components, no CSS cascade patches — styling is native
CSS driven by design tokens.

## Routes used (production API base unchanged)

API base: `https://api.agroai-pilot.com` (override with `VITE_API_BASE_URL`).

- `GET /v1/workbench/schema` — backend health probe
- `GET /openapi.json` — secondary health signal
- `POST /v1/workbench/sessions` — create session
- `POST /v1/workbench/sample-package` — representative session
- `POST /v1/workbench/sessions/{id}/upload` — upload records
- `POST /v1/workbench/sessions/{id}/analyze` — analyze uploaded records
- `POST /v1/workbench/analyze-live` — live connected-source analysis
- `POST /v1/workbench/sessions/{id}/actions/schedule` — evaluation schedule action
- `POST /v1/workbench/sessions/{id}/actions/applied` — evaluation applied-water action
- `POST /v1/workbench/sessions/{id}/actions/observe` — evaluation field observation
- `POST /v1/workbench/sessions/{id}/actions/verify` — evaluation outcome verification
- `GET /v1/workbench/sessions/{id}/evidence-chain` — evaluation evidence chain
- `GET /v1/controllers/environments` — provider runtime summary
- `GET /v1/wiseconn/auth` — WiseConn runtime auth check
- `GET /v1/talgil/status` — Talgil runtime status

## Truth states

Backend status is **derived from a real health probe** (`probeBackend`), never
hardcoded:

- **Backend available** — schema endpoint returns a usable contract.
- **Backend limited** — backend reachable but schema/contract incomplete.
- **Backend unavailable** — no successful response.

Network requests carry an 8s timeout so the UI degrades quickly and honestly.

## Fallback order

1. Backend Workbench result
2. Live connected-source result
3. Uploaded-record result
4. Representative fallback (clearly marked "Representative data")

The decision pipeline distinguishes representative / uploaded / live analysis,
and the recommendation origin is shown explicitly (`Representative fallback`,
`Deterministic engine`, `Live intelligence engine`, `Uploaded intelligence
engine`, or `Insufficient context`).

Provider statuses are also loaded from backend routes and normalized to truthful
states: `Live`, `Configured`, `Limited`, `Unavailable`, `Setup required`, or
`Target selection required`. The UI never claims EarthDaily is live; the partner
surface is labelled **Earth observation layer** until a feed is authorized.

## Entry and Walkthrough

The app opens on a restrained entry screen:

- **Open evaluation workspace** immediately loads representative records for a
  sales call.
- **Sign in for production access** does not collect or store credentials; it
  shows that production identity provisioning is required.
- **Request enterprise onboarding** opens a production-readiness brief.

The command workspace includes a compact guided walkthrough covering source
intelligence, decision pipeline, verified water decision, evidence chain, and
executive report. It can be reset without changing workspace data.

## Responsive layout

A 12-column command layout:

- **≥1480px** — left content area (7 cols: source intelligence, decision
  pipeline, analysis trace) + right decision rail (5 cols: verified decision,
  evidence chain). Reconciliation and report preview span below.
- **1101–1479px** — two columns (content + decision rail). The decision rail keeps
  a `minmax(320px, …)` floor so the verified decision never shrinks below a
  readable width.
- **≤1100px** — single-column application shell and command content ordered:
  executive strip → verified decision →
  decision pipeline → source intelligence → evidence chain → reconciliation →
  report preview.

Operational values use `overflow-wrap: break-word`; only long technical
identifiers use `overflow-wrap: anywhere`. Cards set `min-width: 0` and tables
scroll internally so the document never overflows horizontally.

## Build steps

```bash
cd apps/agroai-command-center-v2
npm install
npm run build      # tsc --noEmit && vite build  → dist/
npm run preview    # serve dist on :4180
```

The build emits a static `dist/` bundle (relative `base`) suitable for
Cloudflare Pages. **This PR does not switch hosting or production routes.**

## Test steps

```bash
npm run test       # vitest unit tests (store logic)
npm run test:e2e   # Playwright across 1440 / 1280 / 1024 / 390
```

e2e assertions: no horizontal overflow, no character-by-character wrapping, no
overlapping source metadata, decision card readable, header not duplicated,
truthful backend state (never "online" when a request fails), source drawer
opens, upload tab works, scenario switching works, evidence chain actions work,
CSV export works, report preview works.

## Known limitations

- Workbench sessions are **evaluation session storage only** (in-memory on the
  backend); tenant persistence is future work.
- Production authentication, credential vault, and tenant provisioning are
  server-side follow-ups.
- Recommendation numbers from the backend are computed by the v0.2 deterministic
  agronomic decision kernel. Durations are withheld unless flow or application
  rate evidence exists. Representative scenarios remain labelled as
  representative data.
- Live connected-source analysis degrades safely when provider telemetry is
  unavailable; it never fabricates telemetry.
- Evidence-chain persistence is evaluation-session storage only, not durable
  tenant persistence.

## Cloudflare static-build compatibility

`vite build` produces a self-contained static bundle with relative asset paths
(`base: "./"`). It can be served from a Pages project or any sub-path. No
Cloudflare project, DNS, or hosting configuration is changed by this PR.
