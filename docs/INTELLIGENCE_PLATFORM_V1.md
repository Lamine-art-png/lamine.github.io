# Build with AGRO-AI Intelligence

AGRO-AI Intelligence is an API for building agricultural AI products. You send
a question plus whatever agricultural context you have — typed field, crop,
weather, soil, observation, treatment, financial or market data; photos and
documents; your own knowledge base; deterministic calculations — and receive an
evidence-grounded answer, optionally as schema-validated JSON, with provenance
for every source it used.

You do not choose or see model vendors. Every response comes from
`agroai-intelligence-1`; routing, fallbacks, retrieval and safety live behind it.

**Who it is for:** agtech startups, agribusiness and enterprise teams, and
internal AGRO-AI products that need agronomic reasoning without rebuilding
context handling, multimodal ingestion, retrieval, tenancy, billing and
production infrastructure.

**What it is not:** an actuator. Self-service keys are advisory. No endpoint
here opens a valve, drives a machine, mixes a chemical, writes to an equipment
provider or moves money. Those capabilities need a separately designed and
separately granted permission model.

---

## 1. Authentication and your first request

1. Sign in to the developer console (`https://platform.agroai-pilot.com`), add
   funds (prepaid, minimum $5), and create a LIVE key. Keys look like
   `agro_live_…`, carry the single scope `intelligence:run`, and are shown once.
2. Send `Authorization: Bearer $AGROAI_API_KEY` (or `X-API-Key`). Every paid
   request needs an `Idempotency-Key` header.

```bash
curl https://api.agroai-pilot.com/v1/intelligence \
  -H "Authorization: Bearer $AGROAI_API_KEY" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"task":"answer","question":"When does navel orangeworm pressure peak in almonds?"}'
```

```python
from agroai import AgroAI            # pip install ./sdk/python  (package: agroai-platform)

client = AgroAI()                     # reads AGROAI_API_KEY
result = client.intelligence.run("When does navel orangeworm pressure peak in almonds?")
print(result.decision, result.billing.charged_cents)
```

```ts
import { AgroAI } from "@agro-ai/platform";
const client = new AgroAI();          // reads AGROAI_API_KEY; server-side only
const result = await client.intelligence.run({ question: "When does navel orangeworm pressure peak in almonds?" });
```

The SDKs generate an idempotency key per call and reuse it on retries, so a
retried request is never charged twice.

## 2. The request

`POST /v1/intelligence` — every field except `question` is optional.

| Field | Purpose |
|---|---|
| `task` | Reasoning profile and price class: `answer`, `field_diagnosis`, `irrigation_plan`, `crop_risk`, `evidence_analysis`, `decision`, `report`, `integration_diagnosis`, `readiness_analysis`. Not a vertical: a finance, compliance or market app uses `decision`/`report`/`answer`. |
| `question` | Natural-language question or instruction (2–8,000 chars). |
| `context` | Typed agricultural context (§4). |
| `attachments` | Up to 8 uploaded file ids (§5). |
| `response_format` | `text` (default), a built-in schema, or your JSON Schema (§3). |
| `tools` | Deterministic capabilities to run first (§9). |
| `knowledge` | Collections to retrieve from (§7). |
| `session_id` | Carry bounded state across calls (§6). |
| `field_id`, `workspace_id` | Reference AGRO-AI Platform fields/workspaces your key may access. |
| `input` | Free-form JSON (the original v1 field; still supported). |
| `language` | Response language. |
| `metadata` | Up to 16 string tags echoed on the run and usage views. |
| `stream` | `true` for server-sent events (§10). |

The response keeps every original field (`id`, `status`, `decision`, `output`,
`confidence`, `risk_flags`, `missing_data`, `evidence`, `billing`) and adds:
`structured_output`, `structured_output_status`, `provenance`, `session`,
`usage`, `degraded_reasons`, `request_id`, `metadata`.

`status` is `completed` (charged) or `degraded` (answered with limitations,
**never charged**). A run is degraded when the runtime fell back, an attached
image could not be analysed, a tool failed, or a requested structured output
could not be produced validly.

## 3. Structured outputs

```python
result = client.intelligence.run(
    "Why are the lower leaves yellowing with concentric spots?",
    task="field_diagnosis",
    context={"crop": {"name": "tomato", "growth_stage": "fruit set"},
             "observations": [{"id": "scout_12", "type": "scouting_note", "value": "rings on lower leaves, 30% of plants"}]},
    response_format="diagnosis",
)
result.structured_output   # validated against the diagnosis schema
```

Built-in schemas (`GET /v1/intelligence/schemas/{name}` for the full JSON
Schema): `diagnosis`, `recommendations`, `risk_assessment`,
`irrigation_schedule`, `financial_projection`, `compliance_findings`,
`task_list`, `evidence_summary`.

Your own schema: `{"type": "json_schema", "name": "lender_summary", "schema": {...}}`
— JSON Schema draft 2020-12, root `type: object`, ≤ 32 KB, ≤ 12 levels.
`pattern`, `patternProperties`, dynamic and remote `$ref` are rejected (they
would execute caller regexes or reach outside the request).

Guarantees:

* `structured_output_status: "valid"` means the object passed validation. We
  never return malformed output as valid. After one repair attempt an invalid
  result is returned as `structured_output: null`, `status: "degraded"`, not
  charged, with `structured_output_errors`.
* Keys your closed schema does not allow are removed; nothing is invented.
* Any `evidence_ids` / `source_ids` / `citations` string that does not match
  evidence actually supplied to the run is removed and listed in
  `provenance.removed_unverifiable_citations`.

## 4. Agricultural context

`context` is a small, extensible domain model. Every section is optional; entity
objects accept extra attributes (`"rootstock": "Nemaguard"`); domain data with
no section goes in `extensions` under a namespaced key.

```json
{
  "operation":  {"name": "North Ranch", "type": "orchard", "area_ha": 120},
  "field":      {"id": "B7", "area_ha": 12, "soil": {"texture": "sandy loam", "ph": 6.8},
                 "irrigation_system": {"type": "drip", "flow_m3h": 60, "efficiency": 0.9},
                 "water_source": {"type": "district canal", "allocation_m3": 80000}},
  "crop":       {"name": "almond", "variety": "Nonpareil", "season": "2026", "growth_stage": "hull split"},
  "location":   {"latitude": 36.7, "longitude": -119.8, "region": "Fresno County", "country": "US",
                 "geometry": {"type": "Polygon", "coordinates": [[...]]}},
  "time_window":{"start": "2026-09-28T00:00:00Z", "end": "2026-10-05T00:00:00Z"},
  "observations": [{"id": "obs_vwc_1", "type": "soil_vwc", "value": 0.14, "unit": "m3/m3",
                    "observed_at": "2026-10-02T06:00:00Z", "source": "probe 3", "confidence": 0.9}],
  "weather":    {"source": "on-farm station", "series": [{"at": "2026-10-02T00:00:00Z", "tmax_c": 31, "tmin_c": 14, "et0_mm": 6.2}]},
  "issues":     [{"type": "pest", "name": "navel orangeworm", "severity": "medium"}],
  "treatments": [{"product": "…", "active_ingredient": "…", "rate": 0.2, "rate_unit": "L/ha", "applied_at": "…"}],
  "equipment":  [{"type": "tractor", "make": "…", "model": "…"}],
  "tasks":      [{"title": "Flush filters", "status": "open"}],
  "harvest":    {"expected_yield": 2.8, "yield_unit": "t/ha"},
  "financial":  {"currency": "USD", "price_per_unit": 2.1, "price_unit": "lb",
                 "costs": [{"category": "water", "amount": 300, "basis": "per_ha"}]},
  "market":     {"commodity": "almonds", "price": 2.1, "unit": "lb", "currency": "USD", "as_of": "2026-10-01T00:00:00Z"},
  "sources":    [{"id": "lab_2026_09", "type": "soil_lab", "label": "Ag lab report", "observed_at": "2026-09-15T00:00:00Z"}],
  "extensions": {"acme.contract": {"buyer": "co-op", "grade": "extra no. 1"}}
}
```

Give observations and sources an `id`: AGRO-AI cites them by id, reports their
age in `provenance.sources[].freshness_hours`, and validates structured
citations against them. Ids must be unique within a request and may not use
AGRO-AI prefixes (`tool_`, `ctx_obs_`, `chunk_`, `file_`, `doc_`, `ses_`,
`turn_`, `run_`) or UUIDs (422). If the supplied data exceeds the analysis
window, whole items are left out: they are marked `omitted_from_analysis` in
provenance and cannot be cited. Bounds: 256 KB per context, finite numbers, physical
ranges (e.g. latitude ±90, pH 0–14) enforced.

## 5. Files and multimodal input

```python
photo = client.intelligence.files.upload("leaf.jpg", content_type="image/jpeg")
lab   = client.intelligence.files.upload("soil_lab.pdf", content_type="application/pdf")
client.intelligence.run("Interpret the photo and lab report together.",
                        task="field_diagnosis", attachments=[photo.id, lab.id])
```

| Kind | Types | Max | How it is used |
|---|---|---|---|
| Image | JPEG, PNG, WebP | 8 MB | Analysed by AGRO-AI vision into visible facts and *hypotheses* (never a confirmed diagnosis) |
| Document | PDF (≤ 200 pages) | 15 MB | Text extracted; first 6,000 characters analysed per run (use knowledge for long documents) |
| Text | plain, CSV, Markdown, JSON (UTF-8) | 2 MB | As documents |

Not supported in v1: audio, video, remote URLs (AGRO-AI never fetches a URL you
send — no SSRF surface). Type is decided by content sniffing; a declared type
that disagrees is rejected (415). Files containing credentials or private keys
are rejected (422). Per project (all workspaces): at most 1,000 active files,
1 GB of stored images, and 25 million characters of extracted document text
(409 when exceeded). Files expire after 30 days; `DELETE /v1/intelligence/files/{id}`
removes them immediately. Original document bytes are not retained, only
bounded extracted text.

## 6. Sessions (state across calls)

```python
session = client.intelligence.sessions.create(
    title="Block 7 — 2026 season", context={"crop": {"name": "almond"}}, retention_days=30)
client.intelligence.run("Plan this week's irrigation.", task="irrigation_plan", session_id=session.id)
client.intelligence.run("And what if Thursday hits 40 °C?", session_id=session.id)  # sees the prior turn
client.intelligence.sessions.delete(session.id)                                      # hard-deletes turns now
```

A session holds pinned context you set explicitly (merged under each request's
own context, request sections win) and a bounded history written only by
completed runs: the latest 8 turns are used, at most 200 are stored, each
turn ≤ 4,000 characters. Sessions expire after `retention_days` (1–90) of
inactivity. Use sessions for state; use the request `context` for per-call data.

## 7. Knowledge (your organization's data)

```python
client.intelligence.knowledge.add(collection="agronomy-sops", title="Hull split irrigation SOP",
    text=open("sop.md").read(), external_id="sop-hullsplit", observed_at="2026-05-01T00:00:00Z",
    source={"type": "sop", "label": "Ranch SOP v4"})
result = client.intelligence.run("What does our SOP say about irrigating during hull split?",
                                 knowledge=["agronomy-sops"])
```

* Ingest text or an uploaded PDF/text file (`file_id`). Re-posting the same
  `external_id` refreshes the document (unchanged content is a no-op).
* Retrieval v1 is full-text search inside PostgreSQL (language-neutral,
  OR-matched terms with prefix matching). It is lexical, not semantic: use the
  words your documents use. A semantic index can be added behind the same API.
* Every retrieved passage is cited by chunk id with document, collection,
  source label and freshness. Deleting a document removes it from retrieval
  immediately. Limits: 1,000,000 characters per document; 2,000 documents and
  50 MB of text per project.
* `POST /v1/intelligence/knowledge/search` returns passages without running
  intelligence (not billed).

## 8. Async jobs

```python
job = client.intelligence.jobs.create("Write the season report for our lender.", task="report",
                                      knowledge=["season-2026"], response_format="financial_projection")
done = client.intelligence.jobs.wait(job.id)        # or poll GET /v1/intelligence/jobs/{id}
done.result.structured_output
```

States: `queued → running → completed | degraded | failed`, plus `canceled`
and `timeout`. Jobs are idempotent (same `Idempotency-Key` returns the same
job), executed exactly once by a leased worker, retried at most 3 times on
transient failure, re-authorized at execution time (a revoked key stops its
queued jobs), cancellable while queued or running, and charged only on
`completed`. Results are retained 30 days. Webhooks are not offered in v1; poll
or use the SDK `wait`.

## 9. Tools (deterministic capabilities)

```python
client.intelligence.tools.list()                    # schemas, scopes, side_effects="none"
client.intelligence.tools.execute("finance.crop_margin.v1", {
    "area_ha": 80, "expected_yield_per_ha": 7.5, "price_per_unit": 210, "currency": "EUR",
    "costs": [{"category": "seed", "amount": 95, "basis": "per_ha"}, {"category": "machinery", "amount": 42000}]})
client.intelligence.run("Is wheat on the south field profitable?", task="decision",
                        tools=[{"name": "finance.crop_margin.v1", "arguments": {...}}])
```

Registered tools: the FAO-56 / soil water / irrigation / phenology / nutrient /
evidence-quality / unit-conversion calculators (fail closed: missing inputs are
reported, never guessed), `finance.crop_margin.v1`, `knowledge.search.v1`,
`observations.query.v1`, `fields.get.v1`.

Every tool is declared with an input schema, requires `intelligence:run`, is
side-effect free, time-bounded, and audited on the run (name, version, status,
duration, argument hash — not your values). Tools run only when *you* request
them, never because model or document text asked, so prompt injection cannot
invoke them. Tool results enter the answer as cited evidence (`tool_1`, …).

## 10. Streaming

`"stream": true` returns `text/event-stream`:
`run.created` (with the run id) → `run.started` → `context.ready` →
`inference.started` → `structured_output.started` → `run.completed` |
`run.degraded` | `error`. Comment lines keep idle connections alive.

Streaming is stage-level in v1, not token-level. Validation, authorization and
balance errors are returned as normal HTTP errors before the stream opens. The
run belongs to the server: if you disconnect, it still finishes, is billed
exactly like a non-streamed run, and is retrievable at
`GET /v1/intelligence/runs/{id}` (or by replaying the same Idempotency-Key).

## 11. Pricing

Prepaid wallet, US dollars, charged only for `completed` runs.

| Task | Price |
|---|---|
| answer | $0.05 |
| field_diagnosis, crop_risk, integration_diagnosis, readiness_analysis | $0.15 |
| irrigation_plan | $0.20 |
| evidence_analysis, decision | $0.25 |
| report | $0.50 |

Add-ons: image attachment +$0.05, document attachment +$0.02, knowledge
retrieval +$0.01 per retrieval. Structured outputs, context, sessions, tools,
streaming and async are included. The exact quote is in
`billing.components`; it is fixed when the run is admitted. Tool execution,
knowledge search, file/knowledge/session management are not billed.

## 12. Errors, limits, observability

| Status | Meaning |
|---|---|
| 400/422 | Invalid request (schema, bounds, unknown tool, credential-like input) |
| 401 | Missing/invalid/revoked key |
| 402 | Insufficient balance (`required_cents`) |
| 403 | Key not allowed (scope, workspace restriction, test key, disabled project) |
| 404 | Not found — including any id belonging to another tenant |
| 409 | Idempotency key reused with a different request, or run still in progress |
| 413/415 | File too large / unsupported or mismatched type |
| 429 | Rate limited (`RateLimit-*`, `Retry-After`) |
| 503 | Temporarily unavailable (not charged; safe to retry with the same key) |

Every response carries `X-Request-Id`; include it in support requests.
`GET /v1/intelligence/usage` and `GET /v1/intelligence/runs` give per-task
volumes, charges, statuses and latency (`runs` pages with the opaque
`next_before` cursor). Keys with resource allow/deny lists see and cancel only
the runs, jobs and sessions they created, and only ground on evidence of
allowed fields. A run grounds on its own API project's evidence plus
organization-level evidence that belongs to no API project (portal uploads,
connectors) — never on another API project's records.

Workspace scope: a run is workspace-scoped when the key is workspace-bound,
the request sets `workspace_id`, or the referenced field belongs to a
workspace. A workspace-scoped run uses only that workspace's sessions, files,
knowledge and fields; project-wide resources (created by a project-wide key)
are not visible inside it, so its stored result can be read safely by that
workspace's keys. Fields must carry this API project's tag and, for a
workspace-scoped run, the same workspace — the same rules as
`/v1/platform/fields`. `GET /v1/intelligence/capabilities`
describes modalities, schemas, tools and limits.

## 13. Production recommendations

* Keep keys server-side; the SDKs refuse to run in a browser.
* Always send an Idempotency-Key you can reproduce (e.g. your own record id).
* Prefer typed `context` with ids over prose; cite-able evidence makes
  better and auditable answers.
* Use async jobs for reports and multi-attachment analyses; use streaming for
  interactive UIs.
* Treat outputs as decision support. Pesticide, nutrient and water decisions
  remain with qualified people and the product label/regulations.

---

## Examples: different applications, one platform

**Crop diagnostic assistant (mobile scouting app).** Upload the scout's photo,
pass crop + scouting note as `context`, `task: field_diagnosis`,
`response_format: "diagnosis"`. Render `likely_causes` with their
`evidence_ids`; show `limitations`.

**Irrigation intelligence (water-management SaaS).** Keep a session per block
with pinned field/system context; each morning send probe readings as
`observations` and ET₀ in `weather`, run `fao56.etc.single_kc.v1` and
`irrigation.gross_requirement.v1` as tools, and request
`irrigation_schedule`. Depths come from the tool results, not model arithmetic.

**Farm-finance intelligence (lender or FMIS).** Use
`finance.crop_margin.v1` with the farm's own costs and prices, add the
season's documents to a `knowledge` collection, and create an async job with
`task: report`, `response_format: "financial_projection"` for the credit memo.

**Pest-management decision support (agronomist tooling).** Pass scouting
counts as observations, prior applications in `treatments`, the label and
local guidance as knowledge, and ask for `recommendations`. AGRO-AI cites the
label passages it used and marks recommendations `requires_human_approval`;
it never issues application commands or rates beyond what the supplied label
evidence supports.

**Operations copilot (enterprise farm ops).** Index SOPs and maintenance logs
as knowledge, keep a session per manager, query `observations.query.v1` for
the latest field records, and request `task_list` for the day's work orders.

**Compliance / buyer-audit preparation.** Supply spray and harvest records in
`context.treatments` / `context.harvest`, the audit standard as knowledge, and
request `compliance_findings` (explicitly not legal advice).

---

## Versioning and compatibility

* `/v1` is stable. Changes inside `/v1` are additive only: new optional request
  fields, new response fields, new endpoints, new tools and schemas, new enum
  values in *response* fields. Clients must ignore unknown response fields.
* A request that does not use a new field behaves exactly as before — same
  prompt, same price, same idempotency hash (pre-platform runs replay
  unchanged).
* Breaking changes (removing/renaming fields, changing types or semantics,
  removing endpoints) require a new major path (`/v2`) and are not planned.
* Deprecation: a deprecated field or endpoint is marked in docs and OpenAPI,
  returns `Deprecation` and `Sunset` headers, and keeps working for at least
  12 months after the announcement.
* Responses carry `AGROAI-API-Version` (date of the contract revision).
* `agroai-intelligence-1` is a stable alias for AGRO-AI's intelligence
  behaviour. AGRO-AI improves models and routing behind it without changing
  the contract; a materially different behaviour would ship as a new alias
  (e.g. `agroai-intelligence-2`) alongside, never as a silent replacement of
  the response contract.
* Built-in schemas and tools are versioned by name (`…v1`); a changed tool
  ships as `…v2`.

## Architecture (for operators)

```
client ──► Cloudflare edge gateway ──► FastAPI (Render) ──► PostgreSQL (Neon)
                     │                      │   ├─ wallets/ledger, runs (sync+async), sessions,
                     │                      │   │  files, knowledge (+tsvector GIN)
                     │                      │   ├─ R2 object store (images, tenant-namespaced)
                     │                      │   └─ AGRO-AI runtime lanes (hidden from callers)
                     └── Cloudflare Queue ──┘  async jobs: outbox-style dispatch, hourly drain
```

No new infrastructure was introduced for v1: jobs use the existing Cloudflare
Queue/edge consumer and hourly maintenance drain, retrieval uses PostgreSQL
full-text search, images use the existing R2 store and field-vision runtime,
rate limiting uses the existing Redis limiter.
