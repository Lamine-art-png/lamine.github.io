"""Regression checks for the synthetic DMRV contract and TEST-only API gate."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.intelligence_platform.contract import ResponseFormat
from app.intelligence_platform.schemas import BUILTIN_SCHEMAS, resolve_schema, validation_errors
from app.platform_api.dmrv_advisory import DmrvAdvisoryPreviewRequest, simulate_dmrv_preview
from tests.unit.test_platform_api_foundation import _project_and_key
from tests.unit.test_platform_api_public_resources import PUBLIC_SCOPES, _enable_api


def _payload(**context_override) -> dict:
    context = {
        "location": {"country": "IN", "state": "Uttar Pradesh", "district": "Gautam Buddha Nagar"},
        "crop": {"name": "wheat", "growth_stage": "vegetative"},
    }
    context.update(context_override)
    return {"context": context}


def test_dmrv_preview_matches_live_structured_schema_without_inference():
    payload = DmrvAdvisoryPreviewRequest.model_validate(_payload())
    result = simulate_dmrv_preview(payload, SimpleNamespace(environment="test", id="project-A"))
    again = simulate_dmrv_preview(payload, SimpleNamespace(environment="test", id="project-A"))
    other_project = simulate_dmrv_preview(payload, SimpleNamespace(environment="test", id="project-B"))
    assert result == again
    assert result["id"] != other_project["id"]
    assert result["environment"] == "test"
    assert result["billing"]["charged_cents"] == 0
    assert result["model_executed"] is False
    assert result["physical_execution"] is False
    assert result["synthetic"] is True
    assert result["provenance"]["evidence_ids"] == []
    assert result["normalized_context"]["location_verified"] is False
    assert [item["category"] for item in result["structured_output"]["recommendations"]] == [
        "irrigation", "nutrients", "soil", "monitoring", "sustainability"
    ]
    assert all(not item["evidence_ids"] for item in result["structured_output"]["recommendations"])
    assert all(item["requires_human_approval"] for item in result["structured_output"]["recommendations"])
    assert not validation_errors(result["structured_output"], BUILTIN_SCHEMAS["dmrv_advisory"])
    resolved = resolve_schema(ResponseFormat(type="agroai_schema", name="dmrv_advisory"))
    assert resolved and resolved[0] == "dmrv_advisory"


@pytest.mark.parametrize("replacement", [
    {"location": {"country": "IN", "state": "Uttar Pradesh"}, "crop": {"name": "wheat"}},
    {"location": {"country": "in", "state": "UP", "district": "Meerut"}, "crop": {"name": "wheat"}},
    {"location": {"country": "IN", "state": "UP", "district": "Meerut", "latitude": 28.98}, "crop": {"name": "wheat"}},
    {"location": {"country": "IN", "state": "UP", "district": "Meerut"}, "crop": {"name": "wheat"}, "observations": [{"type": "soil_vwc", "value": 0.12}]},
    {"location": {"country": "IN", "state": "UP", "district": "Meerut", "other_data": "not-allowed"}, "crop": {"name": "wheat"}},
    {"location": {"country": "IN", "state": "UP", "district": "Meerut"}, "crop": {"name": "wheat", "variety": "private"}},
    {"location": {"country": "IN", "state": "UP", "district": "Meerut", "elevation_m": 123}, "crop": {"name": "wheat"}},
    {"location": {"country": "IN", "state": "UP", "region": "Punjab", "district": "Meerut"}, "crop": {"name": "wheat"}},
])
def test_dmrv_preview_rejects_unsafe_or_incomplete_input(replacement):
    with pytest.raises(ValidationError):
        DmrvAdvisoryPreviewRequest.model_validate({"context": replacement})


def test_dmrv_preview_rejects_live_project_even_directly():
    payload = DmrvAdvisoryPreviewRequest.model_validate(_payload())
    with pytest.raises(ValueError, match="TEST project"):
        simulate_dmrv_preview(payload, SimpleNamespace(environment="live", id="project-A"))


def test_dmrv_preview_http_requires_test_key_scope_and_flag(client, db, monkeypatch):
    _enable_api(monkeypatch)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_DMRV_PREVIEW_ENABLED", True)
    _owner, org, _workspace, project, _sa, _key, token = _project_and_key(db, scopes=PUBLIC_SCOPES)
    route = "/v1/platform/recommendations/preview"
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(route, headers=headers, json=_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["normalized_context"]["district"] == "Gautam Buddha Nagar"
    assert body["environment"] == "test"
    assert body["billing"]["charged_cents"] == 0

    # Same key and same contract are deterministic; no value transferred.
    repeat = client.post(route, headers=headers, json=_payload())
    assert repeat.status_code == 200
    assert repeat.json()["id"] == body["id"]

    monkeypatch.setattr(settings, "PLATFORM_API_DMRV_PREVIEW_ENABLED", False)
    assert client.post(route, headers=headers, json=_payload()).status_code == 404
    monkeypatch.setattr(settings, "PLATFORM_API_DMRV_PREVIEW_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", False)
    assert client.post(route, headers=headers, json=_payload()).status_code == 404
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", True)

    _owner2, _org2, _ws2, _project2, _sa2, _key2, live_key = _project_and_key(db, scopes=PUBLIC_SCOPES, environment="live")
    assert client.post(route, headers={"Authorization": f"Bearer {live_key}"}, json=_payload()).status_code == 403

    _owner3, _org3, _ws3, _project3, _sa3, _key3, missing_scope_key = _project_and_key(db, scopes=["projects:read"])
    assert client.post(route, headers={"Authorization": f"Bearer {missing_scope_key}"}, json=_payload()).status_code == 403
    assert client.post(route, json=_payload()).status_code == 401
