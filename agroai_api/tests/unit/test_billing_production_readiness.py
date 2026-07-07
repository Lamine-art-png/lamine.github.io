from app.core.config import Settings
from app.services.production_readiness import evaluate_production_readiness


def _codes(report):
    return {item.code for item in report.blockers}


def _commercially_ready_settings():
    settings = Settings(
        DATABASE_URL="postgresql://db.example/agroai",
        SECRET_KEY="x" * 64,
        WEBHOOK_SECRET="y" * 64,
        DEMO_API_KEY="non-default-evaluation-key",
        ENABLE_SCHEDULER=False,
        CONNECTOR_UPLOAD_DIR="/tmp/agroai-spool",
        AI_PROVIDER="openrouter",
    )
    values = {
        "CONNECTOR_OBJECT_STORAGE_BACKEND": "s3",
        "CONNECTOR_OBJECT_BUCKET": "agroai-ingestion",
        "TASK_QUEUE_BACKEND": "redis_streams",
        "REDIS_URL": "redis://redis.example/0",
        "CONNECTOR_CREDENTIAL_MASTER_KEY": "configured",
        "OAUTH_STATE_SIGNING_KEY": "configured",
        "STRIPE_SECRET_KEY": "configured",
        "STRIPE_WEBHOOK_SECRET": "configured",
        "STRIPE_PRICE_PRO_MONTHLY": "price_pro_monthly",
        "STRIPE_PRICE_PRO_ANNUAL": "price_pro_annual",
        "STRIPE_PRICE_TEAM_MONTHLY": "price_team_monthly",
        "STRIPE_PRICE_TEAM_ANNUAL": "price_team_annual",
        "STRIPE_PRICE_NETWORK_MONTHLY": "price_network_monthly",
        "STRIPE_PRICE_NETWORK_ANNUAL": "price_network_annual",
    }
    settings.__dict__.update(values)
    return settings


def test_missing_stripe_webhook_secret_blocks_money_engine_release():
    settings = _commercially_ready_settings()
    settings.__dict__["STRIPE_WEBHOOK_SECRET"] = ""
    assert "billing.stripe_webhook_secret_missing" in _codes(evaluate_production_readiness(settings))


def test_every_self_serve_stripe_price_is_required():
    settings = _commercially_ready_settings()
    settings.__dict__["STRIPE_PRICE_NETWORK_ANNUAL"] = ""
    assert "billing.stripe_prices_missing" in _codes(evaluate_production_readiness(settings))


def test_stripe_price_values_must_be_price_identifiers():
    settings = _commercially_ready_settings()
    settings.__dict__["STRIPE_PRICE_TEAM_ANNUAL"] = "product_team_annual"
    assert "billing.stripe_price_ids_invalid" in _codes(evaluate_production_readiness(settings))


def test_self_serve_stripe_prices_must_be_distinct():
    settings = _commercially_ready_settings()
    settings.__dict__["STRIPE_PRICE_NETWORK_ANNUAL"] = settings.STRIPE_PRICE_NETWORK_MONTHLY
    assert "billing.stripe_price_ids_duplicate" in _codes(evaluate_production_readiness(settings))


def test_one_time_service_prices_are_optional_for_core_saas_readiness():
    settings = _commercially_ready_settings()
    settings.__dict__["STRIPE_PRICE_ASSURANCE_AUDIT_FARM"] = ""
    settings.__dict__["STRIPE_PRICE_ASSURANCE_AUDIT_NETWORK"] = ""
    report = evaluate_production_readiness(settings)
    assert report.ready is True, report.to_dict()
