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


SELF_SERVE_STRIPE_PRICE_SETTINGS = (
    "STRIPE_PRICE_PRO_MONTHLY",
    "STRIPE_PRICE_PRO_ANNUAL",
    "STRIPE_PRICE_TEAM_MONTHLY",
    "STRIPE_PRICE_TEAM_ANNUAL",
    "STRIPE_PRICE_NETWORK_MONTHLY",
    "STRIPE_PRICE_NETWORK_ANNUAL",
)


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


def _require_r2_contract(settings: Settings, blockers: list[ReadinessFinding]) -> None:
    endpoint = _setting(settings, "CONNECTOR_OBJECT_ENDPOINT_URL")
    access_key = _setting(settings, "CLOUDFLARE_R2_ACCESS_KEY_ID")
    secret_key = _setting(settings, "CLOUDFLARE_R2_SECRET_ACCESS_KEY")

    if not endpoint:
        blockers.append(
            ReadinessFinding(
                "connectors.r2_endpoint_missing",
                "blocker",
                "connectors",
                "R2 connector object storage requires the account-scoped endpoint URL.",
            )
        )
    elif urlparse(endpoint).scheme != "https":
        blockers.append(
            ReadinessFinding(
                "connectors.r2_endpoint_not_https",
                "blocker",
                "connectors",
                "R2 connector object storage endpoint must use HTTPS.",
            )
        )

    if not access_key or not secret_key:
        blockers.append(
            ReadinessFinding(
                "connectors.r2_credentials_missing",
                "blocker",
                "connectors",
                "R2 connector object storage requires both access key fields before production release.",
            )
        )


def _require_billing_contract(settings: Settings, blockers: list[ReadinessFinding]) -> None:
    if not _setting(settings, "STRIPE_SECRET_KEY"):
        blockers.append(
            ReadinessFinding(
                "billing.stripe_secret_missing",
                "blocker",
                "billing",
                "Stripe API credentials are required before the self-serve commercial surface can enter production.",
            )
        )

    if not _setting(settings, "STRIPE_WEBHOOK_SECRET"):
        blockers.append(
            ReadinessFinding(
                "billing.stripe_webhook_secret_missing",
                "blocker",
                "billing",
                "Stripe webhook signature verification must be configured before production release.",
            )
        )

    price_values = {name: _setting(settings, name) for name in SELF_SERVE_STRIPE_PRICE_SETTINGS}
    missing = [name for name, value in price_values.items() if not value]
    if missing:
        blockers.append(
            ReadinessFinding(
                "billing.stripe_prices_missing",
                "blocker",
                "billing",
                "All Professional, Team, and Network monthly/annual Stripe Price IDs are required; missing: "
                + ", ".join(missing),
            )
        )
        return

    invalid = [name for name, value in price_values.items() if not value.startswith("price_")]
    if invalid:
        blockers.append(
            ReadinessFinding(
                "billing.stripe_price_ids_invalid",
                "blocker",
                "billing",
                "Configured self-serve Stripe prices must use Stripe Price IDs; invalid: " + ", ".join(invalid),
            )
        )

    values = list(price_values.values())
    if len(values) != len(set(values)):
        blockers.append(
            ReadinessFinding(
                "billing.stripe_price_ids_duplicate",
                "blocker",
                "billing",
                "Each self-serve monthly/annual commercial offer must map to a distinct Stripe Price ID.",
            )
        )


def evaluate_production_readiness(settings: Settings, *, target_scale: str = "production") -> ReadinessReport:
    blockers: list[ReadinessFinding] = []
    warnings: list[ReadinessFinding] = []

    database_scheme = _database_scheme(settings.DATABASE_URL)
    if database_scheme.startswith("sqlite"):
        blockers.append(ReadinessFinding("database.sqlite", "blocker", "database", "SQLite is not an acceptable production system of record."))
    if not database_scheme.startswith("postgres"):
        warnings.append(ReadinessFinding("database.non_postgres", "warning", "database", "The application is validated primarily against PostgreSQL; verify pooling, transactions, and migration behavior for this database."))

    default_secret = settings.SECRET_KEY.startswith("dev-") or "change-in-production" in settings.SECRET_KEY
    default_webhook_secret = settings.WEBHOOK_SECRET.startswith("dev-") or "change-in-production" in settings.WEBHOOK_SECRET
    if default_secret:
        blockers.append(ReadinessFinding("security.default_secret", "blocker", "identity", "A development signing secret is configured."))
    if default_webhook_secret:
        blockers.append(ReadinessFinding("security.default_webhook_secret", "blocker", "webhooks", "A development webhook secret is configured."))
    if settings.DEMO_API_KEY.startswith("changeme"):
        blockers.append(ReadinessFinding("security.default_demo_key", "blocker", "api", "The default demonstration API key is configured."))

    if settings.ENABLE_SCHEDULER:
        blockers.append(ReadinessFinding("scheduler.in_process", "blocker", "scheduler", "The API process is allowed to start an in-process scheduler; horizontally scaled replicas can duplicate scheduled work."))

    object_backend = _setting(settings, "CONNECTOR_OBJECT_STORAGE_BACKEND", "disabled").lower()
    object_bucket = _setting(settings, "CONNECTOR_OBJECT_BUCKET")
    object_backend_ready = object_backend in {"s3", "r2", "s3_compatible"} and bool(object_bucket)
    if not object_backend_ready:
        blockers.append(ReadinessFinding("connectors.object_storage_missing", "blocker", "connectors", "A verified durable R2/S3-compatible connector object store and bucket are required."))
    if object_backend == "r2":
        _require_r2_contract(settings, blockers)
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
    derivable_runtime_root = bool(settings.SECRET_KEY and settings.WEBHOOK_SECRET) and not default_secret and not default_webhook_secret
    if not vault_key and not vault_ring and not derivable_runtime_root:
        blockers.append(ReadinessFinding("connectors.credential_vault_missing", "blocker", "connectors", "Encrypted retrievable connector credential custody is not configured."))
    elif not vault_key and not vault_ring:
        warnings.append(ReadinessFinding("connectors.credential_vault_derived", "warning", "connectors", "Connector credential custody uses the stable domain-separated runtime key fallback; configure an explicit versioned keyring for independent rotation."))

    # oauth_state_store already falls back to a strong application signing root.
    # Missing dedicated material is a rotation/isolation warning, not a runtime blocker.
    if not _setting(settings, "OAUTH_STATE_SIGNING_KEY"):
        if default_secret:
            blockers.append(ReadinessFinding("connectors.oauth_state_key_missing", "blocker", "connectors", "A secure OAuth state signing root is not configured."))
        else:
            warnings.append(ReadinessFinding("connectors.oauth_state_key_derived", "warning", "connectors", "OAuth state signing uses the application signing root fallback; configure a dedicated key for independent rotation."))

    _require_billing_contract(settings, blockers)

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
