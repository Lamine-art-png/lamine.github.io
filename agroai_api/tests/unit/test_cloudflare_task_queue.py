import pytest

from app.services.cloudflare_task_queue import CloudflareTaskQueuePublisher


class FakeResponse:
    def __init__(self, status_code=202, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"status": "queued", "job_id": "job-1"}
        self.text = text

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.calls = []

    def post(self, url, *, json, headers):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.response


def test_publisher_posts_authenticated_bounded_task_envelope():
    client = FakeClient()
    publisher = CloudflareTaskQueuePublisher(
        endpoint_url="https://api.agroai-pilot.com/v1/internal/edge/connector-tasks",
        token="test-publish-value",
        client=client,
    )
    marker = publisher.enqueue("job-1", "tenant-1", "connector_provider_sync")
    assert marker == "job-1"
    assert client.calls == [{
        "url": "https://api.agroai-pilot.com/v1/internal/edge/connector-tasks",
        "json": {"job_id": "job-1", "tenant_id": "tenant-1", "task_type": "connector_provider_sync"},
        "headers": {
            "authorization": "Bearer test-publish-value",
            "content-type": "application/json",
            "accept": "application/json",
        },
    }]


def test_publisher_rejects_non_https_endpoint():
    with pytest.raises(RuntimeError, match="HTTPS"):
        CloudflareTaskQueuePublisher(endpoint_url="http://example.invalid/tasks", token="value")


def test_publisher_rejects_unconfirmed_enqueue():
    client = FakeClient(FakeResponse(status_code=200, payload={"status": "ok"}))
    publisher = CloudflareTaskQueuePublisher(
        endpoint_url="https://api.agroai-pilot.com/v1/internal/edge/connector-tasks",
        token="test-publish-value",
        client=client,
    )
    with pytest.raises(RuntimeError, match="status=200"):
        publisher.enqueue("job-1", "tenant-1", "connector_provider_sync")
