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
