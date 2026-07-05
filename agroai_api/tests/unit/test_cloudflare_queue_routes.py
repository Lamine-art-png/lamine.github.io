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
