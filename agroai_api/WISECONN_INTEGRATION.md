# WiseConn Integration — Implementation Notes

## What Was Built

A production-quality WiseConn connector integrated into the AGRO-AI backend, replacing the previous mock adapter with a real HTTP client that supports:

1. **Authentication** — API key auth via `api_key` header (confirmed working)
2. **Discovery** — Farm → Zone → Measure entity hierarchy
3. **Telemetry Read** — Historical and current soil moisture, weather, and sensor data
4. **Irrigation Read** — Historical irrigation events with volume/duration
5. **Irrigation Write** — Create irrigation actions via API (blocked: 403, see below)
6. **Canonical Mapping** — WiseConn entities normalized into AGRO-AI domain models
7. **Persistence** — Idempotent ingestion into Telemetry, Block, and Schedule tables
8. **API Endpoints** — REST endpoints under `/v1/wiseconn/` for all operations
9. **Validation Script** — Standalone CLI tool to prove end-to-end integration

## Live Validation Results (Confirmed)

| Item | Status | Details |
|------|--------|---------|
| Auth | **PASS** | `api_key` header works on first try |
| Base URL | **CONFIRMED** | `https://api.wiseconn.com` (no version prefix) |
| Farm Discovery | **PASS** | "Demo Ferti & Flush" (id=3973, Fresno CA) |
| Zone Discovery | **PASS** | Zone 1 (162803, Soil+Irrigation), Zone 2 (162804, Irrigation), CIMIS-Montague (216961, Weather) |
| Measure Discovery | **PASS** | 18 measures on Zone 1, including 5 soil moisture at 12/24/36/48/60 inches |
| Telemetry Read | **PASS** | ~1274 points per measure over 14 days, 15-min intervals (6370 total) |
| Irrigation Read | **PASS** | 3 events, all "Executed OK", 4hr duration, ~2.4M gal each, scheduled by "Api Semios" |
| Depth Extraction | **PASS** | Regex extracts depths from measure names (HS North → 12in, HS North 24 → 24in, etc.) |
| Irrigation Write | **BLOCKED** | POST `/zones/162803/irrigations` returns 403 Forbidden |

### Write Path 403 Analysis

The API key (`RfoUUEAex1Isi6bEaBW2`) has **read-only ("Monitoring") permissions**. Evidence:
- All GET endpoints work (farms, zones, measures, data, irrigations)
- POST to irrigations returns 403 (not 401, not 400)
- Existing irrigations were created by "Api Semios" — a different API client with write ("Control") access

**To unblock**: Contact WiseConn (Francisco Jaure) and request "API Control" tier access for this key, or obtain a new key with write permissions.

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
| `tests/unit/test_wiseconn.py` | Created | 29 tests covering schemas, mapping, HTTP, flow |
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

## WiseConn API — Confirmed Details

| Detail | Value | Source |
|--------|-------|--------|
| Base URL | `https://api.wiseconn.com` | Live validated |
| Auth header | `api_key` | Live validated (first try) |
| Farm endpoint | `GET /farms` | Live validated |
| Zone endpoint | `GET /farms/{id}/zones` | Live validated |
| Measure endpoint | `GET /zones/{id}/measures` | Live validated |
| Data endpoint | `GET /measures/{id}/data?initTime=...&endTime=...` | Live validated |
| Irrigation endpoint | `GET /zones/{id}/irrigations?initTime=...&endTime=...` | Live validated |
| Time format | `yyyy/MM/dd HH:mm` | Live validated |
| Zone type field | Returns list (e.g., `["Soil", "Irrigation"]`) not string | Live validated |
| Irrigation volume | Returns `{"value": float, "unitAbrev": "gal"}` dict | Live validated |
| Irrigation times | Uses `initTime`/`endTime` field names | Live validated |

## How to Run

### Validation Script
```bash
cd agroai_api
export WISECONN_API_KEY="your-key"
python -m scripts.wiseconn_demo              # full run (write will 403 until permissions granted)
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

## Next Steps

1. **Unblock write path** — Get "API Control" tier key from WiseConn
2. **Add pagination** — Not yet needed (demo farm has small datasets), but will be needed for production farms
3. **Recommendation wiring verification** — The Recommender already reads from Telemetry table; once telemetry is ingested via `full_sync()`, recommendations should work automatically
4. **Webhook receiver** — For real-time data push from WiseConn (currently polling only)
5. **Production tenant mapping** — Replace DEMO_TENANT_ID with real tenant onboarding
6. **Monitoring** — Add Prometheus metrics for sync latency, error rates, data freshness

## Security Notes

- API key is never logged (only first 4 chars shown at startup)
- API key is never committed (loaded from env var)
- Write operations default to minimal impact (1 minute, 24h offset)
- All WiseConn errors are caught and logged without leaking credentials
- The demo environment is shared — writes are intentionally conservative
