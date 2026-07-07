from __future__ import annotations

import gzip

import httpx

from app.adapters.openet import OpenETAdapter
from app.api.v1.connector_hub import router as connector_hub_router
from app.api.v1.connector_unified_v3 import UnifiedConnectRequest
from app.core.config import settings
from app.services.ag_connector_runtime import (
    _extract_geometry,
    _extract_openet_ids,
    build_ag_adapter,
)
from app.services.provider_sync_jobs import SUPPORTED_PROVIDERS


def test_agtech_providers_are_first_class_durable_sync_providers():
    assert SUPPORTED_PROVIDERS == {"google_drive", "outlook", "wiseconn", "talgil", "openet"}


def test_unified_routes_are_mounted_on_connector_hub_router():
    paths = {getattr(route, "path", "") for route in connector_hub_router.routes}
    assert "/connectors/unified/connect" in paths
    assert "/connectors/unified/{connection_id}/discovery" in paths
    assert "/connectors/unified/{connection_id}/selection" in paths
    assert "/connectors/unified/{connection_id}/sync" in paths
    assert "/connectors/unified/{connection_id}/status" in paths
    assert "/connectors/unified/{connection_id}/disconnect" in paths
    assert "/connectors/unified/{connection_id}/openet-boundary" in paths


def test_browser_payload_cannot_define_provider_destination():
    request = UnifiedConnectRequest.model_validate(
        {
            "provider": "openet",
            "api_key": "customer-value",
            "api_url": "https://attacker.invalid/collect",
        }
    )
    assert "api_url" not in request.model_dump()


def test_legacy_vault_api_url_cannot_redirect_provider_requests(monkeypatch):
    monkeypatch.setattr(settings, "WISECONN_API_URL", "https://api.wiseconn.com")
    monkeypatch.setattr(settings, "TALGIL_API_URL", "https://external.talgil.com/v1")
    monkeypatch.setattr(settings, "OPENET_API_URL", "https://openet-api.org")

    poisoned = {"api_key": "test-value", "api_url": "https://attacker.invalid/collect"}
    wiseconn = build_ag_adapter("wiseconn", poisoned)
    talgil = build_ag_adapter("talgil", poisoned)
    openet = build_ag_adapter("openet", poisoned)

    assert wiseconn.api_url == "https://api.wiseconn.com"
    assert talgil.api_url == "https://external.talgil.com/v1"
    assert openet.api_url == "https://openet-api.org"


def test_openet_gzip_payload_decodes_without_eval():
    payload = gzip.compress(b'[{"field_id":"field-123","value":4.2}]')
    response = httpx.Response(200, content=payload)
    decoded = OpenETAdapter._decode_payload(response)
    assert decoded == [{"field_id": "field-123", "value": 4.2}]


def test_openet_field_scope_extracts_only_explicit_openet_ids():
    payload = {
        "field_id": "internal-agroai-field",
        "metadata": {
            "openet_field_ids": ["oe-1", "oe-2"],
            "nested": {"openetFieldId": "oe-3"},
        },
    }
    ids = _extract_openet_ids(payload)
    assert ids == ["oe-1", "oe-2", "oe-3"]
    assert "internal-agroai-field" not in ids


def test_openet_geometry_extracts_nested_geojson_coordinates():
    payload = {
        "field": {
            "boundary": {
                "type": "Polygon",
                "coordinates": [[[-121.0, 38.0], [-121.1, 38.0], [-121.1, 38.1], [-121.0, 38.0]]],
            }
        }
    }
    geometry = _extract_geometry(payload)
    assert geometry[:4] == [-121.0, 38.0, -121.1, 38.0]
    assert len(geometry) >= 8
