# WiseConn Integration — Implementation Notes

## What Was Built

A production-quality WiseConn connector integrated into the AGRO-AI backend, replacing the previous mock adapter with a real HTTP client that supports:

1. **Authentication** — API key auth with automatic header variant detection
2. **Discovery** — Farm → Zone → Measure entity hierarchy
3. **Telemetry Read** — Historical and current soil moisture, weather, and sensor data
4. **Irrigation Read** — Historical irrigation events
5. **Irrigation Write** — Create irrigation actions via API
6. **Canonical Mapping** — WiseConn entities normalized into AGRO-AI domain models
7. **Persistence** — Idempotent ingestion into Telemetry, Block, and Schedule tables
8. **API Endpoints** — REST endpoints under `/v1/wiseconn/` for all operations
9. **Validation Script** — Standalone CLI tool to prove end-to-end integration

## Files Created or Modified

| File | Action | Purpose |
|------|--------|---------|
| `app/core/config.py` | Modified | Added WISECONN_API_KEY, timeout, retry settings |
| `app/adapters/base.py` | Modified | Added DataProviderAdapter interface (read path) |
| `app/adapters/wiseconn.py` | Rewritten | Full HTTP client with retries, mapping, error handling |
| `app/adapters/registry.py` | Rewritten | Registry now creates real WiseConn adapter with API key |
| `app/schemas/wiseconn.py` | Created | Raw API schemas, canonical models, normalization maps |
| `app/services/wiseconn_sync.py` | Created | Sync orchestrator: discover, ingest, normalize, persist |
| `app/api/v1/wiseconn.py` | Created | REST endpoints for all WiseConn operations |
| `app/main.py` | Modified | Wired WiseConn router into FastAPI app |
| `scripts/wiseconn_demo.py` | Created | End-to-end validation script |
| `tests/unit/test_wiseconn.py` | Created | 25+ tests covering schemas, mapping, HTTP, flow |
| `.env.example` | Modified | Added WiseConn credential placeholders |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/wiseconn/auth` | Check authentication |
| GET | `/v1/wiseconn/discover` | Full farm→zone→measure discovery |
| GET | `/v1/wiseconn/farms` | List farms |
| GET | `/v1/wiseconn/farms/{id}/zones` | List zones for farm |
| GET | `/v1/wiseconn/zones/{id}/measures` | List measures for zone |
| GET | `/v1/wiseconn/measures/{id}/data` | Get time-series data |
| GET | `/v1/wiseconn/zones/{id}/irrigations` | List irrigation history |
| POST | `/v1/wiseconn/ingest` | Ingest telemetry into AGRO-AI |
| POST | `/v1/wiseconn/irrigations` | Create test irrigation |
| POST | `/v1/wiseconn/sync` | Full sync (discover + ingest all) |

## WiseConn API Assumptions

The WiseConn developer docs at developers.wiseconn.com were not accessible (403). These assumptions are derived from the wiseconn-node library and common ag-IoT REST patterns. **Each is isolated in code and will produce clear errors if wrong.**

| Assumption | Source | Isolated In |
|-----------|--------|-------------|
| Base URL: `https://api.wiseconn.com` | Default, configurable via env | `config.py` |
| Auth: `api_key` header | wiseconn-node library | `wiseconn.py:_auth_headers()` + auto-detection |
| Entity path: `/farms`, `/farms/{id}/zones`, etc. | REST convention | `wiseconn.py` GET methods |
| Time params: `initTime`/`endTime` in `yyyy/MM/dd HH:mm` | wiseconn-node library | `wiseconn.py:WC_DATE_FMT` |
| Irrigation creation: POST to `/zones/{id}/irrigations` | REST convention | `wiseconn.py:create_irrigation()` |
| Response format: JSON with camelCase keys | Common for JS-origin APIs | `wiseconn.py` schema aliases |

The `check_auth()` method automatically tries 4 auth header variants (`api_key`, `apikey`, `x-api-key`, `Authorization: Bearer`) and reconfigures the client when one works.

## How to Run

### Validation Script
```bash
cd agroai_api
export WISECONN_API_KEY="your-key"
export WISECONN_API_URL="https://api.wiseconn.com"  # adjust if different
python -m scripts.wiseconn_demo
python -m scripts.wiseconn_demo --skip-write  # read-only
python -m scripts.wiseconn_demo --output report.json
```

### Tests
```bash
cd agroai_api
pytest tests/unit/test_wiseconn.py -v
```

### API (local)
```bash
cd agroai_api
WISECONN_API_KEY="your-key" uvicorn app.main:app --reload
# Then: curl http://localhost:8000/v1/wiseconn/auth
```

## What Remains Blocked

1. **WiseConn API base URL** — Assumed `https://api.wiseconn.com`. Need confirmation from Francisco Jaure or the docs.
2. **Auth header name** — Auto-detection built in, but need to confirm which header WiseConn expects.
3. **Exact endpoint paths** — Built from REST conventions. If WiseConn uses different paths (e.g., `/api/v1/farms` instead of `/farms`), the adapter will get 404s and we adjust.
4. **Irrigation create payload shape** — Assumed `{start, minutes}`. May need `{startTime, duration}` or other keys.
5. **Pagination** — Not yet implemented. If WiseConn paginates large result sets, we need to add cursor/offset handling.
6. **Rate limits** — Unknown. The adapter has retry with exponential backoff but no proactive rate limiting.
7. **Webhook support** — Designed for but not implemented. The adapter abstraction supports adding webhooks without rewriting the core.

## Next Steps for Production

1. **Get live credentials** → Run `scripts/wiseconn_demo.py` → Adjust any wrong assumptions
2. **Confirm base URL and auth** → Update `config.py` defaults if different
3. **Confirm endpoint paths** → The first 404 will tell us what to fix
4. **Add pagination** → Once we see real response shapes
5. **Add webhook receiver** → For real-time data push from WiseConn
6. **Production tenant mapping** → Replace DEMO_TENANT_ID with real tenant onboarding
7. **Recommendation wiring** → The Recommender already reads from Telemetry table; once we ingest WiseConn data, recommendations work automatically
8. **Monitoring** → Add Prometheus metrics for sync latency, error rates, data freshness

## Security Notes

- API key is never logged (only first 4 chars shown at startup)
- API key is never committed (loaded from env var)
- Write operations default to minimal impact (1 minute, 24h offset)
- All WiseConn errors are caught and logged without leaking credentials
- The demo environment is shared — writes are intentionally conservative
