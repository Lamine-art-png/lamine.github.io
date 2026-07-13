# ADR 005: Distributed Rate Limiting

Decision: Production Platform API rate limiting requires Redis-backed distributed state.

Implementation:

- Backend technology: Redis, using a single Lua script for atomic multi-bucket increments.
- State backend: `PLATFORM_API_REDIS_URL`, falling back to durable `REDIS_URL` only when a dedicated Platform API URL is not supplied.
- Key format: `agroai:platform-rate-limit:v1:{environment}:{dimension}:{id}:{window}:{window_start}`.
- Dimensions: organization, API project, and API key.
- Windows: burst and sustained windows are checked in the same atomic Redis operation.
- Route cost: a server-owned route-cost table applies weighted costs to every active bucket.
- Test/live separation: environment is part of every Redis key, with separate policy limits for `test` and `live`.
- Retry behavior: transient connection/timeout retries reuse a short-lived operation token stored by the same Lua script, preventing an ambiguous successful write from charging twice.
- Consistency boundary: all six organization/project/key burst/sustained counters and the retry result are committed in one Redis script execution.
- Failure behavior: production Platform API readiness blocks when enabled without Redis; Redis runtime errors fail closed for partner traffic unless a non-production fail-open override is explicitly set.
- Response contract: 429 responses include `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`, and `Retry-After`.
- Observability: Prometheus records backend latency and allowed/denied/unavailable outcomes without organization, project, or key labels.
- Cloudflare edge: edge enforcement may be added later, but backend authorization never assumes the edge enforced limits.
- Portal traffic: existing Enterprise Portal routes do not use this limiter in this phase.

The memory limiter is allowed only in development and tests. Production with memory limiter fails closed for partner traffic.

Real-backend proof uses two independent Redis clients and concurrent calls:

```bash
PLATFORM_API_REDIS_INTEGRATION_URL=redis://127.0.0.1:6379/15 \
python -m pytest tests/integration/test_platform_api_redis_limiter.py -q
```
