from __future__ import annotations

import inspect
from types import SimpleNamespace

from app.services import field_intelligence as field_service
from app.services import field_operating_loop as operating_loop
from app.services.field_intelligence_operating_loop_runtime import (
    _repair_observation_summary,
    install_field_intelligence_operating_loop,
)


def test_field_intelligence_operating_loop_is_idempotently_installed():
    install_field_intelligence_operating_loop()
    first_create = field_service.create_task_from_observation
    first_serializer = operating_loop._task_from_job

    install_field_intelligence_operating_loop()

    assert field_service.create_task_from_observation is first_create
    assert operating_loop._task_from_job is first_serializer
    assert getattr(first_create, "__agroai_operating_loop__", False) is True
    assert getattr(first_serializer, "__agroai_operating_loop__", False) is True


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
    assert "created_from\": \"field_intelligence" in create_source
    assert "source_observation_id" in serializer_source


def test_invalid_object_summary_is_repaired_from_transcript():
    observation = SimpleNamespace(
        summary="[object Object]",
        corrected_transcript=None,
        transcript="Avocado canopy looks dry and may be under water stress.",
        structured_json={},
        recommended_action=None,
    )

    repaired = _repair_observation_summary(observation)

    assert repaired is observation
    assert observation.summary == "Avocado canopy looks dry and may be under water stress."


def test_invalid_json_summary_prefers_grounded_vision_summary_when_transcript_missing():
    observation = SimpleNamespace(
        summary="{'summary': 'bad serialization'}",
        corrected_transcript=None,
        transcript=None,
        structured_json={"vision": {"summary": "Visible canopy dryness requires field confirmation."}},
        recommended_action="Inspect the block.",
    )

    _repair_observation_summary(observation)

    assert observation.summary == "Visible canopy dryness requires field confirmation."
