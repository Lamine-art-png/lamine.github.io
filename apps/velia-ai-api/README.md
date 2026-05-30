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
- `GEMINI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_MODEL`
- `WEATHER_PROVIDER`: `mock` or `openweather`
- `OPENWEATHER_API_KEY`
- `TRANSLATION_PROVIDER` (default `mock`)
- `VECTOR_PROVIDER` (default `local`)
- `MEMORY_PROVIDER` (default `json`)
- `MEMORY_FILE` (default `./src/storage/memory.json`)
- `VECTOR_INDEX_FILE` (default `./src/storage/vector-index.json`)
- `WEATHER_CACHE_FILE` (default `./src/storage/weather-cache.json`)
- `PROVIDER_TIMEOUT_MS`, `PROVIDER_RETRY_COUNT`

Provider API keys are backend-only. Do not place these values in `apps/velia-mobile`, service worker code, static HTML, or frontend local storage.

## Intelligence pipeline

`irrigationDecisionAgent` now builds a hybrid recommendation:

- normalizes field, log, observation, weather, and memory context
- retrieves weather from OpenWeather when configured, with cached stale fallback
- calculates deterministic water-pressure signals and safety rules
- retrieves local RAG knowledge from `knowledge/*.json`
- calls Gemini or OpenAI for strict structured JSON when configured
- retries malformed model output once with a repair instruction
- falls back to deterministic logic when providers are unavailable
- applies guardrails and returns provenance

The deterministic layer remains authoritative for safety constraints. The model may explain, identify uncertainty, and choose field checks, but it must not invent sensor data, exact soil moisture, weather, satellite evidence, yield guarantees, or water-savings guarantees.

## Local persistence

Development mode uses JSON files under `src/storage/`:

- memory events and recurring patterns
- local vector index
- weather cache

These files are ignored by git. Production should migrate memory to Postgres with tenant-scoped tables, and vector search to Postgres + `pgvector` or a managed vector database.

## Privacy expectations

Live LLM and embedding calls send structured field context to the selected backend provider. Logs record provider mode and model name only; prompts, API keys, and farm data are not logged.

## Tests

```bash
cd apps/velia-ai-api
npm test
```

In the Codex desktop runtime used for this build, `npm` was not available on PATH. The equivalent direct command used was:

```bash
/Applications/Codex.app/Contents/Resources/node --test src/tests/*.test.js
```
