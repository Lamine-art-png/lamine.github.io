# AGRO-AI API - Architecture & Development Guidelines

## Overview

AGRO-AI is a production-grade irrigation intelligence platform designed for enterprise deployments (500+ acre operations). The system uses a "file-drop + cloud connectors, everything else in batch" architecture optimized for reliability, auditability, and minimal operational overhead.

## Architecture Principles

### 1. Data Ingestion Strategy
- **Batch-First**: All data ingestion happens in scheduled batches, never real-time streaming
- **Multi-Source**: Support local file-drop directories, S3 buckets, and Azure Blob containers
- **Transform-Then-Load**: Validate and transform sensor data before persisting
- **Audit Everything**: Every ingestion attempt is logged with source, checksum, row counts, and status

### 2. Model Lifecycle
- **Registry-Based**: All ML models stored in versioned registry (filesystem, S3, or Azure)
- **Metadata-Driven**: Training runs tracked with dataset hashes, hyperparameters, metrics
- **Promotion Workflow**: Models promoted through stages: training → pilot → production
- **Reproducibility**: Every recommendation includes model version for audit trails

### 3. Tenant & Security Model
- **Tenant Isolation**: Row-level security on all data (tenant_id on every table)
- **API Key Scoping**: Each key scoped to tenant + optional field restrictions
- **RBAC-Ready**: Owner/Analyst/Viewer roles (API key-backed for now, JWT-ready)
- **Audit Logs**: All credential operations (create, rotate, revoke) logged

### 4. Database & Migrations
- **Alembic-Based**: All schema changes via versioned migrations
- **No create_all**: Database.migrate() replaces Base.metadata.create_all()
- **Rollback Support**: Every migration tested for forward + backward compatibility
- **Seed Through Migrations**: scripts/seed.py uses migration layer

## Security Requirements

### Rate Limiting
- **All Routes**: RateLimiterDependency on all endpoints except /metrics and /health
- **Tenant-Aware**: Limits per tenant_id (100 req/min default, configurable)
- **Burst Handling**: Token bucket algorithm with 2x burst capacity

### Authentication
```python
# Every protected endpoint
@router.post("/recommendations")
async def compute(
    tenant_id: str = Depends(get_current_tenant),  # From API key
    rate_limit: None = Depends(RateLimiterDependency(limit=100)),
    db: Session = Depends(get_db)
):
    ...
```

### Structured Logging
```python
# Every log entry must include
logger.info(
    "action_description",
    extra={
        "tenant_id": tenant_id,
        "field_id": field_id,
        "request_id": get_request_id(),
        "duration_ms": duration,
    }
)
```

## Testing Expectations

### Coverage Requirements
- **Unit Tests**: ≥85% coverage on services, models, schemas
- **Integration Tests**: All API endpoints, all connectors (file, S3, Azure)
- **Migration Tests**: Forward + rollback for every migration
- **E2E Tests**: Complete workflows (ingest → train → promote → recommend)

### Test Organization
```
tests/
├── unit/              # Pure logic, no I/O
│   ├── test_validators.py
│   ├── test_transformers.py
│   └── test_model_registry.py
├── integration/       # Database, API, external services
│   ├── test_api_*.py
│   ├── test_connectors.py
│   └── test_ingestion_orchestrator.py
├── acceptance/        # Business requirements
│   └── test_manulife_scenarios.py
└── migrations/        # Migration-specific tests
    └── test_alembic_*.py
```

### Test Data
- Use fixtures for tenant/field setup
- Mock external services (S3, Azure) in unit tests
- Use localstack/azurite for integration tests when needed
- Never commit real credentials or production data

## Definition of Done

A feature is complete when:

1. **Code**
   - [ ] Implements spec with no placeholders
   - [ ] Follows type hints (mypy clean)
   - [ ] Passes ruff linting
   - [ ] Includes docstrings for public APIs

2. **Tests**
   - [ ] Unit tests for business logic
   - [ ] Integration tests for I/O operations
   - [ ] Tests pass locally and in CI
   - [ ] Coverage meets threshold (≥85%)

3. **Documentation**
   - [ ] README.md updated with new features
   - [ ] API docs include examples
   - [ ] Environment variables documented
   - [ ] Operational runbook updated

4. **Observability**
   - [ ] Metrics added to MetricsRegistry
   - [ ] Structured logs include required fields
   - [ ] Errors handled with appropriate HTTP codes
   - [ ] Audit trail for sensitive operations

5. **Deployment**
   - [ ] Works in Docker Compose
   - [ ] Environment variables in .env.example
   - [ ] Migrations applied automatically on startup
   - [ ] Health check returns detailed status

## Key Metrics for Manulife

The platform must surface these KPIs for enterprise reporting:

1. **Water Efficiency**
   - Total water saved (m³) vs. baseline
   - Water use intensity (m³/acre)
   - Compliance with allocation limits

2. **Energy & Cost**
   - Energy saved (kWh) from optimized pumping
   - Cost savings ($USD) - water + energy
   - ROI calculation vs. traditional schedules

3. **Operational**
   - Recommendation accuracy (actual vs. predicted)
   - System uptime (99.5% SLA)
   - Data ingestion success rate (≥99%)

4. **Agronomic**
   - Soil moisture maintenance (target ±5%)
   - Yield impact (% change vs. baseline)
   - Stress event prevention (days at optimal moisture)

## Manulife-Specific Requirements

### Data Sources
- **Weather**: NOAA/Weather Underground APIs (ET₀, rainfall, temp)
- **Soil Sensors**: 15-min intervals, soil moisture + temp at 6"/12"/18" depths
- **Flow Meters**: Hourly totals per irrigation zone
- **Manual Observations**: Field notes via CSV upload

### Deployment Topology
- **Edge**: Raspberry Pi running ingestion collector (file-drop watcher)
- **Cloud**: Azure App Service hosting API + ML training jobs
- **Storage**: Azure Blob for raw data, Azure SQL for operational DB
- **Registry**: Azure Blob-backed model registry

### Compliance
- SOC 2 Type II audit trail requirements
- Data retention: 7 years for irrigation logs, 3 years for sensor data
- PII handling: No personal data collected, tenant names pseudonymized in logs

## Development Workflow

### 1. Feature Branch
```bash
git checkout -b feature/manulife-ingestion-audit
```

### 2. Implement with Tests
```bash
# Write tests first
pytest tests/unit/test_ingestion_audit.py -v

# Implement feature
# Run tests continuously
pytest --cov=app --cov-report=term
```

### 3. Update Docs
- Add to README.md
- Update API_DEPLOYMENT_GUIDE.md if needed
- Add runbook entry for ops team

### 4. Local Validation
```bash
# Run full suite
make quality  # lint + type + test

# Test in Docker
docker-compose up --build
# Run acceptance tests against Docker instance
```

### 5. Commit & Push
```bash
git add .
git commit -m "feat(ingestion): add audit trail for Manulife compliance"
git push origin feature/manulife-ingestion-audit
```

## File Organization

```
agroai_api/
├── app/
│   ├── api/v1/          # HTTP endpoints
│   ├── core/            # Config, security, logging
│   ├── db/              # Database, migrations
│   ├── models/          # SQLAlchemy ORM
│   ├── schemas/         # Pydantic validation
│   ├── services/        # Business logic
│   ├── ml/              # Model training, registry
│   ├── ingestion/       # Batch ingestion toolkit
│   └── main.py
├── tests/               # All tests
├── scripts/             # CLI tools, seed data
├── docs/                # Extended documentation
├── alembic/             # Database migrations
└── artifacts/           # Model artifacts, reports
```

## Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/agroai

# Security
API_KEY_SALT=random-32-char-salt
JWT_SECRET=your-jwt-secret  # For future JWT support
RATE_LIMIT_PER_MINUTE=100

# Cloud Connectors
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_S3_BUCKET=agroai-manulife-data

AZURE_STORAGE_CONNECTION_STRING=...
AZURE_STORAGE_CONTAINER=agroai-ingestion

# Model Registry
MODEL_REGISTRY_BACKEND=azure  # filesystem | s3 | azure
MODEL_REGISTRY_PATH=models/

# Observability
LOG_LEVEL=INFO
PROMETHEUS_ENABLED=true
SENTRY_DSN=https://...  # For error tracking
```

## Common Pitfalls

1. **Don't** use `Base.metadata.create_all()` - Always use migrations
2. **Don't** log sensitive data (API keys, sensor IDs that could identify locations)
3. **Don't** skip rate limiting - Even admin endpoints need limits
4. **Don't** hardcode tenant IDs - Always from authentication
5. **Don't** trust file uploads - Validate checksums, scan for malware patterns
6. **Do** use transactions for multi-table operations
7. **Do** include tenant_id in all log messages
8. **Do** version all API responses with model version
9. **Do** test migrations in both directions (upgrade + downgrade)
10. **Do** mock cloud services in tests (don't hit real S3/Azure)

## Questions?

This is a living document. When in doubt:
1. Check existing code patterns in `app/services/`
2. Review test examples in `tests/integration/`
3. Consult API_DEPLOYMENT_GUIDE.md for ops questions
4. Ask for clarification rather than guessing
