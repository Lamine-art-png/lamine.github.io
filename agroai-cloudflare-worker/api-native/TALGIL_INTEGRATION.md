# Talgil Integration — Technical Architecture v2.0

Aligned with rest.api.external v1.47 and behavior guidelines v8.

## Request Behavior (aligned with Kosta's feedback + API v1.47)

### What we request and when

| Endpoint | When | Cadence | Purpose |
|----------|------|---------|---------|
| `GET /mytargets` | Connect only | Once per tenant | Discover controller ID (serial, name, online) |
| `GET /targets/{id}/` | Connect only | Once | Full unfiltered image for complete metadata |
| `GET /targets/{id}/?filter=...` | Every sync | Every 20 min | Filtered image: sensors + key fields only |
| `GET /targets/{id}/sensors/{sid}/log` | Backfill only | Batch, 16s gaps | Per-sensor historical data |
| `GET /targets/{id}/eventlog` | Diagnostic only | Manual trigger | Test permissions (returns time, context, subcontext, message) |
| `GET /targets/{id}/wc/valves` | Diagnostic only | Manual trigger | Test permissions (returns keyed object → buckets) |

### What we do NOT do

- **No** separate `/targets/{id}/sensors` call (sensors are in full image)
- **No** `/mytargets` on every sync (called once during connect)
- **No** per-minute log requests (historical is batch-only)
- **No** requests outside simulator date range (2026-02-22 to 2026-03-10)
- **No** duplicate requests (each sync cycle = 1 filtered image fetch)
- **No** unnecessary broad requests (use filtering)

## Minimum Intervals (behavior guidelines v8)

| Request Type | Minimum Interval |
|---|---|
| Live POST (non-modify) | 1 second |
| Live POST (modify) | 2 seconds |
| Live POST (batch modify) | 15 seconds |
| Live GET | 1 second |
| DB GET log (sensors, programs) | 15 seconds |
| DB GET event log | 15 seconds |
| DB GET water consumption | 60 seconds |
| DB GET fert consumption | 60 seconds |

**Important**: Recommended operational cadence is every 10-20 minutes, not the minimum.

## Maximum DB Query Ranges by Rate

| Rate | Max Range |
|---|---|
| hourly | 7 days |
| daily | 31 days |
| weekly | 184 days |
| monthly | 366 days |
| yearly | 731 days |
| none | 92 days |

## Sync Modes

1. **connect** — One-time: /mytargets → /targets/{id}/ (full) → populate catalog + snapshot + sensor UIDs
2. **sync** — Operational: /targets/{id}/?filter=sensors|uid|name|... → update catalog + snapshot
3. **backfill** — Historical: per-sensor /sensors/{sid}/log in 1-day chunks with 16s delay between
4. **test_eventlog** — Diagnostic: single eventlog request to verify permissions
5. **test_wc** — Diagnostic: single wc/valves request to verify permissions

## Filtering (API v1.47)

The API supports response filtering on almost every GET request:
```
GET /targets/{id}/?filter=sensors|uid|name|type|units|value|updateTime
```

For operational sync, we use:
```
filter=sensors|uid|name|type|units|value|updateTime|state|online
```

This reduces traffic and aligns with "do not request unnecessary information."

## Water Consumption Response Format

Per API v1.47, `/wc/valves` returns an object keyed by valve UID:
```json
{
  "1.1": [
    { "from": 1740182400000, "until": 1740268800000, "value": 123.4, "valuePerArea": 5.6 }
  ],
  "1.2": [...]
}
```

Optional params: `vids` (comma-separated valve IDs), `volume` (true/false).

## Event Log Response Format

Per API v1.47, `/eventlog` returns:
```json
[
  { "time": 1740200000000, "context": "irrigation", "subcontext": "valve", "message": "Valve 1 opened" }
]
```

Message is in the caller's language. Kept for at least 3 months.

## Simulator Date Range

- From: 2026-02-22T00:00:00Z (1740182400000 ms)
- Until: 2026-03-10T23:59:59Z (1741651199000 ms)
- All historical requests are clamped to this range in dev
- Zero values outside this range are expected, not errors

## Error Differentiation

| HTTP Status | Meaning | Action |
|---|---|---|
| 200 | Success | Process data |
| 400 | Malformed request | Fix URL/params |
| 401 | Unauthorized | Check API key |
| 403 | Forbidden | Permission scope — confirm with Kosta |
| 404 | Not found | Check endpoint/controller ID |
| 405 | Method not allowed | Check GET vs POST |
| 500 | Server error | Retry later |

A 403 on documented endpoints may be permission-scoped, not syntax error.

## Database Tables

| Table | Purpose | Primary Key |
|---|---|---|
| `integrations_talgil` | Connection state per tenant | tenant_id |
| `talgil_sensor_catalog` | Sensor metadata from full image | tenant_id, controller_id, sensor_uid |
| `talgil_sensor_log` | Historical + snapshot readings | tenant_id, controller_id, sensor_uid, observed_at_ms |
| `talgil_event_log` | Event log entries | tenant_id, controller_id, event_key |
| `talgil_valve_wc` | Water consumption buckets | tenant_id, controller_id, valve_uid, bucket_start_ms |
| `audit_log` | Full audit trail | id (autoincrement) |

## API Endpoints

### Write (POST → Durable Object)
- `POST /v1/integrations/talgil/connect?tenantId=X`
- `POST /v1/integrations/talgil/sync?tenantId=X`
- `POST /v1/integrations/talgil/backfill?tenantId=X&from=&until=`
- `POST /v1/integrations/talgil/disconnect?tenantId=X`
- `POST /v1/integrations/talgil/test/eventlog?tenantId=X`
- `POST /v1/integrations/talgil/test/wc?tenantId=X`

### Read (GET → D1 queries)
- `GET /v1/integrations/talgil/status?tenantId=X`
- `GET /v1/integrations/talgil/sensors/catalog?tenantId=X`
- `GET /v1/integrations/talgil/sensors/latest?tenantId=X`
- `GET /v1/integrations/talgil/sensors/history?tenantId=X&sensor_uid=&from=&until=&limit=`
- `GET /v1/integrations/talgil/events?tenantId=X&limit=`
- `GET /v1/integrations/talgil/wc?tenantId=X&valve_uid=&limit=`
- `GET /v1/integrations/talgil/audit?tenantId=X`

## Evidence Collection Checklist

After deploy and validation, produce:
1. Audit log showing exact URLs called with HTTP status codes
2. Row counts for all tables (status endpoint)
3. Sensor catalog population proof with metadata (type, units, thresholds)
4. Exact HTTP status for eventlog and wc/valves diagnostic tests
5. Sample sensor data with metadata enrichment (latest endpoint)
6. Sample filtered image response showing traffic reduction
7. Backfill results with per-sensor chunk details

## Dev Credentials

- Host: `dev.talgil.com`
- Controller/Simulator ID: `6115`
- All requests require `TLG-API-Key` header
