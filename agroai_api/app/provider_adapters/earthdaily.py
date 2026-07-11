from __future__ import annotations

from datetime import datetime
from typing import Any

from app.provider_adapters.base import READINESS_AWAITING_CONTRACT, ProviderCapability, ProviderMetadata


class EarthDailyReadinessAdapter:
    provider_id = "earthdaily"

    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id=self.provider_id,
            display_name="EarthDaily",
            readiness=READINESS_AWAITING_CONTRACT,
            contract_required=True,
            capabilities=(
                ProviderCapability("connectivity_test", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("resource_discovery", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("field_boundary_mapping", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("satellite_scene_normalization", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("remote_sensing_observation_normalization", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("incremental_sync_cursor", READINESS_AWAITING_CONTRACT, implemented=True),
            ),
            notes=(
                "No EarthDaily endpoint, authentication method, product schema, rate limit, or webhook behavior is assumed.",
                "Adapter remains in integration-readiness mode until official partner documentation and sandbox credentials are supplied.",
            ),
        )

    def configuration_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "api_base_url": {"type": "string", "format": "uri"},
                "contract_reference": {"type": "string"},
            },
            "required": [],
        }

    def credential_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": True,
            "description": "Official EarthDaily credential schema is pending partner documentation.",
        }

    def validate_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": READINESS_AWAITING_CONTRACT,
            "authenticated": False,
            "message": "EarthDaily credentials cannot be validated until the official contract and sandbox are available.",
        }

    def discover_resources(self, credentials: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "status": READINESS_AWAITING_CONTRACT,
            "resources": [],
            "message": "EarthDaily resource discovery is contract-ready but not live.",
        }

    def normalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        external_id = str(record.get("scene_id") or record.get("id") or "").strip()
        acquired_at = record.get("acquired_at") or record.get("acquisition_timestamp")
        if acquired_at:
            acquired_at = str(acquired_at)
        return {
            "provider": self.provider_id,
            "canonical_type": "satellite_scene" if record.get("scene_id") or record.get("id") else "remote_sensing_observation",
            "external_id": external_id,
            "acquired_at": acquired_at,
            "field_id": record.get("field_id"),
            "quality_flags": list(record.get("quality_flags") or []),
            "provenance": {
                "provider": self.provider_id,
                "normalized_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "contract_status": READINESS_AWAITING_CONTRACT,
            },
            "metrics": {
                key: value
                for key, value in record.items()
                if key
                in {
                    "vegetation_index",
                    "thermal_observation",
                    "moisture_indicator",
                    "water_stress_indicator",
                    "cloud_cover",
                }
            },
            "provider_extensions": {
                key: value
                for key, value in record.items()
                if key
                not in {
                    "scene_id",
                    "id",
                    "acquired_at",
                    "acquisition_timestamp",
                    "field_id",
                    "quality_flags",
                    "vegetation_index",
                    "thermal_observation",
                    "moisture_indicator",
                    "water_stress_indicator",
                    "cloud_cover",
                }
            },
        }
