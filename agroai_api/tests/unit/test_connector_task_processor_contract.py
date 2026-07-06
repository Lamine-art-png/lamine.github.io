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
    }
