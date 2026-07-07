from app.core.config import Settings
from app.services.production_readiness import evaluate_production_readiness


def configured_settings() -> Settings:
    return Settings(
        DATABASE_URL="postgresql://db.example/agroai",
        SECRET_KEY="x" * 64,
        WEBHOOK_SECRET="y" * 64,
        DEMO_API_KEY="non-default-evaluation-key",
        ENABLE_SCHEDULER=False,
        CONNECTOR_UPLOAD_DIR="/tmp/agroai-spool",
        CONNECTOR_OBJECT_STORAGE_BACKEND="r2",
        CONNECTOR_OBJECT_BUCKET="agroai-ingestion",
        CONNECTOR_OBJECT_ENDPOINT_URL="https://account-id.r2.cloudflarestorage.com",
        CLOUDFLARE_R2_ACCESS_KEY_ID="configured",
        CLOUDFLARE_R2_SECRET_ACCESS_KEY="configured",
        TASK_QUEUE_BACKEND="cloudflare_queues",
        CLOUDFLARE_QUEUE_PUBLISH_URL="https://api.agroai-pilot.com/v1/internal/edge/connector-tasks",
        CLOUDFLARE_QUEUE_PUBLISH_TOKEN="configured",
        CLOUDFLARE_QUEUE_CONSUMER_TOKEN="configured",
        CONNECTOR_CREDENTIAL_MASTER_KEY="configured",
        OAUTH_STATE_SIGNING_KEY="configured",
        AI_PROVIDER="openrouter",
        STRIPE_SECRET_KEY="configured",
        STRIPE_WEBHOOK_SECRET="configured",
        STRIPE_PRICE_PRO_MONTHLY="price_pro_monthly",
        STRIPE_PRICE_PRO_ANNUAL="price_pro_annual",
        STRIPE_PRICE_TEAM_MONTHLY="price_team_monthly",
        STRIPE_PRICE_TEAM_ANNUAL="price_team_annual",
        STRIPE_PRICE_NETWORK_MONTHLY="price_network_monthly",
        STRIPE_PRICE_NETWORK_ANNUAL="price_network_annual",
    )


def test_cloudflare_queue_configuration_is_ready_without_redis():
    report = evaluate_production_readiness(configured_settings())
    assert report.ready is True, report.to_dict()
    assert not report.blockers


def test_incomplete_cloudflare_queue_fails_closed():
    settings = configured_settings()
    settings.CLOUDFLARE_QUEUE_PUBLISH_TOKEN = ""
    report = evaluate_production_readiness(settings)
    codes = {item.code for item in report.blockers}
    assert "workers.external_queue_missing" in codes
    assert "workers.cloudflare_queue_incomplete" in codes
