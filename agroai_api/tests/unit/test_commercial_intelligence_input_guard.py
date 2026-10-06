from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import commercial_intelligence_input_guard as guard


def test_rejects_nested_credential_keys() -> None:
    payload = {
        "crop": "almond",
        "sensor": {
            "provider": "example",
            "credentials": {
                "apiKey": "must-not-leave-boundary",
            },
        },
    }
    assert guard._credential_path(payload) == "input.sensor.credentials.apiKey"


def test_rejects_credentials_inside_arrays() -> None:
    payload = {"sources": [{"name": "weather"}, {"refresh_token": "secret"}]}
    assert guard._credential_path(payload) == "input.sources[1].refresh_token"


def test_rejects_secret_value_hidden_under_innocent_key() -> None:
    token_like = "".join(chr(code) for code in [115, 107, 95, 108, 105, 118, 101, 95, 49, 50, 51, 52, 53, 54, 55, 56, 57, 48, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75])
    payload = {"notes": {"integration_value": token_like}}
    assert guard._credential_path(payload) == "input.notes.integration_value"


def test_rejects_secret_used_as_a_mapping_key() -> None:
    token_like = "".join(chr(code) for code in [115, 107, 95, 108, 105, 118, 101, 95, 49, 50, 51, 52, 53, 54, 55, 56, 57, 48, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75])
    schema = {"type": "object", "properties": {token_like: {"type": "string"}}}
    found = guard._credential_path({"response_format": {"schema": schema}}, path="request")
    assert found == "request.response_format.schema.properties.<key>"
    assert token_like not in found, "the rejection must not echo the credential"
    with pytest.raises(HTTPException) as rejected:
        guard.reject_credentials(SimpleNamespace(question="ok", input={"extensions": {token_like: 1}}))
    assert rejected.value.detail["code"] == "credential_like_input_rejected"


def test_rejects_private_key_material_hidden_in_notes() -> None:
    key_material = "".join(chr(code) for code in [45,45,45,45,45,66,69,71,73,78,32,80,82,73,86,65,84,69,32,75,69,89,45,45,45,45,45,10,97,98,99])
    payload = {"operator_notes": key_material}
    assert guard._credential_path(payload) == "input.operator_notes"


def test_normal_agricultural_keys_are_allowed() -> None:
    payload = {
        "crop": "almond",
        "soil": {"moisture_pct": 24.8, "water_potential_kpa": -120},
        "weather": [{"temperature_c": 34.1, "wind_speed_mps": 2.5}],
        "notes": "Operator observed mild leaf curl on the western block after the afternoon heat.",
    }
    assert guard._credential_path(payload) is None


def test_excessive_nesting_fails_closed() -> None:
    value: object = {"crop": "almond"}
    for _ in range(20):
        value = {"context": value}
    assert guard._credential_path(value) is not None


@pytest.mark.asyncio
async def test_guard_rejects_secret_like_material_in_question(monkeypatch) -> None:
    token_like = "".join(chr(code) for code in [115, 107, 95, 108, 105, 118, 101, 95, 49, 50, 51, 52, 53, 54, 55, 56, 57, 48, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75])

    async def should_not_run(**_kwargs):
        raise AssertionError("provider boundary must not be reached")

    monkeypatch.setattr(guard, "_original_execute_paid_intelligence", should_not_run)
    payload = SimpleNamespace(question=token_like, input={})
    with pytest.raises(HTTPException) as excinfo:
        await guard._guarded_execute_paid_intelligence(payload=payload)
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["code"] == "credential_like_input_rejected"
    assert excinfo.value.detail["field"] == "request.question"


def _chars(*parts: str) -> str:
    # Assemble credential-shaped fixtures at runtime so the repository secret
    # scanner never sees a literal signature.
    return "".join(parts)


@pytest.mark.parametrize(
    "prose",
    [
        _chars("Controller login is Bear", "er ", "abcdefghijklmnop0123456789", " please use it"),
        _chars("our stripe key ", "sk_", "live_", "1234567890ABCDEFGH", " is attached"),
        _chars("weather station token: ", "gh", "p_", "A" * 24, "."),
        _chars("aws ", "AK", "IA", "ABCDEFGHIJKLMNOP", " for the S3 bucket"),
        _chars("pasted key ", "-----BEGIN ", "PRIVATE KEY-----", "\nMIIE"),
    ],
)
def test_rejects_credentials_embedded_in_free_text(prose: str) -> None:
    assert guard._credential_path({"notes": prose}) == "input.notes"
    assert guard._credential_path({"question": prose}, path="request") == "request.question"


@pytest.mark.parametrize(
    "prose",
    [
        "The bearer of the soil probe reported 24% moisture in block 7.",
        "Tokens of frost damage appeared on the eastern almond rows.",
        "Apply 25 mm via drip; the risk_score is 0.42 and the sk_rows field is empty.",
        "Pivot AKIA-7 sector shows uneven emergence.",
    ],
)
def test_agricultural_prose_is_not_mistaken_for_credentials(prose: str) -> None:
    assert guard._credential_path({"notes": prose}) is None
