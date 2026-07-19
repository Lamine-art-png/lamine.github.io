"""Prometheus metrics configuration."""
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

# Metrics
recommendations_total = Counter(
    'agroai_recommendations_total',
    'Total number of recommendations computed',
    ['tenant', 'status']
)

compute_latency = Histogram(
    'agroai_compute_latency_seconds',
    'Recommendation compute latency in seconds',
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
)

idempotency_hits = Counter(
    'agroai_idempotency_hits_total',
    'Number of idempotent request cache hits'
)

ingestion_total = Counter(
    'agroai_ingestion_total',
    'Total telemetry/events ingested',
    ['tenant', 'type']
)

webhook_sent = Counter(
    'agroai_webhooks_sent_total',
    'Total webhooks sent',
    ['tenant', 'event_type', 'status']
)

# WiseConn sync metrics
sync_runs_total = Counter(
    'agroai_sync_runs_total',
    'Total WiseConn sync runs',
    ['status']
)

sync_duration = Histogram(
    'agroai_sync_duration_seconds',
    'WiseConn sync duration in seconds',
    buckets=[5.0, 15.0, 30.0, 60.0, 120.0, 300.0]
)

sync_data_points = Counter(
    'agroai_sync_data_points_total',
    'Total data points synced from WiseConn',
    ['zone']
)

api_requests = Counter(
    'agroai_api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status']
)

api_latency = Histogram(
    'agroai_api_latency_seconds',
    'API request latency in seconds',
    ['method', 'endpoint'],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

platform_rate_limit_checks = Counter(
    'agroai_platform_rate_limit_checks_total',
    'Platform API rate-limit decisions without customer identifiers',
    ['backend', 'environment', 'outcome']
)

platform_rate_limit_latency = Histogram(
    'agroai_platform_rate_limit_latency_seconds',
    'Platform API rate-limit backend latency',
    ['backend'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)

platform_product_events = Counter(
    'agroai_platform_product_events_total',
    'Audited Platform API product events without customer identifiers',
    ['subsystem', 'action', 'outcome']
)

platform_authentication = Counter(
    'agroai_platform_authentication_total',
    'Platform API authentication decisions without key or customer identifiers',
    ['environment', 'outcome']
)

platform_quota_decisions = Counter(
    'agroai_platform_quota_decisions_total',
    'Platform API credit reservation and quota decisions',
    ['environment', 'outcome']
)

platform_billing_events = Counter(
    'agroai_platform_billing_events_total',
    'Platform API billing lifecycle events',
    ['event_class', 'outcome']
)


def metrics_endpoint():
    """Expose Prometheus metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
