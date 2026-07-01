# Velia AI API (Real Intelligence v1 foundation)

Backend companion for `apps/velia-mobile`.

## Run locally

```bash
cd apps/velia-ai-api
npm install
npm run dev
```

API base URL defaults to `http://localhost:4310`.

Copy `.env.example` to `.env` for local configuration. If no provider keys are set, Velia runs in local deterministic fallback mode.

## Endpoints

- `POST /v1/decisions/daily`
- `POST /v1/assistant/query`
- `POST /v1/voice/interpret`
- `POST /v1/weather/context`
- `POST /v1/memory/update`
- `POST /v1/evaluation/run`

## Environment variables

- `PORT` (default `4310`)
- `CORS_ORIGIN` (default `*`)
- `LOG_LEVEL` (default `info`)
- `LLM_PROVIDER`: `mock`, `gemini`, `openai`, or `anthropic` placeholder
- `GEMINI_API_KEY`, `GEMINI_MODEL`
- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `EMBEDDING_PROVIDER`: `mock`, `gemini`, or `openai`
- `GEMINI_EMBEDDING_MODEL` (default `gemini-embedding-2`), `OPENAI_EMBEDDING_MODEL`
  - `gemini-embedding-2`: uses text prefixes (`title: … | text: …` for documents; `task: search result | query: …` for retrieval); does not send `taskType` field
  - `text-embedding-004` and earlier: uses `taskType` field in request body
- `WEATHER_PROVIDER`: `mock` or `openweather`
- `OPENWEATHER_API_KEY`
- `TRANSLATION_PROVIDER` (default `mock`)
- `VECTOR_PROVIDER` (default `local`)
- `MEMORY_PROVIDER` (default `json`)
- `MEMORY_FILE` (default `<app-root>/src/storage/memory.json`, absolute path derived from module location — not cwd-dependent)
- `VECTOR_INDEX_FILE` (default `<app-root>/src/storage/vector-index.json`)
- `WEATHER_CACHE_FILE` (default `<app-root>/src/storage/weather-cache.json`)
- `PROVIDER_TIMEOUT_MS`, `PROVIDER_RETRY_COUNT`

Provider API keys are backend-only. Do not place these values in `apps/velia-mobile`, service worker code, static HTML, or frontend local storage.

## Intelligence pipeline

`irrigationDecisionAgent` builds a hybrid recommendation in layers:

1. Normalize field, log, observation, weather, and memory context
2. Calculate deterministic water-pressure signals (`deterministicIrrigation.js`)
3. Score evidence quality independently via `confidenceEngine.js` (evidence-based, not need-score-derived)
4. Retrieve local RAG knowledge from `knowledge/*.json`
5. Call Gemini or OpenAI for strict structured JSON when configured
6. Retry malformed model output once with a repair instruction
7. Fall back to deterministic logic when providers are unavailable
8. Apply safety guardrails and return decision with provenance

**Deterministic safety is fully authoritative.** The model may explain reasoning, identify uncertainty, or choose field checks — but it cannot escalate to "irrigate" unless the deterministic engine also permits it. Specific blocking rules (frost risk, rain forecast, wet observation, recent irrigation) are checked before the generic authority block so their named guardrail keys are always recorded.

**Confidence scoring is evidence-quality based**, not need-score derived. `confidenceEngine.scoreEvidence()` scores 11 evidence dimensions (weather freshness, crop type, soil type, irrigation method, field coordinates, irrigation log, recent observation, soil moisture sensor, irrigation controller, ET source, satellite evidence) and detects conflicting signals. This gives an honest representation of what the system actually knows.

**Agronomic guardrails** block 9 prohibited claim types: exact soil moisture, satellite evidence, exact ET values, exact duration, exact application volume, verified water savings, guaranteed yield, unverified water-savings percentages, and specific stress-index values.

## Evaluation

40 executable evaluation fixtures test the deterministic engine end-to-end:

```bash
npm run eval
```

Fixtures cover high heat, frost risk, wet field, dry field, expected rain, stale weather, missing crop/soil/method, recent irrigation, no history, sensor conflicts, controller unavailable, low/high confidence, offline fallback, conflicting signals, unsupported ET/satellite/duration claims, boundary values, and more.

## Smoke tests (live providers only)

```bash
npm run smoke:llm        # requires GEMINI_API_KEY or OPENAI_API_KEY
npm run smoke:embedding  # requires EMBEDDING_PROVIDER + key
npm run smoke:weather    # requires OPENWEATHER_API_KEY
```

Smoke tests fail clearly when credentials are not configured and never log keys or prompts.

## CI

GitHub Actions runs on push to `main`, `claude/**`, `codex/**`, and PRs to `main`:
- Syntax check all source files
- Backend tests with mocked providers (no secrets required)
- Evaluation harness (40 fixtures)
- Mobile syntax check and tests

## Boot sequence

`server.js` explicitly awaits optional dotenv loading before any config properties are read:

1. `loadDotenv()` — resolves `dotenv/config` in two steps (resolve then import). If dotenv/config is absent, the step is skipped silently. Transitive dependency errors and module-evaluation failures propagate. Config-dependent modules use lazy singletons so env-var overrides remain effective even when set via `.env`.
2. Express app is created; if unavailable, the process falls back to a built-in Node.js handler that serves the same API surface.

## Local persistence (development only)

Development storage defaults resolve relative to `apps/velia-ai-api/src/storage/` regardless of the shell's working directory. Use the env-var overrides to relocate them.

JSON files written in development:

- memory events and recurring patterns (`MEMORY_PROVIDER=json`)
- local vector index (`VECTOR_PROVIDER=local`)
- weather cache

These files are git-ignored. `MemoryProvider` is an interface — production should migrate to Postgres with tenant-scoped tables; vector search to `pgvector` or a managed vector database. The JSON implementation is labelled dev-only and is not suitable for multi-tenant or production use.

## Privacy expectations

Live LLM and embedding calls send structured field context to the selected backend provider. Logs record provider mode and model name only; prompts, API keys, and farm data are not logged.

## Tests

```bash
cd apps/velia-ai-api
npm test        # 32 tests (intelligence + routes)
npm run eval    # 40 evaluation fixtures
```
