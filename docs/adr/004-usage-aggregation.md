# ADR 004: Usage Aggregation

Decision: Platform API usage is recorded as durable usage events outside authentication.

This preserves request accounting without committing during API-key verification. Future aggregation can batch events into customer summaries and billing-readiness metrics.
