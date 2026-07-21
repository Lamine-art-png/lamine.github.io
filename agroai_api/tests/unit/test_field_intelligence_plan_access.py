from __future__ import annotations

from app.services.commercial_control import customer_safe_entitlement_payload
from app.services.quota import committed_usage
from tests.unit.test_field_intelligence import _auth, _complete, _initiate


def _new_capture(client, headers, index: int):
    initiated = _initiate(
        client,
        headers,
        client_capture_id=f"quota-cap-{index}",
        idempotency_key=f"quota-idem-{index}",
        note_text=f"Field observation {index}",
    )
    assert initiated.status_code == 200, initiated.text
    return initiated.json()["capture"]["id"]


def test_plan_record_limits_are_customer_visible(db):
    org, _, _ = _auth(db, org_id="org-plan-limits", workspace_id="ws-plan-limits")
    expected = {
        "free": 2,
        "professional": 100,
        "team": 500,
        "network": 2500,
        "enterprise": None,
    }
    for plan, limit in expected.items():
        org.plan = plan
        db.commit()
        payload = customer_safe_entitlement_payload(db, org)
        assert payload["quotas"]["field_intelligence.records.monthly"] == limit
        if plan == "free":
            assert payload["capabilities"]["field_intelligence.model_extraction"] == "enabled"


def test_free_plan_allows_two_completed_records_and_blocks_third(client, db, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FIELD_INTELLIGENCE_RELEASE_STATE", "general")
    org, _, headers = _auth(db, org_id="org-free-fi", workspace_id="ws-free-fi")
    org.plan = "free"
    org.subscription_status = "inactive"
    db.commit()

    first = _new_capture(client, headers, 1)
    second = _new_capture(client, headers, 2)
    third = _new_capture(client, headers, 3)

    assert _complete(client, headers, first).status_code == 202
    assert _complete(client, headers, first).status_code == 202
    assert _complete(client, headers, second).status_code == 202

    blocked = _complete(client, headers, third)
    assert blocked.status_code == 429, blocked.text
    detail = blocked.json()["detail"]
    assert detail["code"] == "quota_exceeded"
    assert detail["metric"] == "field_intelligence.records.monthly"
    assert detail["limit"] == 2
    assert detail["used"] == 2
    assert detail["recommended_plan"] == "professional"
    assert committed_usage(db, org, "field_record") == 2


def test_corrections_and_reprocessing_do_not_consume_another_record(client, db, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FIELD_INTELLIGENCE_RELEASE_STATE", "general")
    org, _, headers = _auth(db, org_id="org-idem-fi", workspace_id="ws-idem-fi")
    org.plan = "free"
    db.commit()

    capture_id = _new_capture(client, headers, 1)
    completed = _complete(client, headers, capture_id)
    assert completed.status_code == 202
    observation_id = completed.json()["observation"]["id"]

    assert _complete(client, headers, capture_id).status_code == 202
    assert client.patch(
        f"/v1/field-intelligence/observations/{observation_id}",
        json={"corrected_transcript": "Corrected field observation"},
        headers=headers,
    ).status_code == 200
    assert client.post(
        f"/v1/field-intelligence/observations/{observation_id}/reprocess",
        headers=headers,
    ).status_code == 202
    assert committed_usage(db, org, "field_record") == 1
