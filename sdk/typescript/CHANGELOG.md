# Changelog

## 0.2.0 — unreleased

- Adds strict server/browser separation, pagination, request and rate-limit
  metadata, safe read retries, idempotency, uploads, job polling, usage, and
  replay-bounded webhook signature verification.

## 0.3.0

- `AgroAI` client for AGRO-AI Intelligence Platform v1: runs, SSE streaming,
  async jobs, sessions, files, knowledge, tools; typed errors; retries that
  reuse one Idempotency-Key. `AgroAIPlatformClient` is unchanged.
