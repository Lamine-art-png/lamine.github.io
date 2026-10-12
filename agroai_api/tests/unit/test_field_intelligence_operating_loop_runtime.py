from __future__ import annotations

import inspect

from app.services import field_intelligence as field_service
from app.services import field_operating_loop as operating_loop
from app.services.field_intelligence_operating_loop_runtime import (
    _clean_observation_payload,
    install_field_intelligence_operating_loop,
)


def test_field_intelligence_operating_loop_is_idempotently_installed():
    install_field_intelligence_operating_loop()
    first_create = field_service.create_task_from_observation
    first_task_serializer = operating_loop._task_from_job
    first_observation_serializer = field_service.serialize_observation

    install_field_intelligence_operating_loop()

    assert field_service.create_task_from_observation is first_create
    assert operating_loop._task_from_job is first_task_serializer
    assert field_service.serialize_observation is first_observation_serializer
    assert getattr(first_create, "__agroai_operating_loop__", False) is True
    assert getattr(first_task_serializer, "__agroai_operating_loop__", False) is True
    assert getattr(first_observation_serializer, "__agroai_operating_loop__", False) is True


def test_field_intelligence_task_contract_keeps_observation_provenance():
    install_field_intelligence_operating_loop()
    create_source = inspect.getsource(field_service.create_task_from_observation)
    serializer_source = inspect.getsource(operating_loop._task_from_job)

    assert "with_for_update" in create_source
    assert "resolve_workspace" in create_source
    assert "task_workspace_id" in create_source
    assert "source_observation_id" in create_source
    assert "source_evidence_ids" in create_source
    assert "source_asset_ids" in create_source
    assert "already_existed" in create_source
    assert 'created_from": "field_intelligence' in create_source
    assert "source_observation_id" in serializer_source


def test_customer_observation_payload_never_exposes_object_dump_text():
    cleaned = _clean_observation_payload(
        {
            "summary": "[object Object]",
            "recommended_action": {"text": "Inspect the affected row and document the result."},
            "field_name": "North field",
            "block_name": None,
            "structured": {
                "vision": {
                    "summary": {"summary": "Visible leaf discoloration in the sampled frame."},
                    "recommended_follow_up": {"label": "Capture a close follow-up image."},
                }
            },
            "correlation": {"explanation": {"text": "Matches the operator's spoken observation."}},
            "task_ids": [None, "task_123"],
            "evidence_ids": ["evidence_1", None],
        }
    )

    assert cleaned["summary"] == "Visible leaf discoloration in the sampled frame."
    assert cleaned["recommended_action"] == "Inspect the affected row and document the result."
    assert cleaned["structured"]["vision"]["summary"] == "Visible leaf discoloration in the sampled frame."
    assert cleaned["correlation"]["explanation"] == "Matches the operator's spoken observation."
    assert cleaned["task_ids"] == ["task_123"]
    assert cleaned["evidence_ids"] == ["evidence_1"]
    assert "[object Object]" not in str(cleaned)


def test_degraded_visual_advice_is_never_promoted_to_the_recommended_action():
    """The vision extension does not promote a degraded follow-up; the serializer must not either."""
    degraded = _clean_observation_payload({
        "recommended_action": None,
        "structured": {"vision": {"analysis_state": "degraded", "recommended_follow_up": "Spray fungicide today."}},
        "correlation": {},
    })
    assert degraded["recommended_action"] is None
    structured = _clean_observation_payload({
        "recommended_action": None,
        "structured": {"vision": {"analysis_state": "structured", "recommended_follow_up": "Capture a close follow-up image."}},
    })
    assert structured["recommended_action"] == "Capture a close follow-up image."


def test_tasks_never_take_instructions_from_degraded_or_unchecked_visual_analysis(client, db):
    """Round-3 review: task creation must apply the same rule as the serializer."""
    import json

    from app.models.field_intelligence import FieldObservation
    from tests.unit.test_field_intelligence import _auth, _complete, _initiate, _process

    _, _, headers = _auth(db)
    for index, state in enumerate(("degraded", None)):
        capture = _initiate(client, headers, client_capture_id=f"cap-advice-{index}", idempotency_key=f"idem-advice-{index}",
                            note_text="Leaves look spotted on the west rows.").json()["capture"]
        observation_id = _complete(client, headers, capture["id"]).json()["observation"]["id"]
        _process(db)
        row = db.query(FieldObservation).filter(FieldObservation.id == observation_id).one()
        vision = {"recommended_follow_up": "Spray fungicide today.",
                  "hypotheses": [{"label": "fungal", "verification": "Spray fungicide today."}]}
        if state:
            vision["analysis_state"] = state
        row.structured_json = {**(row.structured_json or {}), "vision": vision}
        row.recommended_action = None
        row.correlation_json = {}
        db.commit()
        task = client.post(f"/v1/field-intelligence/observations/{observation_id}/tasks", json={}, headers=headers)
        assert task.status_code == 200, task.text
        assert "Spray fungicide" not in json.dumps(task.json()["task"]), state


def test_degraded_visual_summary_stays_labelled_when_used_as_a_fallback():
    cleaned = _clean_observation_payload({
        "summary": "", "transcript": "Leaves look scorched on the west rows.",
        "structured": {"vision": {"analysis_state": "degraded", "summary": "Brown lesions; spray copper today."}},
    })
    assert cleaned["summary"] == "Unverified visual note: Brown lesions; spray copper today."


def test_task_creation_tolerates_any_json_written_through_patch(client, db):
    """Round-5 review: a string became one-character requirements and a number raised a 500."""
    from tests.unit.test_field_intelligence import _auth, _complete, _initiate, _process

    _, _, headers = _auth(db)
    for index, value in enumerate(("Photograph the lower canopy", 7)):
        capture = _initiate(client, headers, client_capture_id=f"cap-json-{index}", idempotency_key=f"idem-json-{index}").json()["capture"]
        observation_id = _complete(client, headers, capture["id"]).json()["observation"]["id"]
        _process(db)
        patched = client.patch(f"/v1/field-intelligence/observations/{observation_id}", headers=headers,
                               json={"structured": {"evidence_requirements": value,
                                                    "vision": {"analysis_state": "structured", "uncertainties": value,
                                                               "hypotheses": value}}})
        assert patched.status_code == 200, patched.text
        task = client.post(f"/v1/field-intelligence/observations/{observation_id}/tasks", json={}, headers=headers)
        assert task.status_code == 200, task.text
        assert all(len(item) > 1 for item in task.json()["task"]["evidence_required"]), task.json()["task"]["evidence_required"]
