# ADR 005: Distributed Rate Limiting

Decision: Production Platform API rate limiting requires Redis-backed distributed state.

The memory limiter is allowed only in development and tests. Production with memory limiter fails closed for partner traffic.
