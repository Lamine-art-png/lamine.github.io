import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import cloudflare_queue as module


app = FastAPI()
app.include_router(module.router, prefix="/v1")
client = TestClient(app)


def test_queue_delivery_requires_bearer_token(monkeypatch):
    monkeypatch.setattr(module.settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "consumer-test-value")
    response = client.post(
        "/v1/internal/queue/connector-task",
        json={"job_id": "job-1", "tenant_id": "tenant-1", "task_type": "connector_provider_sync"},
    )
    assert response.status_code == 401


def test_queue_contract_health_requires_matching_token(monkeypatch):
    monkeypatch.setattr(module.settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "consumer-test-value")
    response = client.get("/v1/internal/queue/health")
    assert response.status_code == 401


def test_queue_contract_health_proves_backend_contract_and_configuration(monkeypatch):
    monkeypatch.setattr(module.settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "consumer-test-value")
    monkeypatch.setattr(module, "queue_configured", lambda: True)
    response = client.get(
        "/v1/internal/queue/health",
        headers={"authorization": "Bearer consumer-test-value"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "contract": module.QUEUE_CONTRACT,
        "queue_configured": True,
    }


def test_queue_contract_health_fails_closed_when_backend_transport_is_incomplete(monkeypatch):
    monkeypatch.setattr(module.settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "consumer-test-value")
    monkeypatch.setattr(module, "queue_configured", lambda: False)
    response = client.get(
        "/v1/internal/queue/health",
        headers={"authorization": "Bearer consumer-test-value"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["contract"] == module.QUEUE_CONTRACT


def test_release_contract_reports_platform_api_activation_state(monkeypatch):
    monkeypatch.setattr(module.settings, "PLATFORM_API_ENABLED", True)
    monkeypatch.setattr(
        module,
        "evaluate_release_contract",
        lambda _db: {
            "status": "ok",
            "build_sha": "exact-sha",
            "schema_current": True,
            "database_heads": ["026_platform_api_operations"],
            "repository_heads": ["026_platform_api_operations"],
            "queue_configured": True,
        },
    )
    monkeypatch.setattr(
        module,
        "probe_object_storage",
        lambda: {"configured": True, "reachable": True},
    )
    monkeypatch.setattr(
        module,
        "evaluate_production_readiness",
        lambda _settings: SimpleNamespace(
            to_dict=lambda: {"ready": True, "blockers": []}
        ),
    )

    payload = asyncio.run(module.release_contract_health(db=SimpleNamespace()))

    assert payload["platform_api_enabled"] is True


def test_terminal_task_delivery_acknowledges_success(monkeypatch):
    monkeypatch.setattr(module.settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "consumer-test-value")
    monkeypatch.setattr(module, "process_connector_task", lambda **_kwargs: "succeeded")
    response = client.post(
        "/v1/internal/queue/connector-task",
        headers={"authorization": "Bearer consumer-test-value"},
        json={"job_id": "job-1", "tenant_id": "tenant-1", "task_type": "connector_provider_sync"},
    )
    assert response.status_code == 200
    assert response.json()["terminal"] is True


def test_transient_task_delivery_requests_queue_retry(monkeypatch):
    monkeypatch.setattr(module.settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "consumer-test-value")
    monkeypatch.setattr(module, "process_connector_task", lambda **_kwargs: "retrying")
    response = client.post(
        "/v1/internal/queue/connector-task",
        headers={"authorization": "Bearer consumer-test-value"},
        json={"job_id": "job-1", "tenant_id": "tenant-1", "task_type": "connector_provider_sync"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "connector_task_retry_required"
