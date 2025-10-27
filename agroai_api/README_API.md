# AGRO-AI API v1

Production-ready irrigation decision engine API. The neutral "brain" that OEMs, sensor platforms, and enterprise growers embed.

## Features

- **Decision Engine**: Water-balance recommender with idempotency and caching
- **Ingestion**: Telemetry and event data with late-arrival support
- **Compliance**: ROI reports and water budget tracking
- **Orchestration**: Controller integration via adapters (WiseConn, Rain Bird)
- **Webhooks**: Event notifications with HMAC signatures
- **Observability**: JSON logging, Prometheus metrics, request tracing
- **Multi-tenancy**: Tenant isolation with OAuth2 authentication

## Architecture

```
┌─────────────┐
│   Clients   │ (OEMs, Platforms, Growers)
└──────┬──────┘
       │ HTTPS + OAuth2
┌──────▼──────────────────────────┐
│      AGRO-AI API (FastAPI)      │
│  - Decision Engine              │
│  - Idempotency & Caching        │
│  - Webhooks & Metrics           │
└──────┬──────────────────────────┘
       │
┌──────▼──────┐    ┌──────────────┐
│  PostgreSQL │    │   Adapters   │
│  (or SQLite)│    │ WiseConn/RB  │
└─────────────┘    └──────────────┘
```

## Quick Start

### Local Development

```bash
# Clone and navigate
cd agroai_api

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env

# Initialize and seed database
python scripts/seed.py

# Run development server
make run
# or: uvicorn app.main:app --reload
```

API will be available at http://localhost:8000

- Docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Metrics: http://localhost:8000/metrics

### Docker

```bash
# Build and run
make docker-up
# or: docker-compose up --build

# View logs
make docker-logs

# Stop
make docker-down
```

## API Endpoints

### Decision API

**Compute Recommendation**
```http
POST /v1/blocks/{blockId}/recommendations:compute
Headers:
  Idempotency-Key: <unique-key>
  Authorization: Bearer <token>

Body:
{
  "constraints": {
    "min_duration_min": 30,
    "max_duration_min": 240,
    "preferred_time_start": "06:00"
  },
  "targets": {
    "target_soil_vwc": 0.35,
    "efficiency": 0.85
  },
  "horizon_hours": 72
}

Response: 200
{
  "when": "2024-01-15T06:00:00Z",
  "duration_min": 120,
  "volume_m3": 250.5,
  "confidence": 0.85,
  "explanations": [
    "Water deficit: 15.2mm",
    "Current soil VWC: 0.30",
    "Recent ET0: 5.5mm/day"
  ],
  "version": "rf-ens-1.0.0"
}
```

**Get Cached Recommendation**
```http
GET /v1/blocks/{blockId}/recommendations?date=2024-01-15

Response: 200 (or 404 if not found)
```

**Simulate Scenario**
```http
POST /v1/scenarios:simulate

Body:
{
  "block_ids": ["block-001", "block-002"],
  "horizon_hours": 72,
  "constraints": {...},
  "overrides": {
    "block-002": {
      "targets": {"target_soil_vwc": 0.40}
    }
  }
}

Response: 200
{
  "scenario_id": "uuid",
  "recommendations": {
    "block-001": {...},
    "block-002": {...}
  },
  "total_volume_m3": 500.5
}
```

### Ingestion

**Ingest Telemetry**
```http
POST /v1/blocks/{blockId}/telemetry

Body:
{
  "records": [
    {
      "type": "soil_vwc",
      "timestamp": "2024-01-15T10:00:00Z",
      "value": 0.32,
      "unit": "m3/m3",
      "source": "sensor-001"
    }
  ]
}

Response: 202
{
  "accepted": 1,
  "rejected": 0
}
```

**Ingest Events**
```http
POST /v1/blocks/{blockId}/events

Body:
{
  "records": [
    {
      "type": "irrigation_start",
      "timestamp": "2024-01-15T06:00:00Z",
      "data": {"zone": "zone-1"},
      "source": "controller-001"
    }
  ]
}

Response: 202
```

### Compliance & ROI

**ROI Report**
```http
GET /v1/reports/roi?from=2024-01-01&to=2024-12-31&blockId=block-001

Response: 200
{
  "block_id": "block-001",
  "period_start": "2024-01-01",
  "period_end": "2024-12-31",
  "water_saved_m3": 1250.5,
  "energy_saved_kwh": 500.2,
  "cost_saved_usd": 1937.50,
  "yield_delta_pct": 2.5,
  "baseline_method": "historical_average"
}
```

**Water Budget**
```http
GET /v1/blocks/{blockId}/water-budget

Response: 200
{
  "block_id": "block-001",
  "allocated_m3": 5000.0,
  "used_m3": 3250.5,
  "remaining_m3": 1749.5,
  "utilization_pct": 65.01
}
```

### Orchestration

**Apply Controller Command**
```http
POST /v1/controllers/{controllerId}:apply?provider=wiseconn

Body:
{
  "start_time": "2024-01-15T06:00:00Z",
  "duration_min": 120,
  "zone_ids": ["zone-1", "zone-2"]
}

Response: 202
{
  "schedule_id": "uuid",
  "status": "pending",
  "provider": "wiseconn",
  "provider_schedule_id": "wc-abc123"
}
```

**Cancel Schedule**
```http
POST /v1/schedules/{scheduleId}:cancel

Response: 200
{
  "schedule_id": "uuid",
  "status": "cancelled",
  "cancelled_at": "2024-01-15T10:30:00Z"
}
```

### Webhooks

**Register Webhook**
```http
POST /v1/webhooks

Body:
{
  "url": "https://your-app.com/webhook",
  "event_types": ["recommendation.created", "irrigation.started"]
}

Response: 201
{
  "id": "uuid",
  "url": "https://your-app.com/webhook",
  "event_types": ["recommendation.created"],
  "active": true,
  "created_at": "2024-01-15T10:00:00Z"
}
```

**Test Webhook**
```http
POST /v1/webhooks/test

Response: 200
{
  "event_id": "uuid",
  "event_type": "test.event",
  "payload": {...},
  "signature": "sha256=abc123...",
  "timestamp": "2024-01-15T10:00:00Z"
}
```

**Webhook Event Format**
```json
{
  "id": "event-uuid",
  "type": "recommendation.created",
  "timestamp": "2024-01-15T06:00:00Z",
  "data": {
    "recommendation_id": "rec-uuid",
    "block_id": "block-001",
    "when": "2024-01-15T06:00:00Z",
    "duration_min": 120,
    "volume_m3": 250.5
  },
  "tenant_id": "tenant-001"
}
```

Verify signature:
```python
import hmac
import hashlib

def verify_signature(payload: str, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

## Authentication

OAuth2 client credentials flow (stub implementation for demo):

```http
Headers:
  Authorization: Bearer <token>
```

Token payload should include `tenant_id`:
```json
{
  "tenant_id": "your-tenant-id",
  "exp": 1234567890
}
```

For demo/dev, authentication is stubbed to use "demo-tenant".

## Idempotency

Use `Idempotency-Key` header for safe retries:

```http
POST /v1/blocks/{blockId}/recommendations:compute
Headers:
  Idempotency-Key: request-123-abc
```

Same key + body → same response for 24 hours.

## Caching

Recommendations cached for 6 hours based on:
- Block ID
- Horizon hours
- Feature hash (telemetry state)

Cache automatically invalidates when features change.

## Metrics

Prometheus metrics at `/metrics`:

- `agroai_recommendations_total{tenant, status}`
- `agroai_compute_latency_seconds` (histogram)
- `agroai_idempotency_hits_total`
- `agroai_ingestion_total{tenant, type}`
- `agroai_webhooks_sent_total{tenant, event_type, status}`

## Data Model

**Core Entities:**
- `tenants` - Customer accounts
- `clients` - OAuth2 clients
- `blocks` - Fields/zones
- `telemetry` - Sensor data (soil_vwc, et0, weather, flow, valve_state)
- `events` - System events
- `recommendations` - Computed irrigation decisions
- `schedules` - Controller schedules
- `webhooks` - Event subscriptions
- `usage_metering` - Billing data
- `audit_logs` - Audit trail

## Testing

```bash
# Run all tests
make test

# Run with coverage
make coverage

# Run acceptance tests only
pytest tests/acceptance/ -v

# Lint and type check
make lint
make type
```

## Development

```bash
# Format code
make format

# Run quality checks
make quality

# Clean artifacts
make clean
```

## Deployment

### Environment Variables

Required:
```bash
DATABASE_URL=postgresql://user:pass@host:5432/agroai
SECRET_KEY=<strong-secret-min-32-chars>
WEBHOOK_SECRET=<webhook-signing-secret>
```

Optional:
```bash
LOG_LEVEL=INFO
ENABLE_METRICS=true
ENABLE_WEBHOOKS=true
CACHE_TTL_HOURS=6
IDEMPOTENCY_TTL_HOURS=24
```

### Production Checklist

- [ ] Set strong `SECRET_KEY` and `WEBHOOK_SECRET`
- [ ] Use PostgreSQL (not SQLite)
- [ ] Configure CORS allowed origins
- [ ] Set up OAuth2 authentication provider
- [ ] Enable HTTPS/TLS
- [ ] Configure monitoring (Prometheus/Grafana)
- [ ] Set up log aggregation
- [ ] Configure backup strategy
- [ ] Review rate limiting needs
- [ ] Set up alerts for metrics

## Assumptions

Based on the specification, the following design decisions were made:

1. **Authentication**: Stub OAuth2 implementation for demo. Production requires integration with identity provider (Auth0, Keycloak, etc.)

2. **Database**: SQLite for development, PostgreSQL for production. Migrations via SQLAlchemy.

3. **Baseline Algorithm**: Water balance method using ET0, rainfall, and soil VWC. Pluggable interface allows model upgrades.

4. **Adapters**: Mock implementations for WiseConn and Rain Bird. Real implementations require API credentials and documentation.

5. **ROI Calculation**: Simplified baseline (20% over actual usage). Production should use historical data or industry benchmarks.

6. **Metering**: Records all billable operations. Integration with billing system (Stripe, etc.) is external.

7. **Webhooks**: Retry 3 times with exponential backoff. Disable after 10 consecutive failures.

8. **Feature Cache**: 6-hour TTL based on telemetry features. Longer TTL may be appropriate for stable conditions.

9. **Telemetry Types**: Fixed set (soil_vwc, et0, weather, flow, valve_state). Extensible via metadata field.

10. **Time Zones**: All timestamps in UTC. Client responsible for local time conversion.

## Support

For issues, questions, or feature requests, contact the AGRO-AI team.

## License

Proprietary - AGRO-AI
