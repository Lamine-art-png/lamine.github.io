from __future__ import annotations

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


def evaluate_production_readiness(settings: Settings, *, target_scale: str = "one-million-users") -> ReadinessReport:
    blockers: list[ReadinessFinding] = []
    warnings: list[ReadinessFinding] = []

    database_scheme = _database_scheme(settings.DATABASE_URL)
    if database_scheme.startswith("sqlite"):
        blockers.append(ReadinessFinding(
            "database.sqlite", "blocker", "database",
            "SQLite is not an acceptable production system of record for the target scale.",
        ))
    if not database_scheme.startswith("postgres"):
        warnings.append(ReadinessFinding(
            "database.non_postgres", "warning", "database",
            "The target architecture is validated primarily against PostgreSQL; verify pooling, transactions, and migration behavior for this database.",
        ))

    if settings.SECRET_KEY.startswith("dev-") or "change-in-production" in settings.SECRET_KEY:
        blockers.append(ReadinessFinding(
            "security.default_secret", "blocker", "identity",
            "A development signing secret is configured.",
        ))
    if settings.WEBHOOK_SECRET.startswith("dev-") or "change-in-production" in settings.WEBHOOK_SECRET:
        blockers.append(ReadinessFinding(
            "security.default_webhook_secret", "blocker", "webhooks",
            "A development webhook secret is configured.",
        ))
    if settings.DEMO_API_KEY.startswith("changeme"):
        blockers.append(ReadinessFinding(
            "security.default_demo_key", "blocker", "api",
            "The default demonstration API key is configured.",
        ))

    if settings.ENABLE_SCHEDULER:
        blockers.append(ReadinessFinding(
            "scheduler.in_process", "blocker", "scheduler",
            "The API process is allowed to start an in-process scheduler; horizontally scaled replicas can duplicate scheduled work.",
        ))

    if _is_local_path(settings.CONNECTOR_UPLOAD_DIR):
        blockers.append(ReadinessFinding(
            "connectors.local_upload_storage", "blocker", "connectors",
            "Connector payloads are configured for local or ephemeral disk instead of durable object storage.",
        ))

    object_backend = getattr(settings, "CONNECTOR_OBJECT_STORAGE_BACKEND", "disabled").strip().lower()
    if object_backend in {"", "disabled", "local"}:
        blockers.append(ReadinessFinding(
            "connectors.object_storage_missing", "blocker", "connectors",
            "No durable connector object-storage backend is configured.",
        ))

    queue_backend = getattr(settings, "TASK_QUEUE_BACKEND", "disabled").strip().lower()
    if queue_backend in {"", "disabled", "inline", "in_process"}:
        blockers.append(ReadinessFinding(
            "workers.external_queue_missing", "blocker", "workers",
            "No external task queue is configured for ingestion, synchronization, reports, and long-running model work.",
        ))

    if not getattr(settings, "REDIS_URL", "").strip():
        warnings.append(ReadinessFinding(
            "coordination.redis_missing", "warning", "coordination",
            "No distributed coordination/cache endpoint is configured; rate limits, locks, deduplication, and shared cache cannot be assumed across replicas.",
        ))

    if settings.ACCESS_TOKEN_EXPIRE_MINUTES > 1440:
        warnings.append(ReadinessFinding(
            "identity.long_lived_access_token", "warning", "identity",
            "Access tokens live longer than one day; production scale should use shorter access tokens plus refresh/session rotation.",
        ))

    if not settings.AI_PROVIDER:
        blockers.append(ReadinessFinding(
            "intelligence.provider_missing", "blocker", "intelligence",
            "No live intelligence provider is configured.",
        ))

    return ReadinessReport(
        ready=not blockers,
        target_scale=target_scale,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )
