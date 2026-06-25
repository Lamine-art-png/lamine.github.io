# AGRO-AI • Manulife Pilot Kit (One-Region)

This is a drop-in starter to make a **limited pilot** reproducible:
- **Terraform (AWS)**: ECS Fargate API + RDS Postgres + S3 (raw/models) + CloudWatch + Secrets Manager + ECR.
- **CI/CD (GitHub Actions)**: Lint/Test → Docker Build/Push → Terraform Plan/Apply via OIDC.
- **RBAC & Secrets**: Tenant-scoped roles (`owner`, `analyst`) with API keys; per-tenant secrets in Secrets Manager.
- **Runbooks**: Incident & DR with RTO/RPO targets and evidence checklist.
- **SOC 2 Matrix**: Minimal controls mapped to TSC with compensating controls.
- **Data & Model**: Batch ingestion, retraining, evaluation (MAE/R²), feature importance, bias stub, KPI report template.

> Assumptions: AWS account in `us-west-1` (N. California), OIDC to GitHub, Dockerized API (e.g., FastAPI).


## AGRO-AI Water Command Center

- **AGRO-AI Portal:** https://app.agroai-pilot.com
- **AGRO-AI API:** https://api.agroai-pilot.com
- **Water Command Center:** Enterprise customer portal for connected controller environments, live context assembly, irrigation recommendations, execution tracking, verification, integrations, reports, audit log, and administration placeholders.

## Quickstart
```bash
make tfinit
make tfplan
make tfapply
```

## Evidence Pack
- `terraform.plan.txt`, `terraform.apply.txt` (from CI)
- CloudWatch alarm screenshots, RDS snapshots, Secrets rotation events
- `data/processed/evaluation.json`, `feature_importance.csv`, `bias_report.json`
- `ops/runbooks/*.md` (export PDF)
<!-- trigger deploy -->

## AGRO-AI Intelligence Engine

The FastAPI backend includes a provider-agnostic AI gateway for AGRO-AI
Intelligence routes. It does not hardcode paid model providers. Configure any
OpenAI-compatible chat-completions endpoint or a local Ollama runtime.

Recommended free/local development:

```bash
AI_PROVIDER=ollama
AI_BASE_URL=http://localhost:11434
AI_MODEL=qwen3:8b
# or AI_MODEL=deepseek-r1:8b
```

Recommended serious hosted inference:

```bash
AI_PROVIDER=openai_compatible
AI_BASE_URL=<provider base URL>
AI_API_KEY=<key>
AI_MODEL=<model name>
AI_TIMEOUT_SECONDS=30
```

If AI variables are unset, the API still starts and returns a clearly marked
`unavailable`/demo fallback response. Production AI requires either hosted
inference or GPU-backed self-hosting. Do not place model API keys in frontend
code.


## Velia AI backend + mobile wiring

- Backend app: `apps/velia-ai-api` (Express).
- Mobile app: `apps/velia-mobile` calls backend-first APIs with local fallback for weather, daily decisions, assistant responses, and voice interpretation.
- Velia Real Intelligence v1 adds backend-only Gemini/OpenAI reasoning adapters, Gemini/OpenAI embeddings, OpenWeather weather retrieval, local RAG ingestion, JSON memory, provenance, guardrails, and deterministic fallback.
- Do not put provider keys in frontend code. Configure `apps/velia-ai-api/.env` from `.env.example`.

### Backend quick run

```bash
cd apps/velia-ai-api
npm install
cp .env.example .env
npm run dev
```

Optional live providers:

- `LLM_PROVIDER=gemini` with `GEMINI_API_KEY`
- `LLM_PROVIDER=openai` with `OPENAI_API_KEY`
- `EMBEDDING_PROVIDER=gemini|openai`
- `WEATHER_PROVIDER=openweather` with `OPENWEATHER_API_KEY`

Without keys, Velia stays in local deterministic/mock fallback mode.

### Backend tests

```bash
cd apps/velia-ai-api
npm test
```

### Mobile quick run

```bash
cd apps/velia-mobile
python -m http.server 4174
```

Then open `http://localhost:4174`.
