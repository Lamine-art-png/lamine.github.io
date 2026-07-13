# ADR 005: Distributed Rate Limiting

Decision: Production Platform API rate limiting requires Redis-backed distributed state.

Implementation:

- Backend technology: Redis, using a single Lua script for atomic multi-bucket increments.
- State backend: `PLATFORM_API_REDIS_URL`, falling back to durable `REDIS_URL` only when a dedicated Platform API URL is not supplied.
- Key format: `agroai:platform-rate-limit:v1:{environment}:{dimension}:{id}:{window}:{window_start}`.
- Dimensions: organization, API project, and API key.
- Windows: burst and sustained windows are checked in the same atomic Redis operation.
- Route cost: route handlers pass a weighted `cost`; the limiter applies that cost to every active bucket.
- Test/live separation: environment is part of every Redis key, with separate policy limits for `test` and `live`.
- Failure behavior: production Platform API readiness blocks when enabled without Redis; Redis runtime errors fail closed for partner traffic unless a non-production fail-open override is explicitly set.
- Response contract: 429 responses include `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`, and `Retry-After`.
- Cloudflare edge: edge enforcement may be added later, but backend authorization never assumes the edge enforced limits.
- Portal traffic: existing Enterprise Portal routes do not use this limiter in this phase.

The memory limiter is allowed only in development and tests. Production with memory limiter fails closed for partner traffic.
