# Platform API service-level objective policy

Status: engineering objectives, not a customer SLA.

The launch objective is 99.9% monthly availability for the customer request path, less than 0.5% server-error rate, and p95 latency below 500 ms for bounded metadata reads under the declared launch topology. Asynchronous operations have separate objectives: accepted jobs begin processing within two minutes under normal load, webhook deliveries reach a terminal state within fifteen minutes, and billing meter backlog age remains below fifteen minutes.

No objective becomes a contractual claim until at least 30 consecutive days of production telemetry, alert coverage, incident review, and an approved customer agreement exist.

## Required measurements

Every report records release SHA, environment, instance and replica topology, database and Redis topology, request mix, duration, throughput, p50/p95/p99, status-code distribution, CPU, memory, database connections and pool waits, Redis latency and backlog, queue age, worker throughput, and saturation point.

## Error-budget response

At 50% monthly budget consumption, pause non-essential reliability-risking changes. At 75%, require founder and engineering approval for releases. At 100%, prioritize recovery and reliability work until the rolling window returns within budget.
