from __future__ import annotations

from app.models.saas import EntitlementOverride
from app.services.commercial_control import customer_safe_entitlement_payload
from app.services.field_intelligence_plan_access import ENTITLEMENT_KEY
from app.services.field_intelligence_rollout import ROLLOUT_FEATURE_KEY
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


def _enable_canary_rollout(db, organization) -> None:
    """Keep quota tests independent from the exact-SHA general-release gate.

    Production intentionally downgrades an unaligned general release to canary.
    These tests exercise plan quotas, not release alignment, so their fixture must
    explicitly enroll its own organization in the canary cohort.
    """

    db.add(
        EntitlementOverride(
            organization_id=organization.id,
            feature_key=ROLLOUT_FEATURE_KEY,
            value_json={"value": "canary"},
        )
    )


def test_plan_record_limits_are_customer_visible(db, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
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
        org.subscription_status = "inactive" if plan == "free" else ("contracted" if plan == "enterprise" else "active")
        db.commit()
        payload = customer_safe_entitlement_payload(db, org)
        assert payload["quotas"]["field_intelligence.records.monthly"] == limit
        if plan == "free":
            assert payload["capabilities"]["field_intelligence.model_extraction"] == "enabled"


def test_inactive_paid_plan_receives_free_equivalent_launch_access(db, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    org, _, _ = _auth(db, org_id="org-inactive-paid-fi", workspace_id="ws-inactive-paid-fi")
    org.plan = "professional"
    org.subscription_status = "past_due"
    db.commit()

    payload = customer_safe_entitlement_payload(db, org)
    assert payload["plan"] == "professional"
    assert payload["quotas"]["field_intelligence.records.monthly"] == 2
    assert payload["capabilities"]["field_intelligence.model_extraction"] == "enabled"


def test_enterprise_override_preserves_contract_configured_capacity(db, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    org, _, _ = _auth(db, org_id="org-enterprise-fi", workspace_id="ws-enterprise-fi")
    org.plan = "enterprise"
    org.subscription_status = "contracted"
    db.add(
        EntitlementOverride(
            organization_id=org.id,
            feature_key=ENTITLEMENT_KEY,
            value_json={"value": 9000},
        )
    )
    db.commit()

    payload = customer_safe_entitlement_payload(db, org)
    assert payload["quotas"]["field_intelligence.records.monthly"] == 9000


def test_free_plan_allows_two_completed_records_and_blocks_third(client, db, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FIELD_INTELLIGENCE_RELEASE_STATE", "general")
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    org, _, headers = _auth(db, org_id="org-free-fi", workspace_id="ws-free-fi")
    org.plan = "free"
    org.subscription_status = "inactive"
    _enable_canary_rollout(db, org)
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
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    org, _, headers = _auth(db, org_id="org-idem-fi", workspace_id="ws-idem-fi")
    org.plan = "free"
    _enable_canary_rollout(db, org)
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
