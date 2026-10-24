"""Regression checks for the synthetic DMRV contract and TEST-only API gate."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from fastapi import HTTPException

from app.api.v1.commercial_intelligence import IntelligenceRequest, _request_hash
from app.intelligence_platform.contract import PLATFORM_REQUEST_FIELDS
from app.intelligence_platform import runtime as intelligence_runtime
from app.platform_api.principal import PlatformPrincipal

from app.core.config import settings
from app.intelligence_platform.contract import ResponseFormat
from app.intelligence_platform.schemas import BUILTIN_SCHEMAS, resolve_schema, validation_errors
from app.platform_api.dmrv_advisory import DmrvAdvisoryPreviewRequest, simulate_dmrv_preview
from tests.unit.test_platform_api_foundation import _project_and_key
from tests.unit.test_platform_api_public_resources import PUBLIC_SCOPES, _enable_api
from tests.unit.dmrv_reference_fixture import synthetic_reference


@pytest.fixture(autouse=True)
def _synthetic_reference(monkeypatch):
    """Pin engine reference data so these contract tests do not depend on the committed dataset."""
    from app.intelligence_platform import dmrv_engine
    from app.platform_api import dmrv_advisory

    reference = synthetic_reference()
    monkeypatch.setattr(dmrv_engine, "load_reference", lambda path=None: reference)
    monkeypatch.setattr(dmrv_advisory, "load_reference", lambda path=None: reference)


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
    # v2: recommendations are grounded and cite resolvable evidence (v1 returned a static template with none).
    known = {item["id"] for item in result["evidence"]} | {item["id"] for item in result["calculations"]}
    assert result["provenance"]["evidence_ids"] and set(result["provenance"]["evidence_ids"]) <= known
    assert result["provenance"]["customer_field_data_used"] is False
    assert result["normalized_context"]["location_verified"] is False
    assert result["normalized_context"]["location_resolved"] is True
    categories = [item["category"] for item in result["structured_output"]["recommendations"]]
    assert set(categories) == {"irrigation", "nutrients", "soil", "monitoring", "sustainability"}
    assert categories == sorted(categories, key=["irrigation", "nutrients", "soil", "monitoring", "sustainability"].index)
    assert all(item["evidence_ids"] and set(item["evidence_ids"]) <= known for item in result["structured_output"]["recommendations"])
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
    {"location": {"country": "IN", "state": "UP", "district": "Meerut"}, "crop": {"name": "wheat", "cycle_id": "prod-cycle-7"}},
    {"location": {"country": "IN", "state": "UP", "district": "Meerut\u0000"}, "crop": {"name": "wheat"}},
    {"location": {"country": "IN", "state": "UP", "district": "Meerut"}, "crop": {"name": "wheat\n"}},
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
    monkeypatch.setattr(settings, "PLATFORM_API_DMRV_PREVIEW_ORGANIZATION_IDS", org.id)
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
    monkeypatch.setattr(settings, "PLATFORM_API_DMRV_PREVIEW_ORGANIZATION_IDS", "")
    assert client.post(route, headers=headers, json=_payload()).status_code == 404


def _live_payload(context: dict) -> IntelligenceRequest:
    return IntelligenceRequest(
        task="decision",
        question="Prepare evidence-grounded DMRV recommendations for this location and crop",
        context=context,
        response_format={"type": "agroai_schema", "name": "dmrv_advisory"},
    )


def test_live_dmrv_context_gate_occurs_before_charge(db, monkeypatch):
    monkeypatch.setattr(settings, "INTELLIGENCE_DMRV_ADVISORY_ENABLED", True)
    principal = PlatformPrincipal(authentication_type="internal_service")
    accepted = intelligence_runtime.resolve(db, principal, _live_payload(_payload()["context"]))
    assert accepted.schema and accepted.schema[0] == "dmrv_advisory"
    for broken in (
        {"location": {"country": "IN", "state": "Uttar Pradesh", "district": "Gautam Buddha Nagar"}},
        {"crop": {"name": "wheat"}},
        {"location": {"country": "IN", "state": "UP"}, "crop": {"name": "wheat"}},
        {"location": {"country": "in", "state": "UP", "district": "Meerut"}, "crop": {"name": "wheat"}},
        {"location": {"country": "IN", "state": "UP", "region": "Punjab", "district": "Meerut"}, "crop": {"name": "wheat"}},
    ):
        with pytest.raises(HTTPException) as failure:
            intelligence_runtime.resolve(db, principal, _live_payload(broken))
        assert failure.value.status_code == 422
        assert failure.value.detail["code"] == "dmrv_context_incomplete"


def test_dmrv_schema_prompt_requires_evidence_and_rejects_carbon_claims():
    args = {
        "question": "How should this district manage wheat?",
        "schema": BUILTIN_SCHEMAS["dmrv_advisory"],
        "analysis": {"answer": "Review the evidence."},
        "data_block": "",
        "language": None,
    }
    prompt = intelligence_runtime._structure_messages(schema_name="dmrv_advisory", apply_dmrv_policy=True, **args)
    policy = prompt[0]["content"]
    assert "carbon" in policy.lower()
    assert "fertilizer" in policy.lower()
    assert "geocoded evidence" in policy.lower()
    assert "never provide numeric irrigation depth" in policy.lower()
    other = intelligence_runtime._structure_messages(
        schema_name="recommendations",
        **{**args, "schema": BUILTIN_SCHEMAS["recommendations"]},
    )
    assert "geocoded evidence" not in other[0]["content"]



def test_custom_schema_named_dmrv_advisory_is_not_builtin_gated(db, monkeypatch):
    """Caller-owned schema names must not grant or trigger built-in DMRV policy."""
    principal = PlatformPrincipal(authentication_type="internal_service")
    payload = IntelligenceRequest(
        task="decision",
        question="Return a short custom JSON response",
        context={},
        response_format={
            "type": "json_schema",
            "name": "dmrv_advisory",
            "schema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
        },
    )
    for enabled in (False, True):
        monkeypatch.setattr(settings, "INTELLIGENCE_DMRV_ADVISORY_ENABLED", enabled)
        resolved = intelligence_runtime.resolve(db, principal, payload)
        assert resolved.schema is not None and resolved.schema[0] == "dmrv_advisory"
        assert resolved.schema_is_builtin_dmrv is False
        prompt = intelligence_runtime._structure_messages(
            question=payload.question,
            schema_name=resolved.schema[0],
            schema=resolved.schema[1],
            analysis={"answer": "Test"},
            data_block="",
            language=None,
            apply_dmrv_policy=resolved.schema_is_builtin_dmrv,
        )
        assert "geocoded evidence" not in prompt[0]["content"]

    monkeypatch.setattr(settings, "INTELLIGENCE_DMRV_ADVISORY_ENABLED", True)
    builtin = intelligence_runtime.resolve(db, principal, _live_payload(_payload()["context"]))
    assert builtin.schema_is_builtin_dmrv is True


def test_new_location_defaults_preserve_legacy_context_idempotency_hashes():
    # Before DMRV fields were typed, absent state and district did not appear
    # in serialized Location. Replays across release must hash identically.
    payload = IntelligenceRequest(
        question="Review almond crop risk",
        task="crop_risk",
        context={
            "location": {"country": "US", "region": "California"},
            "crop": {"name": "almond"},
        },
    )
    serialized = payload.model_dump(mode="json", by_alias=True)
    location = serialized["context"]["location"]
    assert location.pop("state") is None
    assert location.pop("district") is None
    serialized.pop("stream", None)
    for key, default in PLATFORM_REQUEST_FIELDS.items():
        if serialized.get(key) == default:
            serialized.pop(key, None)
    historic_hash = hashlib.sha256(
        json.dumps(serialized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert _request_hash(payload) == historic_hash

    explicit = IntelligenceRequest(
        question="Review almond crop risk",
        task="crop_risk",
        context={
            "location": {"country": "US", "region": "California", "state": "California", "district": "Fresno"},
            "crop": {"name": "almond"},
        },
    )
    assert _request_hash(explicit) != historic_hash

    # Older clients could send an explicitly null extra field; preserve its
    # inclusion in the canonical hash rather than conflating it with omission.
    explicit_null = IntelligenceRequest(
        question="Review almond crop risk",
        task="crop_risk",
        context={
            "location": {"country": "US", "region": "California", "state": None},
            "crop": {"name": "almond"},
        },
    )
    assert _request_hash(explicit_null) != historic_hash


def test_dmrv_live_schema_stays_hidden_until_explicitly_enabled(client, db, monkeypatch):
    from app.intelligence_platform.routes import builtin_schema, capabilities
    from fastapi import Response

    monkeypatch.setattr(settings, "INTELLIGENCE_DMRV_ADVISORY_ENABLED", False)
    principal = PlatformPrincipal(authentication_type="internal_service")
    payload = _live_payload(_payload()["context"])
    with pytest.raises(HTTPException) as refused:
        intelligence_runtime.resolve(db, principal, payload)
    assert refused.value.status_code == 404
    assert refused.value.detail["code"] == "dmrv_advisory_unavailable"
    names = {item["name"] for item in capabilities(Response())["structured_output"]["builtin_schemas"]}
    assert "dmrv_advisory" not in names
    with pytest.raises(HTTPException) as unavailable:
        builtin_schema("dmrv_advisory", Response())
    assert unavailable.value.status_code == 404

    monkeypatch.setattr(settings, "INTELLIGENCE_DMRV_ADVISORY_ENABLED", True)
    assert "dmrv_advisory" in {item["name"] for item in capabilities(Response())["structured_output"]["builtin_schemas"]}
    assert builtin_schema("dmrv_advisory", Response())["name"] == "dmrv_advisory"
    assert intelligence_runtime.resolve(db, principal, payload).schema[0] == "dmrv_advisory"


# ---------------------------------------------------------------- v2 grounded UAT contract

def test_dmrv_preview_accepts_variety_season_planting_and_synthetic_measurements():
    payload = DmrvAdvisoryPreviewRequest.model_validate({
        "context": {
            "location": {"country": "IN", "state": "Uttar Pradesh", "district": "Gautam Buddha Nagar"},
            "crop": {"name": "wheat", "variety": "HD-2967", "season": "rabi", "planted_at": "2025-11-10T00:00:00Z", "growth_stage": "flowering"},
        },
        "as_of": "2026-01-25",
        "measurements": {
            "data_classification": "synthetic",
            "soil_water": {"field_capacity_vwc_fraction": 0.3, "wilting_point_vwc_fraction": 0.13, "current_vwc_fraction": 0.18},
            "irrigation_system": {"type": "furrow", "efficiency": 0.6},
            "field_area_ha": 1.5,
            "soil_test": {"available_n_kg_ha": 240, "available_p_kg_ha": 12, "available_k_kg_ha": 190, "ph": 8.2},
        },
    })
    result = simulate_dmrv_preview(payload, SimpleNamespace(environment="test", id="project-A"))
    assert result["contract_version"] == "dmrv-uat/2"
    assert result["normalized_context"]["variety"] == "HD-2967"
    assert result["calendar"]["planting_basis"] == "planted_at"
    assert result["calendar"]["current_stage"] == "mid_season"
    assert result["measured_soil_water"]["trigger_reached"] is True
    assert result["soil_test"]["ratings"]["available_n_kg_ha"] == "low"
    assert result["provenance"]["uat_measurements_used"] is True
    assert result["billing"]["charged_cents"] == 0 and result["model_executed"] is False
    # Different measurements change identity and outcome deterministically.
    again = simulate_dmrv_preview(payload, SimpleNamespace(environment="test", id="project-A"))
    assert again == result
    without_soil_water = payload.model_copy(update={"measurements": payload.measurements.model_copy(update={"soil_water": None})})
    assert simulate_dmrv_preview(without_soil_water, SimpleNamespace(environment="test", id="project-A"))["id"] != result["id"]


@pytest.mark.parametrize("measurements", [
    {"soil_test": {"ph": 7.0}},  # classification missing
    {"data_classification": "production", "soil_test": {"ph": 7.0}},
    {"data_classification": "synthetic", "soil_test": {"ph": 7.0, "farmer_name": "x"}},
    {"data_classification": "synthetic", "soil_water": {"field_capacity_vwc_fraction": 1.4}},
    {"data_classification": "synthetic", "stage_lengths_days": [10, 10, 10]},
    {"data_classification": "synthetic", "stage_lengths_days": [10, 10, 10, 9000]},
])
def test_dmrv_preview_measurements_must_be_declared_synthetic_and_bounded(measurements):
    with pytest.raises(ValidationError):
        DmrvAdvisoryPreviewRequest.model_validate({**_payload(), "measurements": measurements})


def test_dmrv_preview_outputs_differ_by_crop_and_district():
    project = SimpleNamespace(environment="test", id="project-A")
    def run(state, district, crop):
        payload = DmrvAdvisoryPreviewRequest.model_validate({"context": {
            "location": {"country": "IN", "state": state, "district": district}, "crop": {"name": crop}}})
        return simulate_dmrv_preview(payload, project)["structured_output"]
    wheat, rice = run("Uttar Pradesh", "Gautam Buddha Nagar", "wheat"), run("Uttar Pradesh", "Gautam Buddha Nagar", "rice")
    bihar_rice = run("Bihar", "Aurangabad", "rice")
    assert wheat["recommendations"] != rice["recommendations"] != bihar_rice["recommendations"]
    assert wheat["summary"] != rice["summary"] != bihar_rice["summary"]


def test_dmrv_preview_http_contract_errors_isolation_and_zero_billing(client, db, monkeypatch):
    _enable_api(monkeypatch)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_DMRV_PREVIEW_ENABLED", True)
    _owner, org, _ws, _project, _sa, _key, token = _project_and_key(db, scopes=PUBLIC_SCOPES)
    _owner_b, _org_b, _ws_b, _project_b, _sa_b, _key_b, other_token = _project_and_key(db, scopes=PUBLIC_SCOPES)
    monkeypatch.setattr(settings, "PLATFORM_API_DMRV_PREVIEW_ORGANIZATION_IDS", f" {org.id} ,")
    route = "/v1/platform/recommendations/preview"
    headers = {"Authorization": f"Bearer {token}"}

    ok = client.post(route, headers=headers, json=_payload())
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["billing"] == {"charged_cents": 0} and body["model_executed"] is False and body["physical_execution"] is False
    assert body["geography"]["precision"] == "administrative_representative_point"
    assert body["water_balance"]["season_etc_mm"] > 0
    assert not validation_errors(body["structured_output"], BUILTIN_SCHEMAS["dmrv_advisory"])

    # Another organization's valid TEST key is not on the allowlist.
    assert client.post(route, headers={"Authorization": f"Bearer {other_token}"}, json=_payload()).status_code == 404

    mismatch = client.post(route, headers=headers, json=_payload(location={"country": "IN", "state": "Uttar Pradesh", "district": "Aurangabad"}))
    assert mismatch.status_code == 422
    error = mismatch.json()  # Platform API error envelope: top-level code/type/message/request_id
    assert error["code"] == "location_state_mismatch" and error["type"] == "request_error"
    assert {c["state"] for c in error["resolution"]["candidates"]} == {"Bihar", "Maharashtra"}

    unknown_crop = client.post(route, headers=headers, json=_payload(crop={"name": "quinoa"}))
    assert unknown_crop.status_code == 422 and unknown_crop.json()["code"] == "crop_not_supported"
    assert "wheat" in unknown_crop.json()["supported_crops"]

    production = client.post(route, headers=headers, json={**_payload(), "measurements": {"data_classification": "production"}})
    assert production.status_code == 422 and production.json()["code"] == "invalid_request"
    observations = client.post(route, headers=headers, json=_payload(observations=[{"type": "soil_vwc", "value": 0.2}]))
    assert observations.status_code == 422


def test_live_dmrv_grounding_is_computed_before_charge_and_is_citable(db, monkeypatch):
    monkeypatch.setattr(settings, "INTELLIGENCE_DMRV_ADVISORY_ENABLED", True)
    principal = PlatformPrincipal(authentication_type="internal_service")
    accepted = intelligence_runtime.resolve(db, principal, _live_payload({
        **_payload()["context"], "field": {"soil": {"field_capacity_vwc_fraction": 0.3, "wilting_point_vwc_fraction": 0.12}},
    }))
    grounding = accepted.dmrv_grounding
    assert grounding and grounding["water_balance"]["season_etc_mm"] > 0
    assert any(item["id"] == "dmrv:soil_water" for item in grounding["evidence"])
    section, ids = intelligence_runtime._dmrv_section(grounding)
    assert section.startswith("DMRV_GROUNDING ")
    # Must fit the 18k analysis window alongside customer context, or it would be omitted.
    assert len(section) <= intelligence_runtime.DMRV_SECTION_MAX_CHARS + len("DMRV_GROUNDING ")
    cited = {e for rec in grounding["structured_output"]["recommendations"] for e in rec["evidence_ids"]}
    assert cited <= ids
    # Every citable id resolves to a returned provenance record, including calculations.
    sources = {item["id"]: item for item in intelligence_runtime.dmrv_sources(grounding, ids)}
    assert ids <= set(sources)
    calc_ids = {i for i in cited if i.startswith("calc:")}
    assert calc_ids and all(sources[i]["tool_id"] and sources[i]["tool_version"] and sources[i]["output"] for i in calc_ids)
    assert "dmrv_grounding" not in json.dumps(grounding)  # no recursive embedding

    for context, code in (
        ({"location": {"country": "IN", "state": "Uttar Pradesh", "district": "Nowhere"}, "crop": {"name": "wheat"}}, "location_district_not_found"),
        ({"location": {"country": "IN", "state": "Uttar Pradesh", "district": "Gautam Buddha Nagar"}, "crop": {"name": "quinoa"}}, "crop_not_supported"),
    ):
        with pytest.raises(HTTPException) as refused:
            intelligence_runtime.resolve(db, principal, _live_payload(context))
        assert refused.value.status_code == 422 and refused.value.detail["code"] == code

    impersonation = {**_payload()["context"], "observations": [{"id": "ref:soilgrids:101", "type": "soil_ph", "value": 5.0}]}
    with pytest.raises(HTTPException) as clash:
        intelligence_runtime.resolve(db, principal, _live_payload(impersonation))
    assert clash.value.detail["code"] == "reserved_evidence_id"


def test_non_dmrv_live_runs_keep_customer_ids_and_get_no_grounding(db, monkeypatch):
    monkeypatch.setattr(settings, "INTELLIGENCE_DMRV_ADVISORY_ENABLED", True)
    principal = PlatformPrincipal(authentication_type="internal_service")
    payload = IntelligenceRequest(
        task="decision", question="Summarise this field",
        context={"observations": [{"id": "ref:lab-17", "type": "soil_ph", "value": 6.5}]},
        response_format={"type": "agroai_schema", "name": "recommendations"},
    )
    resolved = intelligence_runtime.resolve(db, principal, payload)
    assert resolved.dmrv_grounding is None
