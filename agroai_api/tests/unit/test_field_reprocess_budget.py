"""Regression coverage for bounded free record retries."""
from app.models.saas import EntitlementOverride
from app.models.operational_records import IngestionJob
from app.services.field_intelligence_rollout import ROLLOUT_FEATURE_KEY
from app.services.quota import committed_usage
from tests.unit.test_field_intelligence import _auth, _complete, _initiate, _process


def test_free_record_retries_are_bounded(client, db, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    monkeypatch.setattr("app.core.config.settings.FIELD_INTELLIGENCE_RELEASE_STATE", "general")
    monkeypatch.setattr("app.core.config.settings.FIELD_EXTRACTION_MODE", "deterministic")
    org, _, headers = _auth(db, org_id="org-limited-retries", workspace_id="ws-limited-retries")
    org.plan = "free"
    org.subscription_status = "inactive"
    db.add(EntitlementOverride(
        organization_id=org.id, feature_key=ROLLOUT_FEATURE_KEY,
        value_json={"value": "canary"},
    ))
    db.commit()
    result = _initiate(client, headers, client_capture_id="retry-original",
                       idempotency_key="retry-original", note_text="Pump needs inspection.")
    assert result.status_code == 200, result.text
    capture_id = result.json()["capture"]["id"]
    result = _complete(client, headers, capture_id)
    assert result.status_code == 202, result.text
    observation_id = result.json()["observation"]["id"]
    _process(db)

    url = f"/v1/field-intelligence/observations/{observation_id}"
    for index in (1, 2):
        patched = client.patch(
            url, json={"corrected_transcript": f"Inspection revision {index}"},
            headers=headers,
        )
        assert patched.status_code == 200, patched.text
        _process(db)

    count_query = db.query(IngestionJob).filter(
        IngestionJob.tenant_id == org.id,
        IngestionJob.idempotency_key.like(f"fi-proc-{observation_id}-%"),
    )
    assert count_query.count() == 2
    corrected = client.patch(url, json={"corrected_transcript": "Third inspection revision"}, headers=headers)
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["observation"]["status"] == "needs_review"
    assert count_query.count() == 2

    denied = client.post(f"{url}/reprocess", headers=headers)
    assert denied.status_code == 402, denied.text
    assert denied.json()["detail"]["code"] == "upgrade_required"
    assert committed_usage(db, org, "field_record") == 1


def test_free_correction_keeps_media_analysis_and_detections(client, db, monkeypatch):
    """A correction saved without provider AI re-extracts the text only; the
    photos did not change, so their analysis and detections must survive."""
    from app.models.field_intelligence import FieldObservation

    monkeypatch.setattr("app.core.config.settings.APP_ENV", "production")
    monkeypatch.setattr("app.core.config.settings.FIELD_INTELLIGENCE_RELEASE_STATE", "general")
    monkeypatch.setattr("app.core.config.settings.FIELD_EXTRACTION_MODE", "deterministic")
    org, _, headers = _auth(db, org_id="org-keep-vision", workspace_id="ws-keep-vision")
    org.plan = "free"
    org.subscription_status = "inactive"
    db.add(EntitlementOverride(organization_id=org.id, feature_key=ROLLOUT_FEATURE_KEY, value_json={"value": "canary"}))
    db.commit()
    capture_id = _initiate(client, headers, client_capture_id="keep-vision", idempotency_key="keep-vision",
                           note_text="Leaves look scorched.").json()["capture"]["id"]
    observation_id = _complete(client, headers, capture_id).json()["observation"]["id"]
    _process(db)
    url = f"/v1/field-intelligence/observations/{observation_id}"
    for index in (1, 2):  # spend the free reprocess allowance
        assert client.patch(url, json={"corrected_transcript": f"Revision {index}"}, headers=headers).status_code == 200
        _process(db)

    vision = {"analysis_state": "structured", "crop_condition": "stressed", "possible_issues": ["leaf scorch"]}
    detections = {"counts": {"totals": [{"label": "cluster", "observed_lower_bound": 4, "sum_upper_bound": 9}]}}
    row = db.query(FieldObservation).filter(FieldObservation.id == observation_id).one()
    row.structured_json = {**(row.structured_json or {}), "vision": vision, "detections": detections}
    db.commit()

    corrected = client.patch(url, json={"corrected_transcript": "Leaves scorched on row 4."}, headers=headers)
    assert corrected.status_code == 200, corrected.text
    db.expire_all()
    row = db.query(FieldObservation).filter(FieldObservation.id == observation_id).one()
    assert row.model_provider == "deterministic"
    assert row.structured_json["vision"] == vision
    assert row.structured_json["detections"] == detections
    assert db.query(IngestionJob).filter(
        IngestionJob.tenant_id == org.id, IngestionJob.idempotency_key.like(f"fi-proc-{observation_id}-%"),
    ).count() == 2
