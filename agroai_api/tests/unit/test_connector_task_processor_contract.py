import re
from pathlib import Path

import pytest

from app.services import connector_task_processor as processor


def test_unknown_task_type_fails_before_database_session(monkeypatch):
    opened = []

    def forbidden_session():
        opened.append(True)
        raise AssertionError("database session must not open for unknown task type")

    monkeypatch.setattr(processor, "SessionLocal", forbidden_session)

    with pytest.raises(ValueError, match="unsupported connector task type"):
        processor.process_connector_task(
            job_id="job-1",
            tenant_id="tenant-1",
            task_type="unknown_task",
            worker_id="worker-test",
        )

    assert opened == []


def test_supported_task_type_set_is_exact():
    assert processor.SUPPORTED_TASK_TYPES == {
        "connector_ingest_object",
        "connector_provider_sync",
        "market_intelligence_cycle",
        "platform_api_operation",
        "platform_stripe_meter_export",
        "platform_webhook_delivery",
    }


def test_edge_queue_allowlist_matches_processor_task_types():
    # A task type the processor handles but the edge rejects would sit in the
    # outbox forever (and the reverse would be poison messages).
    source = (Path(__file__).resolve().parents[3] / "cloudflare" / "edge-gateway" / "src" / "index.ts").read_text(encoding="utf-8")
    allowlist = re.search(r"ALLOWED_TASK_TYPES = new Set<ConnectorTaskType>\(\[([^\]]*)\]\)", source)
    assert allowlist is not None
    assert set(re.findall(r'"([a-z_]+)"', allowlist.group(1))) == set(processor.SUPPORTED_TASK_TYPES)


def test_market_cycle_task_dispatches_to_market_cycle_processor(monkeypatch):
    calls = []

    class FakeSession:
        def close(self):
            calls.append("closed")

    monkeypatch.setattr(processor, "SessionLocal", FakeSession)
    monkeypatch.setattr(processor, "process_market_cycle_job", lambda db, **kwargs: calls.append(kwargs) or "succeeded")
    status = processor.process_connector_task(job_id="job-9", tenant_id="org-9", task_type="market_intelligence_cycle", worker_id="w")
    assert status == "succeeded"
    assert calls == [{"job_id": "job-9", "organization_id": "org-9", "worker_id": "w"}, "closed"]
