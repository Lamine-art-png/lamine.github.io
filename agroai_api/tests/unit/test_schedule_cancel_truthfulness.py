"""A schedule is only reported cancelled when the controller confirms it."""
import uuid
from datetime import datetime

import pytest

from app.adapters.registry import AdapterRegistry
from app.core.security import get_current_tenant_id
from app.main import app
from app.models.schedule import Schedule


@pytest.fixture(autouse=True)
def _tenant():
    app.dependency_overrides[get_current_tenant_id] = lambda: "test-tenant"
    yield
    app.dependency_overrides.pop(get_current_tenant_id, None)


class _FailingAdapter:
    async def cancel_schedule(self, controller_id, provider_schedule_id):
        raise RuntimeError("controller unreachable")


class _ConfirmingAdapter:
    def __init__(self):
        self.calls = []

    async def cancel_schedule(self, controller_id, provider_schedule_id):
        self.calls.append(provider_schedule_id)
        return True


def _live_schedule(db):
    row = Schedule(
        id=str(uuid.uuid4()), tenant_id="test-tenant", controller_id="ctrl-1",
        start_time=datetime.utcnow(), duration_min=30, status="pending",
        provider="wiseconn", provider_schedule_id="wc-123",
        meta_data={"physical_execution_performed": True},
    )
    db.add(row)
    db.commit()
    return row


def test_provider_cancel_failure_is_not_reported_as_cancelled(client, auth_headers, db, monkeypatch):
    row = _live_schedule(db)
    monkeypatch.setattr(AdapterRegistry, "get_adapter", staticmethod(lambda provider: _FailingAdapter()))
    response = client.post(f"/v1/schedules/{row.id}:cancel", headers=auth_headers)
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "provider_cancel_failed"
    db.refresh(row)
    assert row.status == "pending"


def test_confirmed_provider_cancel_marks_schedule_cancelled(client, auth_headers, db, monkeypatch):
    row = _live_schedule(db)
    adapter = _ConfirmingAdapter()
    monkeypatch.setattr(AdapterRegistry, "get_adapter", staticmethod(lambda provider: adapter))
    response = client.post(f"/v1/schedules/{row.id}:cancel", headers=auth_headers)
    assert response.status_code == 200
    assert adapter.calls == ["wc-123"]
    db.refresh(row)
    assert row.status == "cancelled"
