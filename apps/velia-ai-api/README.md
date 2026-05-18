# Velia AI API (v0.1)

Backend companion for `apps/velia-mobile`.

## Run locally

```bash
cd apps/velia-ai-api
npm install
npm run dev
```

API base URL defaults to `http://localhost:4310`.

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
- `LLM_PROVIDER` (default `mock`)
- `EMBEDDING_PROVIDER` (default `mock`)
- `WEATHER_PROVIDER` (default `mock`)
- `TRANSLATION_PROVIDER` (default `mock`)
- `VECTOR_PROVIDER` (default `memory`)
- `MEMORY_FILE` (default `./src/storage/memory.json`)

## Tests

```bash
cd apps/velia-ai-api
npm test
```
