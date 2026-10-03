# Changelog

## 0.2.0 — unreleased

- Adds sync and async clients, pagination, request/rate-limit metadata, safe
  read retries, idempotency support, upload initiation, job polling, usage, and
  constant-time webhook signature verification.

## 0.3.0

- New `agroai` package: `from agroai import AgroAI, AsyncAgroAI`.
- `client.intelligence.run/stream/jobs/sessions/files/knowledge/tools/runs/usage`
  for AGRO-AI Intelligence Platform v1.
- Typed errors (`InsufficientBalanceError`, `ConflictError`, `RateLimitError`, …),
  bounded retries that reuse one Idempotency-Key, configurable timeouts.
- `agroai_platform` (Platform API client and CLI) is unchanged.
