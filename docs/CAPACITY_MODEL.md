# AGRO-AI capacity model

Status: workload assumptions for measurement, not a scale certification.

## Scenarios

Registered users, active users, concurrent sessions, request rate, connector jobs, and model-provider concurrency are different quantities.

| Metric | Launch | 10k registered | 100k registered | 1M registered |
|---|---:|---:|---:|---:|
| Registered users | 1,000 | 10,000 | 100,000 | 1,000,000 |
| MAU | 450 | 4,000 | 35,000 | 300,000 |
| DAU | 160 | 1,400 | 12,000 | 100,000 |
| Peak concurrent sessions | 35 | 250 | 1,800 | 12,000 |
| Modeled peak API RPS | 20 | 120 | 800 | 5,500 |
| Read share | 72% | 72% | 74% | 75% |
| Non-AI write share | 12% | 12% | 11% | 10% |
| AI request share | 8% | 8% | 8% | 8% |
| Connector uploads/day | 120 | 1,000 | 8,000 | 60,000 |
| Mean upload size | 2 MB | 2 MB | 2.5 MB | 3 MB |
| p95 upload size | 20 MB | 20 MB | 25 MB | 25 MB |
| Ingestion jobs/hour at peak | 50 | 350 | 2,800 | 20,000 |
| Mean evidence records/job | 40 | 50 | 60 | 75 |
| Target worker concurrency | 2 | 8 | 40 | 240 |
| Planned web replicas | 2 | 4 | 16 | 80 |

These are explicit assumptions to challenge with production telemetry.

## Representative platform request mix

- 5% health checks;
- 20% operational readiness reads;
- 20% field-intelligence reads;
- 10% exception reads;
- 10% decision-workbench reads;
- 10% connector-job reads;
- 10% conversation/evidence reads;
- 10% controlled safe-Brain requests using a deterministic provider boundary;
- 5% bounded writes.

## Database connection budget

A large registered-user population must not map to a large direct PostgreSQL connection count.

Planning envelope before measurement:

- web process: 5 steady connections plus at most 5 overflow;
- worker process: 3 steady plus at most 2 overflow;
- reserve explicit connection headroom for migrations, operators, workers, and failover;
- introduce an external pooler such as RDS Proxy or PgBouncer before high replica counts make direct pools unsafe;
- measure pool wait time and active connections during every saturation test.

## Redis worker model

At the 1M registered-user scenario, the workload assumption is 20,000 logical ingestion jobs/hour at peak. Validation must include burst behavior, redelivery after worker failure, pending count, oldest pending age, and queue drain time after an outage.

A capacity claim requires worker throughput above arrival rate with at least 30% measured headroom.

## Object-storage model

At 60,000 uploads/day and 3 MB mean size, modeled raw ingress is approximately 180 GB/day before lifecycle expiry.

Measure PUT, HEAD, GET, and DELETE p50/p95/p99, exact-byte verification, checksum failure behavior, and lifecycle effects.

## AI capacity is separate

Application-layer AI tests use a deterministic provider boundary to measure authentication, tenant context assembly, evidence retrieval, safe-Brain processing, provenance, freshness, and persistence.

Live-provider tests are small and bounded. Record provider latency, quotas, timeouts, retry rate, concurrency limits, and cost. Do not extrapolate a small paid-provider sample into a global capacity claim.

## Scenario success gates

### Launch

- 20 peak RPS;
- p95 read latency below 500 ms;
- error rate below 1%;
- no pool exhaustion;
- normal worker peak drains within five minutes.

### 10k registered

- 120 peak RPS;
- p95 read latency below 600 ms;
- error rate below 1%;
- queue pending age below two minutes under normal load.

### 100k registered

- 800 peak RPS under a declared replica and pooler topology;
- p95 read latency below 750 ms;
- error rate below 1%;
- worker throughput exceeds modeled arrival rate by 30%.

### 1M registered

This is a scenario, not a current claim. Minimum evidence:

- sustained 5,500 peak RPS workload mix under a declared multi-replica topology;
- measured external DB pooling and no uncontrolled connection growth;
- at least 26,000 worker jobs/hour for 30% headroom;
- backlog recovery after worker loss;
- object-store latency under modeled ingress;
- bounded model-provider quota and cost envelope;
- Redis, object-store, DB-pressure, worker-restart, and slow-model failure tests;
- p50/p95/p99, error rate, CPU, memory, DB connections, Redis lag, worker throughput, and drain time captured.

Until that evidence exists, the verdict cannot be `PROVEN`.

## Required benchmark record

Every result records: git SHA, environment, instance sizes, replica counts, DB topology and pool limits, Redis topology, object-store backend, AI boundary, dataset size, virtual users, duration, p50/p95/p99, throughput, error rate, CPU, memory, DB active connections, pool waits, Redis pending age, worker throughput, bottleneck, and saturation point.
