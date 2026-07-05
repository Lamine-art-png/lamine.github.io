from redis.exceptions import ResponseError

from app.services.redis_task_queue import RedisTaskQueue


class FakeRedis:
    def __init__(self):
        self.group_created = False
        self.messages = []
        self.acked = []

    def xgroup_create(self, stream, group, id="0", mkstream=True):
        if self.group_created:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self.group_created = True
        return True

    def xadd(self, stream, fields, **kwargs):
        assert kwargs.get("maxlen") == 100000
        assert kwargs.get("approximate") is True
        message_id = f"{len(self.messages) + 1}-0"
        self.messages.append((message_id, dict(fields)))
        return message_id

    def xreadgroup(self, group, consumer, streams, count=5, block=5000):
        return [(next(iter(streams)), list(self.messages[:count]))] if self.messages else []

    def xautoclaim(self, stream, group, consumer, min_idle_time, start_id="0-0", count=10):
        return ("0-0", list(self.messages[:count]), [])

    def xack(self, stream, group, message_id):
        self.acked.append(message_id)
        return 1

    def xpending(self, stream, group):
        return {"pending": max(0, len(self.messages) - len(self.acked))}

    def ping(self):
        return True


def test_redis_stream_queue_enqueue_read_claim_ack_and_lag(monkeypatch):
    monkeypatch.setenv("TASK_QUEUE_STREAM", "test:tasks")
    monkeypatch.setenv("TASK_QUEUE_GROUP", "test-workers")
    monkeypatch.delenv("TASK_QUEUE_STREAM_MAXLEN", raising=False)
    fake = FakeRedis()
    queue = RedisTaskQueue(fake)

    message_id = queue.enqueue("job-1", "tenant-1", "connector_ingest_object")
    assert message_id == "1-0"
    assert queue.pending_count() == 1
    assert queue.read("worker-a")[0].job_id == "job-1"
    assert queue.claim_stale("worker-b", min_idle_ms=1000)[0].tenant_id == "tenant-1"
    assert queue.ack(message_id) == 1
    assert queue.pending_count() == 0
    assert fake.acked == ["1-0"]
    assert queue.ping() is True
