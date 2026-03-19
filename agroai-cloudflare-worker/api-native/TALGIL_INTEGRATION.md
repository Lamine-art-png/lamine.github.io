# Talgil Integration — Technical Architecture

## Request Behavior (aligned with Kosta's feedback)

### What we request and when

| Endpoint | When | Cadence | Purpose |
|----------|------|---------|---------|
| `GET /mytargets` | Connect only | Once per tenant | Discover controller ID |
| `GET /targets/{id}/` | Every sync | Every 20 minutes | Full image: status + sensors |
| `GET /targets/{id}/sensors/log` | Backfill only | Batch, 16s between chunks | Historical sensor data |
| `GET /targets/{id}/eventlog` | Diagnostic only | Manual trigger | Test permissions |
| `GET /targets/{id}/wc/valves` | Diagnostic only | Manual trigger | Test permissions |

### What we do NOT do

- **No** separate `/targets/{id}/sensors` call (sensors are in full image)
- **No** `/mytargets` on every sync (called once during connect)
- **No** per-minute log requests (historical is batch-only)
- **No** requests outside simulator date range (2026-02-22 to 2026-03-10)

## Sync Modes

1. **connect** — One-time: /mytargets → /targets/{id}/ → populate catalog + snapshot
2. **sync** — Operational: /targets/{id}/ only → update catalog + snapshot
3. **backfill** — Historical: /sensors/log in 1-day chunks with 16s delay between
4. **test_eventlog** — Diagnostic: single eventlog request to verify permissions
5. **test_wc** — Diagnostic: single wc/valves request to verify permissions

## Simulator Date Range

- From: 2026-02-22T00:00:00Z (1771718400000 ms)
- Until: 2026-03-10T23:59:59Z (1773187199000 ms)
- All historical requests are clamped to this range
- Zero values outside this range are expected, not errors

## Evidence Collection

After deploy and validation, produce:
1. Audit log showing exact URLs called
2. Row counts for all tables
3. Sensor catalog population proof
4. Exact HTTP status for eventlog and wc/valves
5. Sample sensor data with metadata enrichment
