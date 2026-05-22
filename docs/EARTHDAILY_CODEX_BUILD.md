# AGRO-AI × EarthDaily — Codex Build Instructions

**Audience:** Codex (autonomous build agent).
**Goal:** Ship a production-shaped EarthDaily → AGRO-AI integration on the deployed Cloudflare API plus a serious demo frontend, in time for an EarthDaily executive call.
**Branch:** `claude/trusting-allen-jF2XV`.
**Non-goal:** A local toy script. A pretty dashboard that fakes everything. Claiming live EarthDaily data when no credentials are configured.

---

## 0. Positioning (read this before writing code)

EarthDaily is the **agricultural data infrastructure layer** (imagery, STAC, NDVI/NDRE/EVI/NDMI time series, weather, ET, anomaly, change detection, field boundaries, benchmarking, Rx maps).

AGRO-AI is the **irrigation decision intelligence layer** that consumes those data products and returns:

- recommendation (irrigate / wait / monitor / investigate / manual_review)
- timing window
- volume
- confidence
- risk flags
- reasoning
- report-ready output

Do **not** rebuild EarthDaily's monitoring. The API decision output is the product; the frontend only visualizes it.

---

## 1. Repository Map (current truth)

You are working in the `lamine-art-png/lamine.github.io` repo. Relevant pieces:

| Path | What it is | Use for EarthDaily? |
|---|---|---|
| `agroai-cloudflare-worker/api-native/` | TS Cloudflare Worker, D1, Durable Objects, deployed as `agroai-api-staging`. Talgil integration lives here. Single-file router in `src/index.ts`. | **YES — primary deploy target.** Add EarthDaily module alongside Talgil. |
| `agroai_api/` | Python FastAPI deployed via Cloudflare **Containers** at `api.agroai-pilot.com`. Has `/v1/...` routes, decisioning, demos. | **Reference only.** Mirror schemas/patterns; do not deploy EarthDaily logic here. |
| `agroai/` | Trivial Python sim engine (`engine.py` = ET₀ × Kc). | **Reference only.** Rebuild deterministic core in TS. |
| `customer-portal/` | Vanilla JS portal (`window.AGROAI_API_BASE` → `https://api.agroai-pilot.com`, vanilla module views in `js/views/`). | **YES — add an EarthDaily view.** |
| `apps/velia-ai-api/` | Express dev backend. | Ignore. |
| `wrangler.toml` (root) | Cloudflare **Containers** config for the Python API. Do not modify. | — |
| `agroai-cloudflare-worker/api-native/wrangler.toml` | Worker config. **Edit this** for EarthDaily env + secrets. | — |

**Hard rules:**
1. Put EarthDaily logic in the **TypeScript Worker** (`agroai-cloudflare-worker/api-native/`). It is the real Cloudflare-native edge API.
2. The Python FastAPI in `agroai_api/` is hosted on Containers and is not the integration target. Do not duplicate logic there.
3. Frontend: extend `customer-portal/`, do not introduce a new framework.

---

## 2. Target Architecture (where each piece lives)

All new TypeScript under `agroai-cloudflare-worker/api-native/src/`:

```
src/
  index.ts                          # extend router — add EarthDaily routes
  schemas/
    earthdaily.ts                   # EarthDailyRawInput
    signals.ts                      # NormalizedSignalPack
    decision.ts                     # DecisionOutput
    report.ts                       # ReportObject
    common.ts                       # ApiEnvelope, RequestContext, ErrorShape
  adapters/
    earthdaily/
      index.ts                      # provider entry — picks demo vs live
      demoAdapter.ts                # rich sample EarthDaily payload generator
      liveAdapter.ts                # EDS REST client skeleton (auth + STAC + indices + weather)
      types.ts                      # provider-local types
    demo/
      sampleField.ts                # curated demo field (Madera almonds, etc.)
      sampleResponse.ts             # precomputed end-to-end response
  core/
    normalization/
      normalize.ts                  # EarthDailyRawInput → NormalizedSignalPack
      derive.ts                     # derived signals: depletion, stress, ET pressure
    risk/
      flags.ts                      # risk flag computation (8 flags from the spec)
    confidence/
      score.ts                      # confidence score + drivers + limitations
    decision/
      engine.ts                     # deterministic irrigation decision (the brain)
      volume.ts                     # crop/stage/method-aware volume calc
      timing.ts                     # window selection from ET + weather + crop calendar
      rules.ts                      # versioned rule constants (RULES_VERSION)
    reporting/
      report.ts                     # DecisionOutput → ReportObject
  lib/
    llm/
      client.ts                     # JSON-strict LLM caller (Anthropic / OpenAI compatible)
      prompt.ts                     # advisor / grower / executive / technical prompts
      jsonGuard.ts                  # parse + validate strict JSON, no markdown
    audit/
      trace.ts                      # audit entry shape + writer (D1 or KV)
      hash.ts                       # input hashing for traceability
    cloudflare/
      env.ts                        # Env type augmentation
      cors.ts                       # CORS allowlist
      requestId.ts                  # X-Request-Id middleware
      rateLimit.ts                  # placeholder limiter (KV or in-memory)
      errors.ts                     # safe error responses
  api/
    routes/
      earthdailyStatus.ts
      earthdailyNormalize.ts
      earthdailyDecision.ts
      earthdailyReport.ts
      earthdailyEndToEnd.ts
      demoSampleField.ts
      demoSampleResponse.ts
      decisionRead.ts
      decisionAudit.ts
      health.ts
```

Plus:

```
agroai-cloudflare-worker/api-native/
  migrations/
    003_earthdaily_decisions.sql    # decisions + audit tables
  tests/                            # NEW — uses vitest + @cloudflare/vitest-pool-workers
    schemas.test.ts
    demoAdapter.test.ts
    liveAdapterMissingCreds.test.ts
    normalize.test.ts
    decisionEngine.test.ts
    confidence.test.ts
    riskFlags.test.ts
    report.test.ts
    routes.happy.test.ts
    routes.invalid.test.ts
    sampleResponse.snapshot.test.ts
  vitest.config.ts
```

Frontend (extend, do not replace):

```
customer-portal/
  index.html                        # add nav entry
  js/
    config.js                       # already exposes apiBase — reuse
    apiClient.js                    # add ENDPOINTS.earthdaily*
    views/
      earthdailyView.js             # NEW — 8 panels from spec
    components/
      earthdailyPanels/             # NEW — small render helpers
```

---

## 3. Data Model — Implement Exactly

Use TypeScript interfaces in `src/schemas/`. Every field below is required unless marked `?`. Mirror these names exactly so the Python FastAPI side can later adopt them verbatim.

### 3.1 `EarthDailyRawInput`

```ts
export interface EarthDailyRawInput {
  provider: "earthdaily";
  mode: "demo" | "live";
  field: {
    field_id: string;
    field_name: string;
    grower_id: string;
    farm_id: string;
    crop_type: string;
    crop_stage: string;
    acreage: number;
    geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
    timezone: string;
    region: string;
    soil_profile: {
      texture: string;
      awc_mm_per_m: number;
      rooting_depth_m: number;
      field_capacity: number;
      wilting_point: number;
    };
  };
  imagery: {
    stac_items: Array<{ id: string; collection: string; datetime: string; href: string }>;
    acquisition_date: string;
    cloud_cover: number;
    asset_links: Record<string, string>;
    index_maps: Record<string, string>;
    vegetation_indices: { ndvi_mean: number; ndre_mean: number; evi_mean: number; ndmi_mean: number };
    anomaly_layers: Array<{ id: string; type: string; severity: number; href: string }>;
  };
  time_series: {
    ndvi: TimeSeriesPoint[];
    ndmi: TimeSeriesPoint[];
    evi: TimeSeriesPoint[];
    ndre: TimeSeriesPoint[];
    lai: TimeSeriesPoint[];
    biomass: TimeSeriesPoint[];
    fapar: TimeSeriesPoint[];
    fcover: TimeSeriesPoint[];
  };
  weather: {
    forecast_days: number;
    precipitation: TimeSeriesPoint[];
    temperature_min: TimeSeriesPoint[];
    temperature_max: TimeSeriesPoint[];
    humidity: TimeSeriesPoint[];
    wind_speed: TimeSeriesPoint[];
    gdd: TimeSeriesPoint[];
    et0: TimeSeriesPoint[];
    et_forecast: TimeSeriesPoint[];
  };
  water_context: {
    soil_moisture_surface: number;
    soil_moisture_rootzone: number;
    estimated_depletion: number;        // mm
    water_stress_index: number;         // 0..1
    irrigation_history: Array<{ date: string; volume_mm: number; method: string }>;
    applied_water_actuals: Array<{ date: string; volume_mm: number }>;
  };
  agronomic_events: {
    emergence?: string;
    peak_growth?: string;
    senescence?: string;
    change_detection: Array<{ date: string; type: string; magnitude: number }>;
    hotspot_alerts: Array<{ date: string; type: string; severity: number; bbox: number[] }>;
  };
  metadata: {
    source: string;
    retrieved_at: string;
    data_freshness: string;
    missing_fields: string[];
    quality_flags: string[];
  };
}

export interface TimeSeriesPoint { date: string; value: number; quality?: string }
```

### 3.2 `NormalizedSignalPack`, `DecisionOutput`, `ReportObject`

Implement every field listed in the spec verbatim (signal_pack_id, decision_id, recommendation.action ∈ {irrigate, wait, monitor, investigate, manual_review}, priority ∈ {low, medium, high, critical}, the 8 risk flags, confidence drivers/limitations, trace.{model_version, rules_version, provider, input_hash, created_at}). Generate IDs with `crypto.randomUUID()`. `input_hash` = SHA-256 of canonical-JSON of `EarthDailyRawInput`.

---

## 4. Adapter Layer

### 4.1 Provider entry (`adapters/earthdaily/index.ts`)

```ts
export async function loadEarthDailyInput(
  env: Env,
  req: { field_id?: string; mode?: "demo" | "live"; raw?: EarthDailyRawInput }
): Promise<{ input: EarthDailyRawInput; mode: "demo" | "live"; usedFallback: boolean }>;
```

Decision logic:
1. If `req.raw` is provided → use it verbatim, `usedFallback=false`, mode = `req.raw.mode`.
2. Else if `LIVE_EARTHDAILY_ENABLED === "true"` and all four `EARTHDAILY_*` secrets exist → call `liveAdapter.fetch(env, field_id)`.
3. Else if `DEMO_MODE === "true"` → call `demoAdapter.build(field_id)`.
4. Else → throw `EarthDailyUnavailableError` (handled by route → friendly 503).

### 4.2 Demo adapter (`demoAdapter.ts`)

Produce a **rich, realistic, internally-consistent** payload. One curated field minimum: Madera County almonds, ~120 acres, mid-season, mild moisture stress. Generate 30 days of NDVI/NDMI/EVI/NDRE/ET₀ with seasonally plausible values; 7 days of weather forecast with one heat event; one hotspot alert; STAC item placeholders pointing at Sentinel-2 L2A IDs. Mark `metadata.source = "agroai-demo-fixture"` and `mode = "demo"`. Do **not** label as live.

### 4.3 Live adapter (`liveAdapter.ts`) — skeleton only, real REST

Wrap the EarthDaily Platform REST API directly (the Python `earthdaily.EDSClient` is not edge-compatible). Implement:

- `authenticate(env)` → OAuth client_credentials against `EARTHDAILY_AUTH_URL`, returns access token, cache in KV with TTL = `expires_in - 60s` (key `eds:token`).
- `stacSearch(env, token, { collection: "sentinel-2-l2a", intersects: geometry, datetime: range })` → POST `${EARTHDAILY_API_URL}/stac/search`.
- `vegetationTimeSeries(env, token, { field_id, indices: ["ndvi","ndmi","evi","ndre"], date_range })`.
- `weatherIndicators(env, token, { field_id, forecast_days })`.
- `changeDetection(env, token, { field_id, window })`.
- `normalizeToRawInput(...)` → assemble an `EarthDailyRawInput`.

Endpoints must be table-driven (`EARTHDAILY_API_URL` + path constants in one file). If a call fails or returns non-2xx, fail closed: throw `EarthDailyLiveError` — the route handler decides whether to fall back to demo based on `DEMO_MODE`.

Missing credentials → never throw at module load. The status endpoint must report `live_ready: false` and the reason, and demo fallback handles requests.

---

## 5. Deterministic Decision Engine

The LLM must never override irrigation decisions outside an explicit `review_mode=true` flag.

### 5.1 Component scores (`core/decision/engine.ts`)

All scores returned in `[0,1]`. Each function takes `NormalizedSignalPack`. Implement these and unit-test each:

| Score | Inputs | Notes |
|---|---|---|
| `moisture_stress_score` | rootzone SM, depletion, AWC, FC, WP | Higher = drier rootzone |
| `et_pressure_score` | 7-day ET₀ forecast, recent precip | Demand minus supply |
| `vegetation_stress_score` | NDVI slope (14d), NDRE slope, NDMI level | Down trends drive higher |
| `anomaly_severity` | hotspot alerts + change_detection magnitude | Max severity * weight |
| `weather_risk_score` | heat days >35°C, wind, no-rain run | Bounded [0,1] |
| `data_quality_score` | cloud_cover, missing_fields count, freshness hours | **Higher = better data** |

Composite priority:

```
raw = 0.30*moisture + 0.25*et + 0.20*veg + 0.15*anomaly + 0.10*weather
priority_score = raw * (0.5 + 0.5*data_quality_score)
```

Buckets: `[0..0.25)` low, `[0.25..0.55)` medium, `[0.55..0.80)` high, `[0.80..1]` critical.

Action selection:

| Condition | action |
|---|---|
| `data_quality_score < 0.35` OR ≥3 risk flags include data_gap/cloud/sensor_conflict | `investigate` |
| `priority_score >= 0.55` AND moisture_stress >= 0.45 AND no over-irrigation risk | `irrigate` |
| `0.25 <= priority_score < 0.55` | `monitor` |
| `priority_score < 0.25` AND moisture sufficient | `wait` |
| Conflicting strong signals | `manual_review` |

### 5.2 Volume (`core/decision/volume.ts`)

`recommended_volume_mm = clamp(estimated_depletion + et_forecast_7d_sum*kc_stage - precip_forecast_7d_sum, 0, max_method_mm)`.

`kc_stage` lookup table keyed by `(crop_type, crop_stage)` for at least almonds, grapes, corn, alfalfa, tomato. Convert to gallons/acre using method (drip 0.90 / sprinkler 0.75 / flood 0.55 efficiency). Emit `recommended_volume`, `recommended_volume_unit`, `estimated_duration`, `estimated_duration_unit`, `irrigation_method_assumption`.

### 5.3 Timing (`core/decision/timing.ts`)

Pick the earliest 12-hour window in the next 72h where: `temp_max < 32°C`, `wind_speed < 6 m/s`, no rain ≥ 5mm. Emit `recommended_window_start`/`end` in ISO-8601 with field timezone.

### 5.4 Risk flags — all 8 from spec

`water_stress, heat_stress, data_gap, cloud_contamination, anomaly_detected, over_irrigation_risk, under_irrigation_risk, sensor_conflict`. Each is `boolean` with a deterministic threshold defined in `rules.ts` and pinned by `RULES_VERSION`.

### 5.5 Confidence (`core/confidence/score.ts`)

`score = 0.4*data_quality_score + 0.3*signal_agreement + 0.2*recency_score + 0.1*model_self_consistency`. Level: `<0.45` low, `<0.7` medium, `<0.85` high, else `very_high`. Emit `drivers` (top 3 positive factors) and `limitations` (top 3 negative factors).

### 5.6 Reasoning tokens

The deterministic engine **does not** produce prose. It produces structured reasoning tokens consumed by the LLM:

```ts
type ReasoningToken =
  | { kind: "signal"; name: string; value: number; weight: number; impact: "positive"|"negative" }
  | { kind: "rule"; id: string; triggered: boolean; description: string }
  | { kind: "constraint"; id: string; value: string };
```

---

## 6. AI Explanation Layer

`lib/llm/client.ts` posts to Anthropic Messages API (model from `AGROAI_LLM_MODEL`, key from `AGROAI_LLM_API_KEY`). Request `response_format` strict JSON (or instruct via prompt + validate with `jsonGuard.ts`). On any parse failure: log, return a deterministic fallback report assembled from reasoning tokens — never block the decision.

Inputs to LLM (exact):

```json
{
  "normalized_signal_pack": {...},
  "decision_output": {...},
  "risk_flags": {...},
  "confidence": {...},
  "report_objective": "advisor_summary" | "executive_summary" | "grower_message" | "technical_explanation",
  "audience": "technical" | "advisor" | "grower" | "executive"
}
```

Output must validate against `LLMReportPayload`:

```ts
interface LLMReportPayload {
  executive_summary: string;     // 1–3 sentences
  decision_explanation: string;  // 2–5 sentences
  risk_interpretation: string;
  recommended_next_actions: string[];
  limitations: string;
  commercial_demo_narrative: string;
}
```

No markdown, no code fences. Strict JSON only. If LLM returns invalid → fallback to deterministic templating.

The LLM never mutates `DecisionOutput.recommendation.*`. It only fills `rationale.executive_summary` and the `ReportObject` prose fields.

---

## 7. Cloudflare API Routes

Extend `src/index.ts`. **Do not** require `x-admin-token` on EarthDaily routes (the existing Talgil guard is tenant-internal). EarthDaily routes are demo-facing; protect with CORS allowlist + per-IP rate limit placeholder.

Add to `Env`:

```ts
interface Env {
  // existing: DB, TALGIL_SYNC, ADMIN_TOKEN, ...
  EARTHDAILY_CLIENT_ID?: string;
  EARTHDAILY_SECRET?: string;
  EARTHDAILY_AUTH_URL?: string;
  EARTHDAILY_API_URL?: string;
  AGROAI_LLM_API_KEY?: string;
  AGROAI_LLM_MODEL?: string;
  DEMO_MODE?: string;             // "true" | "false"
  LIVE_EARTHDAILY_ENABLED?: string;
  AGROAI_ENV?: string;
  AGROAI_API_VERSION?: string;
  ALLOWED_ORIGINS?: string;       // comma-separated
  EDS_TOKEN_CACHE: KVNamespace;   // new KV for token cache
}
```

Routes (mount under existing fetch handler, before the 404):

| Method + Path | Handler | Behavior |
|---|---|---|
| `GET /health` | `health.ts` | `{status, version=AGROAI_API_VERSION, build_ts, environment=AGROAI_ENV, modules:["earthdaily","talgil"]}` |
| `GET /api/v1/partners/earthdaily/status` | `earthdailyStatus.ts` | `{credentials_configured, live_enabled, demo_mode, live_ready, data_products:[...], reason?}` — never leaks secret values |
| `POST /api/v1/partners/earthdaily/normalize` | `earthdailyNormalize.ts` | Validate `EarthDailyRawInput` → return `NormalizedSignalPack` |
| `POST /api/v1/partners/earthdaily/decision` | `earthdailyDecision.ts` | Accept normalized **or** raw (auto-normalize) → return `DecisionOutput`. Persist to D1. |
| `POST /api/v1/partners/earthdaily/report` | `earthdailyReport.ts` | Accept `DecisionOutput` + optional `field_metadata` → return `ReportObject` (LLM-augmented) |
| `POST /api/v1/partners/earthdaily/end-to-end` | `earthdailyEndToEnd.ts` | Accept raw payload (or empty body → load demo) → return `{earthdaily_raw_input, normalized_signal_pack, decision_output, ai_review, report_object, audit_trace, integration_metadata}` |
| `GET /api/v1/demo/earthdaily/sample-field` | `demoSampleField.ts` | Curated demo field; clearly tagged `mode:"demo"` |
| `GET /api/v1/demo/earthdaily/sample-response` | `demoSampleResponse.ts` | Precomputed full end-to-end response — reliability fallback |
| `GET /api/v1/decisions/{decision_id}` | `decisionRead.ts` | Fetch persisted `DecisionOutput` from D1 |
| `GET /api/v1/decisions/{decision_id}/audit` | `decisionAudit.ts` | Fetch audit trail entries |

**Every response** must wrap success bodies in:

```ts
interface ApiEnvelope<T> {
  ok: true;
  request_id: string;
  provider: "earthdaily";
  mode: "demo" | "live";
  data: T;
}
```

Errors:

```ts
interface ApiErrorEnvelope {
  ok: false;
  request_id: string;
  error: { code: string; message: string; details?: unknown };
}
```

Set `X-Request-Id` header on every response; generate with `crypto.randomUUID()` if missing on inbound.

CORS: read `ALLOWED_ORIGINS` (comma-separated); echo origin if allowed; preflight handling in `lib/cloudflare/cors.ts`.

Input validation: hand-rolled validators in `schemas/*.ts` (no zod — keep bundle tiny). Reject unknown `provider`. Reject NaN, infinities, payloads >256KB.

---

## 8. Persistence & Audit

Migration `migrations/003_earthdaily_decisions.sql`:

```sql
CREATE TABLE IF NOT EXISTS earthdaily_decisions (
  decision_id TEXT PRIMARY KEY,
  field_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  mode TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  recommendation_action TEXT NOT NULL,
  priority TEXT NOT NULL,
  confidence_score REAL NOT NULL,
  rules_version TEXT NOT NULL,
  model_version TEXT NOT NULL,
  decision_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eds_decisions_field ON earthdaily_decisions(field_id);

CREATE TABLE IF NOT EXISTS earthdaily_audit (
  audit_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL,
  step TEXT NOT NULL,           -- 'normalize'|'decide'|'report'|'llm'|'live_fetch'|'demo_fallback'
  status TEXT NOT NULL,         -- 'ok'|'error'|'fallback'
  duration_ms INTEGER NOT NULL,
  request_id TEXT NOT NULL,
  meta_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (decision_id) REFERENCES earthdaily_decisions(decision_id)
);
CREATE INDEX IF NOT EXISTS idx_eds_audit_decision ON earthdaily_audit(decision_id);
```

Audit writer (`lib/audit/trace.ts`) appends one row per pipeline step. **Never log secret values.** Log: timing, request_id, provider mode, input_hash, error codes.

---

## 9. Wrangler / Secrets

Edit `agroai-cloudflare-worker/api-native/wrangler.toml`:

```toml
# under [env.staging]
[[env.staging.kv_namespaces]]
binding = "EDS_TOKEN_CACHE"
id = "<create with: wrangler kv:namespace create EDS_TOKEN_CACHE --env staging>"

[env.staging.vars]
ENVIRONMENT = "staging"
AGROAI_ENV = "staging"
AGROAI_API_VERSION = "v1"
DEMO_MODE = "true"
LIVE_EARTHDAILY_ENABLED = "false"
ALLOWED_ORIGINS = "https://app.agroai-pilot.com,https://agroai-portal.pages.dev,http://localhost:4173,http://127.0.0.1:4173"
AGROAI_LLM_MODEL = "claude-sonnet-4-6"

[[env.staging.migrations]]
tag = "v2"
new_sqlite_classes = []
```

Secrets — never commit, set via wrangler:

```
wrangler secret put EARTHDAILY_CLIENT_ID  --env staging
wrangler secret put EARTHDAILY_SECRET     --env staging
wrangler secret put EARTHDAILY_AUTH_URL   --env staging
wrangler secret put EARTHDAILY_API_URL    --env staging
wrangler secret put AGROAI_LLM_API_KEY    --env staging
```

The `.dev.vars.staging.example` file must be updated to list every new env var with placeholder values (no real secrets).

---

## 10. Frontend (customer-portal)

Add **one** new view: `js/views/earthdailyView.js`. Mount via the existing shell view nav.

### 10.1 API client additions (`js/apiClient.js`)

Add to `ENDPOINTS`:

```js
earthdailyStatus: "/api/v1/partners/earthdaily/status",
earthdailyEndToEnd: "/api/v1/partners/earthdaily/end-to-end",
earthdailySampleField: "/api/v1/demo/earthdaily/sample-field",
earthdailySampleResponse: "/api/v1/demo/earthdaily/sample-response",
earthdailyDecision: (id) => `/api/v1/decisions/${encodeURIComponent(id)}`,
earthdailyAudit: (id) => `/api/v1/decisions/${encodeURIComponent(id)}/audit`,
```

The worker is deployed at a different host than the FastAPI (`https://agroai-api-staging.<account>.workers.dev`, or eventually `https://api.agroai-pilot.com/edge/*` if routed). Allow override via `window.AGROAI_EDGE_API_BASE` in `config.js`, fall back to `AGROAI_API_BASE`.

### 10.2 Eight panels (exact)

Build as eight sibling sections in `earthdailyView.js`:

1. **Executive landing** — headline: "EarthDaily data in. AGRO-AI decisions out. Customer workflow ready." Subhead with provider/mode badge.
2. **Field selection** — sample field card (name, crop, acreage, region, freshness, mode badge).
3. **Scattered data panel** — eight tiles: field boundary (geometry summary), STAC items list, vegetation time series mini-chart, NDMI moisture signal, ET forecast chart, weather strip, anomaly events list, soil moisture estimate, data quality flags.
4. **Normalization panel** — table of normalized features with raw → normalized → score columns; render the 6 component scores as bars.
5. **Decision panel** — recommendation badge, timing window, volume + unit, confidence bar + level, risk flag chips (red/amber), reasoning bullets, next action CTA.
6. **Report panel** — executive summary, advisor note, grower-facing message, water savings estimate, compliance note, audit trace link.
7. **API panel** — collapsible raw JSON for each step, endpoint path, request_id, HTTP status, provider trace, decision_id.
8. **Deployment mapping** — static content describing AGRO-AI's EarthDaily asks: sandbox account or feed, API access path, update cadence, preferred output format (STAC + JSON), technical owner contact.

### 10.3 The single button

Big primary CTA: **"Run EarthDaily → AGRO-AI Decision Workflow"**. On click:

1. Show skeleton loaders in panels 3–7.
2. `POST /api/v1/partners/earthdaily/end-to-end` with empty body (server loads demo) **or** the sample field returned by `GET /api/v1/demo/earthdaily/sample-field`.
3. On 2xx: hydrate panels 3–7 from the response.
4. On failure: try `GET /api/v1/demo/earthdaily/sample-response`. If that also fails: render friendly error card with retry button. Never crash the view.

Use vanilla DOM + the existing styles. No new framework. Match the existing portal aesthetic (look at `commandCenterView.js` for patterns).

---

## 11. Test Suite

Add `vitest` + `@cloudflare/vitest-pool-workers`:

```json
"devDependencies": {
  "@cloudflare/vitest-pool-workers": "^0.5.0",
  "vitest": "^2.0.0"
}
```

Required tests (one file each):

| File | Asserts |
|---|---|
| `tests/schemas.test.ts` | Validator rejects missing required fields, wrong provider, NaN values |
| `tests/demoAdapter.test.ts` | Sample payload is internally consistent (date ordering, value ranges, mode="demo") |
| `tests/liveAdapterMissingCreds.test.ts` | Missing secrets → status endpoint reports live_ready=false, no throw |
| `tests/normalize.test.ts` | Known input → expected normalized scores within tolerance |
| `tests/decisionEngine.test.ts` | Each action case (`irrigate`, `wait`, `monitor`, `investigate`, `manual_review`) hits with crafted inputs |
| `tests/confidence.test.ts` | Score boundaries; drivers/limitations selection |
| `tests/riskFlags.test.ts` | Each of 8 flags fires under its trigger and is silent otherwise |
| `tests/report.test.ts` | Report assembles even when LLM unavailable (fallback path) |
| `tests/routes.happy.test.ts` | All 10 endpoints return 200 + envelope shape |
| `tests/routes.invalid.test.ts` | 400 on bad JSON, 400 on unknown provider, 413 on >256KB |
| `tests/sampleResponse.snapshot.test.ts` | `/sample-response` payload is stable byte-for-byte (snapshot) |

Run: `npm test` (add script). CI: extend `.github/workflows/` to run `npm test && npm run typecheck` in the worker dir.

---

## 12. Build & Deploy Commands

Add to `agroai-cloudflare-worker/api-native/package.json`:

```json
"scripts": {
  "dev": "wrangler dev --env staging",
  "deploy:staging": "wrangler deploy --env staging",
  "typecheck": "tsc --noEmit",
  "test": "vitest run",
  "test:watch": "vitest",
  "migrate:staging": "wrangler d1 migrations apply agroai_staging2 --env staging --remote",
  "kv:create": "wrangler kv:namespace create EDS_TOKEN_CACHE --env staging"
}
```

Update root `README.md` with a new **"EarthDaily Integration — Quickstart"** section pointing at `docs/EARTHDAILY_CODEX_BUILD.md` and the demo runbook in §14.

---

## 13. Security Checklist (must pass before demo)

- [ ] No EarthDaily secret reaches the frontend (verify `/status` payload — only booleans and lists).
- [ ] CORS allowlist enforced — wildcard never used.
- [ ] `X-Request-Id` on every response.
- [ ] `input_hash` is SHA-256, not anything reversible.
- [ ] Audit log stores metadata only, never raw secrets, never full LLM prompts containing PII.
- [ ] Rate-limit placeholder (`lib/cloudflare/rateLimit.ts`) wired into routes — even if no-op, the hook exists.
- [ ] Payloads >256KB rejected with `413`.
- [ ] Unknown `provider` rejected with `400 unsupported_provider`.
- [ ] LLM never invoked without `AGROAI_LLM_API_KEY` — deterministic fallback used silently.
- [ ] Frontend never claims "live EarthDaily data" unless `/status` returns `live_enabled=true && live_ready=true`.
- [ ] No `console.error(secret)` anywhere. Add an eslint rule or grep check in CI.

---

## 14. Demo Runbook (write to `docs/EARTHDAILY_DEMO_RUNBOOK.md`)

T-24h:
1. `cd agroai-cloudflare-worker/api-native && npm install`
2. `npm run typecheck && npm test`
3. `npm run migrate:staging`
4. `wrangler secret list --env staging` — confirm secret presence (or absence — demo mode is fine).
5. `npm run deploy:staging`
6. Smoke: `curl <staging>/health`, `curl <staging>/api/v1/partners/earthdaily/status`, `curl -X POST <staging>/api/v1/partners/earthdaily/end-to-end -H "content-type: application/json" -d '{}' | jq`.

T-1h:
1. Open `customer-portal/index.html` against the staging worker host (set `window.AGROAI_EDGE_API_BASE`).
2. Click **Run EarthDaily → AGRO-AI Decision Workflow**. Confirm all 8 panels populate in <3s.
3. Verify mode badge says **demo** if no live creds.

During the call — the narrative beats:
1. **EarthDaily data in** — Panel 3 shows imagery, indices, weather, anomaly, soil moisture.
2. **AGRO-AI normalizes** — Panel 4 shows the 6 component scores.
3. **AGRO-AI decides** — Panel 5 shows action, timing, volume, confidence, risks, reasoning.
4. **AGRO-AI reports** — Panel 6 shows executive/advisor/grower outputs and water savings.
5. **It's a real API** — Panel 7 shows the live JSON envelope, request_id, decision_id.
6. **Here's what we need from EarthDaily** — Panel 8 walks the integration ask.

Failure modes:
- Endpoint down → frontend hits `/sample-response` automatically.
- LLM down → deterministic fallback report still renders (templated from reasoning tokens).
- Live creds rotated/invalid → status flips to `live_ready=false`, demo path takes over silently.

---

## 15. Acceptance Criteria (Codex must verify before declaring done)

- [ ] `npm install` succeeds in `agroai-cloudflare-worker/api-native/`.
- [ ] `npm run typecheck` passes with no errors.
- [ ] `npm test` passes — every test file in §11 exists and is green.
- [ ] `wrangler deploy --env staging` succeeds.
- [ ] `GET /health` returns `{status:"ok", version, environment, modules}`.
- [ ] `GET /api/v1/partners/earthdaily/status` returns credential + mode status without leaking secret values.
- [ ] `POST /api/v1/partners/earthdaily/end-to-end` (empty body) returns full envelope with all six top-level keys: `earthdaily_raw_input`, `normalized_signal_pack`, `decision_output`, `ai_review`, `report_object`, `audit_trace`, `integration_metadata`.
- [ ] Frontend renders all 8 panels without crashing when worker is reachable.
- [ ] Frontend renders all 8 panels using `/sample-response` when worker returns 5xx.
- [ ] No EarthDaily secret appears in any frontend payload (grep network responses).
- [ ] No claim of live EarthDaily data anywhere in the UI unless `live_enabled && live_ready`.
- [ ] Branch `claude/trusting-allen-jF2XV` is pushed to origin with all changes.

---

## 16. Do-Nots

- Do **not** make the EarthDaily integration hardcoded inside the decision engine. The engine consumes `NormalizedSignalPack`; the adapter produces it. Any future provider drops in by writing a new adapter.
- Do **not** put EarthDaily logic in `agroai_api/` (the Python FastAPI). It is not the integration target.
- Do **not** introduce React/Vue/Next/Vite into `customer-portal/`. It is vanilla JS — keep it that way.
- Do **not** ship a "Run" button that calls a hidden localhost backend. The button calls the deployed Cloudflare worker, always.
- Do **not** let the LLM mutate decisions. Prose only.
- Do **not** commit secrets. Use `wrangler secret put`.
- Do **not** claim live data without `LIVE_EARTHDAILY_ENABLED=true` AND `live_ready=true`.
- Do **not** push to `main` or any branch other than `claude/trusting-allen-jF2XV`.

---

## 17. Order of Implementation (for Codex to execute)

1. Schemas (`src/schemas/*`) — types + validators.
2. Demo adapter + sample field + sample response.
3. Normalization + component scores + risk flags + confidence.
4. Deterministic decision engine + volume + timing + rules.
5. Audit writer + D1 migration `003_earthdaily_decisions.sql`.
6. Routes (status, demo endpoints first, then normalize/decision/report/end-to-end, then read+audit).
7. CORS, request-id, rate-limit placeholder, error envelope, env type.
8. Live adapter skeleton (REST + token cache), behind `LIVE_EARTHDAILY_ENABLED` gate.
9. LLM client + jsonGuard + prompts + report assembly with fallback.
10. Tests (one file per item in §11).
11. Frontend view + apiClient additions + config tweak.
12. `wrangler.toml` env + KV binding + `.dev.vars.staging.example` update.
13. README quickstart + `docs/EARTHDAILY_DEMO_RUNBOOK.md`.
14. Local smoke (`wrangler dev`), then `deploy:staging`, then end-to-end smoke via the deployed URL.
15. Commit each phase with a clear message. Push to `claude/trusting-allen-jF2XV`. Do not open a PR unless explicitly asked.

End of instructions.
