from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings


class CloudflareTaskQueuePublisher:
    def __init__(
        self,
        *,
        endpoint_url: str,
        token: str,
        client: Any | None = None,
        timeout_seconds: float = 15.0,
    ):
        endpoint = endpoint_url.strip()
        secret = token.strip()
        if not endpoint:
            raise RuntimeError("CLOUDFLARE_QUEUE_PUBLISH_URL is required")
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RuntimeError("Cloudflare queue publish endpoint must be HTTPS")
        if not secret:
            raise RuntimeError("CLOUDFLARE_QUEUE_PUBLISH_TOKEN is required")
        self.endpoint_url = endpoint
        self.token = secret
        self.client = client
        self.timeout_seconds = timeout_seconds

    def enqueue(self, job_id: str, tenant_id: str, task_type: str) -> str:
        payload = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "task_type": str(task_type),
        }
        headers = {
            "authorization": f"Bearer {self.token}",
            "content-type": "application/json",
            "accept": "application/json",
        }
        if self.client is not None:
            response = self.client.post(self.endpoint_url, json=payload, headers=headers)
        else:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False) as client:
                response = client.post(self.endpoint_url, json=payload, headers=headers)
        if response.status_code != 202:
            body = (getattr(response, "text", "") or "")[:500]
            raise RuntimeError(f"Cloudflare queue publish failed status={response.status_code} body={body}")
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError("Cloudflare queue publish returned invalid JSON") from exc
        if data.get("status") != "queued":
            raise RuntimeError("Cloudflare queue publish response did not confirm enqueue")
        return str(data.get("job_id") or job_id)


def cloudflare_queue_configured() -> bool:
    backend = getattr(settings, "TASK_QUEUE_BACKEND", "disabled").strip().lower()
    return backend in {"cloudflare", "cloudflare_queues", "cloudflare-queues"} and bool(
        getattr(settings, "CLOUDFLARE_QUEUE_PUBLISH_URL", "").strip()
        and getattr(settings, "CLOUDFLARE_QUEUE_PUBLISH_TOKEN", "").strip()
        and getattr(settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "").strip()
    )


def get_cloudflare_task_publisher(client: Any | None = None) -> CloudflareTaskQueuePublisher:
    if not cloudflare_queue_configured():
        raise RuntimeError("Cloudflare task queue is not configured")
    return CloudflareTaskQueuePublisher(
        endpoint_url=getattr(settings, "CLOUDFLARE_QUEUE_PUBLISH_URL", "").strip(),
        token=getattr(settings, "CLOUDFLARE_QUEUE_PUBLISH_TOKEN", "").strip(),
        client=client,
    )
