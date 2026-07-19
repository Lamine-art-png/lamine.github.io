"""Production-safe Field Intelligence metrics and structured events.

Label discipline is strict: labels carry only bounded enumerations (stage,
status, cohort, reason codes). No tenant identifier, transcript, note body,
object path, filename or secret ever enters a metric label or a structured
log line — redaction is applied centrally here.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

from app.core.config import settings

logger = logging.getLogger("agroai.field_intelligence.events")

_LATENCY_BUCKETS = [0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0]
_BYTES_BUCKETS = [1e4, 1e5, 5e5, 1e6, 5e6, 1e7, 2.5e7, 5e7]

captures_initiated = Counter(
    "agroai_field_captures_initiated_total",
    "Field capture sessions initiated", ["source", "cohort"],
)
asset_upload_bytes = Histogram(
    "agroai_field_asset_upload_bytes",
    "Uploaded field asset size in bytes", ["kind"], buckets=_BYTES_BUCKETS,
)
asset_upload_latency = Histogram(
    "agroai_field_asset_upload_seconds",
    "Field asset upload handling latency", ["kind"], buckets=_LATENCY_BUCKETS,
)
media_validation_failures = Counter(
    "agroai_field_media_validation_failures_total",
    "Rejected media uploads", ["reason"],
)
quota_reservation_failures = Counter(
    "agroai_field_quota_reservation_failures_total",
    "Storage quota reservations refused",
)
processing_outcomes = Counter(
    "agroai_field_processing_outcomes_total",
    "Durable processing job outcomes", ["stage", "outcome"],
)
processing_retries = Counter(
    "agroai_field_processing_retries_total",
    "Durable processing retries", ["stage"],
)
stage_latency = Histogram(
    "agroai_field_stage_seconds",
    "Latency per pipeline stage", ["stage"], buckets=_LATENCY_BUCKETS,
)
queue_depth = Gauge(
    "agroai_field_queue_depth",
    "Field Intelligence durable queue depth", ["job_type", "status"],
)
stale_jobs = Gauge(
    "agroai_field_stale_jobs",
    "Jobs older than the stale threshold", ["job_type"],
)
stale_leases = Counter(
    "agroai_field_stale_leases_total",
    "Job leases that expired and were reclaimed",
)
sync_batches = Counter(
    "agroai_field_sync_batches_total",
    "Offline sync batches processed", ["outcome"],
)
observations_created = Counter(
    "agroai_field_observations_created_total",
    "Observations created", ["cohort"],
)
evidence_created = Counter(
    "agroai_field_evidence_created_total",
    "Evidence records created from observations",
)
tasks_created = Counter(
    "agroai_field_tasks_created_total",
    "Tasks created from observations",
)
objects_deleted = Counter(
    "agroai_field_objects_deleted_total",
    "Physical media objects deleted",
)
orphans_reconciled = Counter(
    "agroai_field_orphans_reconciled_total",
    "Reconciler outcomes", ["outcome"],
)
storage_used_bytes = Gauge(
    "agroai_field_storage_used_bytes",
    "Physical media storage accounted (sampled per tenant sweep)",
)
transcription_latency = Histogram(
    "agroai_field_transcription_seconds",
    "Transcription provider latency", ["provider", "status"], buckets=_LATENCY_BUCKETS,
)
emergency_disable = Gauge(
    "agroai_field_emergency_disable",
    "1 while the Field Intelligence kill switch is active",
)
rollout_requests = Counter(
    "agroai_field_rollout_decisions_total",
    "Release-gate decisions", ["state", "cohort", "allowed"],
)

# ---------------------------------------------------------------------------
# Redacted structured events
# ---------------------------------------------------------------------------

# Keys whose values must never be logged verbatim.
_SENSITIVE_KEY = re.compile(
    r"(transcript|note|text|token|secret|key|password|authorization|object_ref|"
    r"filename|path|email|phone)", re.IGNORECASE,
)
_MAX_VALUE = 120


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if _SENSITIVE_KEY.search(str(k)) else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value[:20]]
    if isinstance(value, str) and len(value) > _MAX_VALUE:
        return value[:_MAX_VALUE] + "…"
    return value


def emit_event(event: str, **fields: Any) -> None:
    """Structured, redacted operational event (single log line)."""
    if not bool(getattr(settings, "FIELD_METRICS_ENABLED", True)):
        return
    safe = _redact(fields)
    logger.info("field_intelligence.%s %s", event, safe)


def record_emergency_disable(*, active: bool) -> None:
    emergency_disable.set(1 if active else 0)
    emit_event("emergency_disable", active=active)
