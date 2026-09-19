from __future__ import annotations

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
    payload = {"notes": {"integration_value": "sk_" + "live_" + "1234567890ABCDEFGHIJK"}}
    assert guard._credential_path(payload) == "input.notes.integration_value"


def test_rejects_private_key_material_hidden_in_notes() -> None:
    payload = {"operator_notes": "-----BEGIN PRIVATE KEY-----\nabc"}
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
