from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from app.core.config import Settings


@dataclass(frozen=True)
class ReadinessFinding:
    code: str
    severity: str
    component: str
    message: str


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    target_scale: str
    blockers: tuple[ReadinessFinding, ...]
    warnings: tuple[ReadinessFinding, ...]

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "target_scale": self.target_scale,
            "blockers": [asdict(item) for item in self.blockers],
            "warnings": [asdict(item) for item in self.warnings],
        }


def _is_local_path(value: str) -> bool:
    raw = (value or "").strip().lower()
    return raw.startswith("/tmp/") or raw.startswith("./") or raw.startswith("/var/tmp/")


def _database_scheme(url: str) -> str:
    return urlparse(url or "").scheme.lower()


def _setting(settings: Settings, name: str, default: str = "") -> str:
    value = getattr(settings, name, None)
    if value not in (None, ""):
        return str(value).strip()
    return os.getenv(name, default).strip()


def evaluate_production_readiness(settings: Settings, *, target_scale: str = "production") -> ReadinessReport:
    blockers: list[ReadinessFinding] = []
    warnings: list[ReadinessFinding] = []

    database_scheme = _database_scheme(settings.DATABASE_URL)
    if database_scheme.startswith("sqlite"):
        blockers.append(ReadinessFinding("database.sqlite", "blocker", "database", "SQLite is not an acceptable production system of record."))
    if not database_scheme.startswith("postgres"):
        warnings.append(ReadinessFinding("database.non_postgres", "warning", "database", "The application is validated primarily against PostgreSQL; verify pooling, transactions, and migration behavior for this database."))

    if settings.SECRET_KEY.startswith("dev-") or "change-in-production" in settings.SECRET_KEY:
        blockers.append(ReadinessFinding("security.default_secret", "blocker", "identity", "A development signing secret is configured."))
    if settings.WEBHOOK_SECRET.startswith("dev-") or "change-in-production" in settings.WEBHOOK_SECRET:
        blockers.append(ReadinessFinding("security.default_webhook_secret", "blocker", "webhooks", "A development webhook secret is configured."))
    if settings.DEMO_API_KEY.startswith("changeme"):
        blockers.append(ReadinessFinding("security.default_demo_key", "blocker", "api", "The default demonstration API key is configured."))

    if settings.ENABLE_SCHEDULER:
        blockers.append(ReadinessFinding("scheduler.in_process", "blocker", "scheduler", "The API process is allowed to start an in-process scheduler; horizontally scaled replicas can duplicate scheduled work."))

    object_backend = _setting(settings, "CONNECTOR_OBJECT_STORAGE_BACKEND", "disabled").lower()
    object_bucket = _setting(settings, "CONNECTOR_OBJECT_BUCKET")
    if object_backend not in {"s3", "r2", "s3_compatible"} or not object_bucket:
        blockers.append(ReadinessFinding("connectors.object_storage_missing", "blocker", "connectors", "A verified durable R2/S3-compatible connector object store and bucket are required."))
    if _is_local_path(settings.CONNECTOR_UPLOAD_DIR) and object_backend not in {"s3", "r2", "s3_compatible"}:
        blockers.append(ReadinessFinding("connectors.local_upload_storage", "blocker", "connectors", "Connector payloads are configured for local or ephemeral disk without durable object storage."))

    queue_backend = _setting(settings, "TASK_QUEUE_BACKEND", "disabled").lower()
    redis_url = _setting(settings, "REDIS_URL")
    cloudflare_publish_url = _setting(settings, "CLOUDFLARE_QUEUE_PUBLISH_URL")
    cloudflare_publish_token = _setting(settings, "CLOUDFLARE_QUEUE_PUBLISH_TOKEN")
    cloudflare_consumer_token = _setting(settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN")
    redis_ready = queue_backend in {"redis", "redis_streams", "redis-streams"} and bool(redis_url)
    cloudflare_ready = queue_backend in {"cloudflare", "cloudflare_queues", "cloudflare-queues"} and bool(
        cloudflare_publish_url and cloudflare_publish_token and cloudflare_consumer_token
    )
    if not redis_ready and not cloudflare_ready:
        blockers.append(ReadinessFinding("workers.external_queue_missing", "blocker", "workers", "A complete durable external connector queue transport is required."))
    if queue_backend in {"cloudflare", "cloudflare_queues", "cloudflare-queues"} and not cloudflare_ready:
        blockers.append(ReadinessFinding("workers.cloudflare_queue_incomplete", "blocker", "workers", "Cloudflare Queue mode requires publish URL, publish token, and consumer token together."))
    if queue_backend in {"redis", "redis_streams", "redis-streams"} and not redis_url:
        warnings.append(ReadinessFinding("coordination.redis_missing", "warning", "coordination", "Redis queue mode is selected without a distributed coordination endpoint."))

    vault_key = _setting(settings, "CONNECTOR_CREDENTIAL_MASTER_KEY")
    vault_ring = _setting(settings, "CONNECTOR_CREDENTIAL_KEYS_JSON")
    if not vault_key and not vault_ring:
        blockers.append(ReadinessFinding("connectors.credential_vault_missing", "blocker", "connectors", "Encrypted retrievable connector credential custody is not configured."))
    if not _setting(settings, "OAUTH_STATE_SIGNING_KEY"):
        blockers.append(ReadinessFinding("connectors.oauth_state_key_missing", "blocker", "connectors", "A dedicated OAuth state signing key is not configured."))

    if settings.ACCESS_TOKEN_EXPIRE_MINUTES > 1440:
        warnings.append(ReadinessFinding("identity.long_lived_access_token", "warning", "identity", "Access tokens live longer than one day; production should use shorter access tokens plus refresh/session rotation."))

    if not settings.AI_PROVIDER:
        blockers.append(ReadinessFinding("intelligence.provider_missing", "blocker", "intelligence", "No live intelligence provider is configured."))

    return ReadinessReport(
        ready=not blockers,
        target_scale=target_scale,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )
