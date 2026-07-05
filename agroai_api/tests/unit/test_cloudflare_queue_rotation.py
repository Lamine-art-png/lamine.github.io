from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import cloudflare_queue as module


app = FastAPI()
app.include_router(module.router, prefix="/v1")
client = TestClient(app)


def test_previous_consumer_token_is_accepted_during_rotation(monkeypatch):
    monkeypatch.setattr(module.settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "new-consumer-value")
    monkeypatch.setenv("CLOUDFLARE_QUEUE_CONSUMER_TOKEN_PREVIOUS", "old-consumer-value")
    monkeypatch.setattr(module, "queue_configured", lambda: True)

    response = client.get(
        "/v1/internal/queue/health",
        headers={"authorization": "Bearer old-consumer-value"},
    )

    assert response.status_code == 200
    assert response.json()["contract"] == module.QUEUE_CONTRACT


def test_unknown_consumer_token_is_rejected_during_rotation(monkeypatch):
    monkeypatch.setattr(module.settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "new-consumer-value")
    monkeypatch.setenv("CLOUDFLARE_QUEUE_CONSUMER_TOKEN_PREVIOUS", "old-consumer-value")

    response = client.get(
        "/v1/internal/queue/health",
        headers={"authorization": "Bearer unknown-value"},
    )

    assert response.status_code == 401
