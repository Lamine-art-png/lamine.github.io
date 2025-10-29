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


def metrics_endpoint():
    """Expose Prometheus metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
