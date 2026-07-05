from app.core.config import Settings
from app.services.production_readiness import evaluate_production_readiness


def _codes(report):
    return {item.code for item in report.blockers}


def test_default_settings_fail_closed_for_large_scale():
    report = evaluate_production_readiness(Settings())
    assert report.ready is False
    codes = _codes(report)
    assert "database.sqlite" in codes
    assert "security.default_secret" in codes
    assert "scheduler.in_process" in codes
    assert "connectors.local_upload_storage" in codes
    assert "connectors.object_storage_missing" in codes
    assert "workers.external_queue_missing" in codes
    assert "intelligence.provider_missing" in codes


def test_externalized_reference_configuration_can_be_ready():
    settings = Settings(
        DATABASE_URL="postgresql://db.example/agroai",
        SECRET_KEY="x" * 64,
        WEBHOOK_SECRET="y" * 64,
        DEMO_API_KEY="non-default-evaluation-key",
        ENABLE_SCHEDULER=False,
        CONNECTOR_UPLOAD_DIR="s3://agroai-ingestion/raw",
        AI_PROVIDER="openrouter",
    )
    settings.__dict__["CONNECTOR_OBJECT_STORAGE_BACKEND"] = "s3"
    settings.__dict__["TASK_QUEUE_BACKEND"] = "celery"
    settings.__dict__["REDIS_URL"] = "redis://redis.example/0"

    report = evaluate_production_readiness(settings)
    assert report.ready is True, report.to_dict()
    assert not report.blockers


def test_missing_external_queue_is_always_a_scale_blocker():
    settings = Settings(
        DATABASE_URL="postgresql://db.example/agroai",
        SECRET_KEY="x" * 64,
        WEBHOOK_SECRET="y" * 64,
        DEMO_API_KEY="non-default-evaluation-key",
        ENABLE_SCHEDULER=False,
        CONNECTOR_UPLOAD_DIR="s3://agroai-ingestion/raw",
        AI_PROVIDER="openrouter",
    )
    settings.__dict__["CONNECTOR_OBJECT_STORAGE_BACKEND"] = "s3"
    report = evaluate_production_readiness(settings)
    assert "workers.external_queue_missing" in _codes(report)


def test_in_process_scheduler_blocks_horizontal_replication_contract():
    settings = Settings(
        DATABASE_URL="postgresql://db.example/agroai",
        SECRET_KEY="x" * 64,
        WEBHOOK_SECRET="y" * 64,
        DEMO_API_KEY="non-default-evaluation-key",
        ENABLE_SCHEDULER=True,
        CONNECTOR_UPLOAD_DIR="s3://agroai-ingestion/raw",
        AI_PROVIDER="openrouter",
    )
    settings.__dict__["CONNECTOR_OBJECT_STORAGE_BACKEND"] = "s3"
    settings.__dict__["TASK_QUEUE_BACKEND"] = "celery"
    report = evaluate_production_readiness(settings)
    assert "scheduler.in_process" in _codes(report)
