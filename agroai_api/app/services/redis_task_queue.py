from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import redis
from redis.exceptions import ResponseError

from app.core.config import settings


@dataclass(frozen=True)
class QueueMessage:
    message_id: str
    job_id: str
    tenant_id: str
    task_type: str


class RedisTaskQueue:
    def __init__(self, client: Any | None = None):
        url = getattr(settings, "REDIS_URL", "").strip()
        if client is None and not url:
            raise RuntimeError("REDIS_URL is required")
        self.client = client or redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
        self.stream = os.getenv("TASK_QUEUE_STREAM", "agroai:tasks").strip() or "agroai:tasks"
        self.group = os.getenv("TASK_QUEUE_GROUP", "agroai-workers").strip() or "agroai-workers"
        self.maxlen = max(1000, int(os.getenv("TASK_QUEUE_STREAM_MAXLEN", "100000")))

    def ensure_group(self) -> None:
        try:
            self.client.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def enqueue(self, job_id: str, tenant_id: str, task_type: str) -> str:
        self.ensure_group()
        return str(
            self.client.xadd(
                self.stream,
                {"job_id": job_id, "tenant_id": tenant_id, "task_type": task_type},
                maxlen=self.maxlen,
                approximate=True,
            )
        )

    def read(self, consumer: str, *, block_ms: int = 5000) -> list[QueueMessage]:
        self.ensure_group()
        response = self.client.xreadgroup(self.group, consumer, {self.stream: ">"}, count=5, block=max(100, block_ms))
        result: list[QueueMessage] = []
        for _stream, entries in response or []:
            for message_id, fields in entries:
                if fields.get("job_id") and fields.get("tenant_id") and fields.get("task_type"):
                    result.append(QueueMessage(str(message_id), str(fields["job_id"]), str(fields["tenant_id"]), str(fields["task_type"])))
                else:
                    self.ack(str(message_id))
        return result

    def claim_stale(self, consumer: str, *, min_idle_ms: int = 120000) -> list[QueueMessage]:
        self.ensure_group()
        response = self.client.xautoclaim(self.stream, self.group, consumer, min_idle_time=max(1000, min_idle_ms), start_id="0-0", count=10)
        entries = response[1] if response and len(response) > 1 else []
        result: list[QueueMessage] = []
        for message_id, fields in entries:
            if fields.get("job_id") and fields.get("tenant_id") and fields.get("task_type"):
                result.append(QueueMessage(str(message_id), str(fields["job_id"]), str(fields["tenant_id"]), str(fields["task_type"])))
            else:
                self.ack(str(message_id))
        return result

    def ack(self, message_id: str) -> int:
        return int(self.client.xack(self.stream, self.group, message_id))

    def pending_count(self) -> int:
        self.ensure_group()
        summary = self.client.xpending(self.stream, self.group)
        if isinstance(summary, dict):
            return int(summary.get("pending") or 0)
        return int(summary[0] if summary else 0)

    def ping(self) -> bool:
        return bool(self.client.ping())


def queue_configured() -> bool:
    backend = getattr(settings, "TASK_QUEUE_BACKEND", "disabled").strip().lower()
    return backend in {"redis", "redis_streams", "redis-streams"} and bool(getattr(settings, "REDIS_URL", "").strip())


def get_task_queue(client: Any | None = None) -> RedisTaskQueue:
    if client is None and not queue_configured():
        raise RuntimeError("external task queue is not configured")
    return RedisTaskQueue(client)
