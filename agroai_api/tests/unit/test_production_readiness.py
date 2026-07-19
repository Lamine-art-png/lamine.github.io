import base64
import json

from app.core.config import Settings
from app.services.production_readiness import evaluate_production_readiness


def _codes(report):
    return {item.code for item in report.blockers}


def _ready_settings():
    settings = Settings(
        DATABASE_URL="postgresql://db.example/agroai",
        SECRET_KEY="x" * 64,
        WEBHOOK_SECRET="y" * 64,
        DEMO_API_KEY="non-default-evaluation-key",
        ENABLE_SCHEDULER=False,
        CONNECTOR_UPLOAD_DIR="/tmp/agroai-spool",
        AI_PROVIDER="openrouter",
    )
    settings.__dict__["CONNECTOR_OBJECT_STORAGE_BACKEND"] = "s3"
    settings.__dict__["CONNECTOR_OBJECT_BUCKET"] = "agroai-ingestion"
    settings.__dict__["TASK_QUEUE_BACKEND"] = "redis_streams"
    settings.__dict__["REDIS_URL"] = "redis://redis.example/0"
    settings.__dict__["CONNECTOR_CREDENTIAL_MASTER_KEY"] = "configured"
    key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii").rstrip("=")
    settings.__dict__["CONNECTOR_CREDENTIAL_KEYS_JSON"] = json.dumps({"v1": key})
    settings.__dict__["PLATFORM_API_EDGE_AUTH_SECRET"] = "dedicated-edge-origin-secret"
    settings.__dict__["OAUTH_STATE_SIGNING_KEY"] = "configured"
    settings.__dict__["STRIPE_SECRET_KEY"] = "configured"
    settings.__dict__["STRIPE_WEBHOOK_SECRET"] = "configured"
    settings.__dict__["STRIPE_PRICE_PRO_MONTHLY"] = "price_pro_monthly"
    settings.__dict__["STRIPE_PRICE_PRO_ANNUAL"] = "price_pro_annual"
    settings.__dict__["STRIPE_PRICE_TEAM_MONTHLY"] = "price_team_monthly"
    settings.__dict__["STRIPE_PRICE_TEAM_ANNUAL"] = "price_team_annual"
    settings.__dict__["STRIPE_PRICE_NETWORK_MONTHLY"] = "price_network_monthly"
    settings.__dict__["STRIPE_PRICE_NETWORK_ANNUAL"] = "price_network_annual"
    return settings


def _ready_r2_settings():
    settings = _ready_settings()
    settings.__dict__["CONNECTOR_OBJECT_STORAGE_BACKEND"] = "r2"
    settings.__dict__["CONNECTOR_OBJECT_ENDPOINT_URL"] = "https://account-id.r2.cloudflarestorage.com"
    settings.__dict__["CLOUDFLARE_R2_ACCESS_KEY_ID"] = "configured"
    settings.__dict__["CLOUDFLARE_R2_SECRET_ACCESS_KEY"] = "configured"
    return settings


def test_default_settings_fail_closed_for_large_scale():
    report = evaluate_production_readiness(Settings())
    assert report.ready is False
    codes = _codes(report)
    assert "database.sqlite" in codes
    assert "security.default_secret" in codes
    assert "scheduler.in_process" not in codes
    assert "connectors.local_upload_storage" in codes
    assert "connectors.object_storage_missing" in codes
    assert "workers.external_queue_missing" in codes
    assert "billing.stripe_secret_missing" in codes
    assert "billing.stripe_webhook_secret_missing" in codes
    assert "billing.stripe_prices_missing" in codes
    assert "intelligence.provider_missing" in codes


def test_externalized_reference_configuration_can_be_ready():
    report = evaluate_production_readiness(_ready_settings())
    assert report.ready is True, report.to_dict()
    assert not report.blockers


def test_r2_reference_configuration_can_be_ready():
    report = evaluate_production_readiness(_ready_r2_settings())
    assert report.ready is True, report.to_dict()
    assert not report.blockers


def test_r2_requires_https_endpoint_and_paired_credentials():
    settings = _ready_r2_settings()
    settings.__dict__["CONNECTOR_OBJECT_ENDPOINT_URL"] = "http://account-id.r2.cloudflarestorage.com"
    settings.__dict__["CLOUDFLARE_R2_SECRET_ACCESS_KEY"] = ""

    report = evaluate_production_readiness(settings)

    codes = _codes(report)
    assert "connectors.r2_endpoint_not_https" in codes
    assert "connectors.r2_credentials_missing" in codes


def test_missing_external_queue_is_always_a_scale_blocker():
    settings = _ready_settings()
    settings.__dict__["TASK_QUEUE_BACKEND"] = "disabled"
    settings.__dict__["REDIS_URL"] = ""
    report = evaluate_production_readiness(settings)
    assert "workers.external_queue_missing" in _codes(report)


def test_in_process_scheduler_blocks_horizontal_replication_contract():
    settings = _ready_settings()
    settings.ENABLE_SCHEDULER = True
    report = evaluate_production_readiness(settings)
    assert "scheduler.in_process" in _codes(report)


def test_platform_api_enabled_requires_distributed_redis_limiter():
    settings = _ready_settings()
    settings.__dict__["PLATFORM_API_ENABLED"] = True
    settings.__dict__["PLATFORM_API_RATE_LIMIT_BACKEND"] = "memory"
    settings.__dict__["PLATFORM_API_REDIS_URL"] = ""

    report = evaluate_production_readiness(settings)

    codes = _codes(report)
    assert "platform_api.rate_limiter_not_distributed" in codes
    assert "platform_api.redis_missing" not in codes


def test_platform_api_enabled_with_redis_limiter_is_ready_when_other_contracts_are_ready():
    settings = _ready_settings()
    settings.__dict__["PLATFORM_API_ENABLED"] = True
    settings.__dict__["PLATFORM_API_RATE_LIMIT_BACKEND"] = "redis"
    settings.__dict__["PLATFORM_API_REDIS_URL"] = "redis://platform-limiter.example/0"

    report = evaluate_production_readiness(settings)

    assert report.ready is True, report.to_dict()


def test_platform_api_enabled_without_any_redis_url_fails_readiness():
    settings = _ready_settings()
    settings.__dict__["PLATFORM_API_ENABLED"] = True
    settings.__dict__["PLATFORM_API_RATE_LIMIT_BACKEND"] = "redis"
    settings.__dict__["PLATFORM_API_REDIS_URL"] = ""
    settings.__dict__["REDIS_URL"] = ""

    report = evaluate_production_readiness(settings)

    assert "platform_api.redis_missing" in _codes(report)


def test_platform_api_enabled_requires_authenticated_edge_client_ip_context():
    settings = _ready_settings()
    settings.__dict__["PLATFORM_API_ENABLED"] = True
    settings.__dict__["PLATFORM_API_RATE_LIMIT_BACKEND"] = "redis"
    settings.__dict__["PLATFORM_API_EDGE_AUTH_SECRET"] = ""

    report = evaluate_production_readiness(settings)

    assert "platform_api.edge_auth_missing" in _codes(report)


def test_disabled_platform_api_does_not_require_edge_auth_for_deployment_readiness():
    settings = _ready_settings()
    settings.__dict__["PLATFORM_API_ENABLED"] = False
    settings.__dict__["PLATFORM_API_EDGE_AUTH_SECRET"] = ""

    report = evaluate_production_readiness(settings)

    assert report.ready is True, report.to_dict()
    assert "platform_api.edge_auth_missing" not in _codes(report)


def test_platform_api_enabled_requires_explicit_vault_keyring():
    settings = _ready_settings()
    settings.__dict__["PLATFORM_API_ENABLED"] = True
    settings.__dict__["PLATFORM_API_RATE_LIMIT_BACKEND"] = "redis"
    settings.__dict__["CONNECTOR_CREDENTIAL_KEYS_JSON"] = ""

    report = evaluate_production_readiness(settings)

    assert "platform_api.explicit_vault_keyring_missing" in _codes(report)


def test_platform_api_enabled_rejects_fail_open_limiter_configuration():
    settings = _ready_settings()
    settings.__dict__["PLATFORM_API_ENABLED"] = True
    settings.__dict__["PLATFORM_API_RATE_LIMIT_BACKEND"] = "redis"
    settings.__dict__["PLATFORM_API_RATE_LIMIT_FAIL_OPEN"] = True

    report = evaluate_production_readiness(settings)

    assert "platform_api.rate_limiter_fail_open" in _codes(report)
