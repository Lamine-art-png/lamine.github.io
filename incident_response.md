# Incident Response Runbook (Pilot)

Scope: API, Batch Ingestion, Postgres, Secrets, Observability

## Severity
- SEV-1: Data loss or outage > 2h
- SEV-2: Degraded perf or ingestion lag > 30m
- SEV-3: Minor bug; workaround exists

## On-call
- Primary: CTO
- Secondary: CEO (escalation)
- Rotation: Weekly (Fri 09:00 PT)

## Alerts
- API 5XX > 2% for 5m
- p95 latency > 800ms for 10m
- Ingestion lag > 30m
- Disk free < 15%
- RDS replica lag > 1m

## Response
1. Acknowledge alert (timestamp).
2. Stabilize (scale ECS, pause batch, feature-flag).
3. Diagnose (logs, exec into task, DB health).
4. Communicate through approved private incident channels.
5. Recover (RTO 4h, RPO 24h): restore snapshot; replay ledger.
6. Preserve evidence in an approved private evidence store. Screenshots, screen
   recordings, logs, traces, browser state, customer data, credentials, and
   authenticated dashboards must never be committed to this repository, posted
   to a public gist/repository, or uploaded by an agent to a public image host.
7. If any credential appears in Git history, logs, screenshots, chat, or another
   public location, treat it as compromised: revoke/rotate it immediately, then
   remove the exposed material and document the rotation privately.

## Postmortem
Timeline, root cause (5 whys), fix, owners & dates. Store sensitive evidence and
credential details outside the public repository.
