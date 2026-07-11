from __future__ import annotations

from datetime import datetime
from typing import Any

from app.provider_adapters.base import READINESS_AWAITING_CONTRACT, ProviderCapability, ProviderMetadata


class ValleyIrrigationReadinessAdapter:
    provider_id = "valley_irrigation"

    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id=self.provider_id,
            display_name="Valley Irrigation",
            readiness=READINESS_AWAITING_CONTRACT,
            contract_required=True,
            capabilities=(
                ProviderCapability("connectivity_test", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("capability_discovery", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("resource_discovery", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("equipment_status_normalization", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("telemetry_normalization", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("alarm_normalization", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("incremental_sync_cursor", READINESS_AWAITING_CONTRACT, implemented=True),
                ProviderCapability("physical_command_execution", "disabled", implemented=False, write_capability=True),
            ),
            notes=(
                "Valley or AgSense endpoint, authentication, telemetry schema, rate limit, webhook behavior, and write contract are not assumed.",
                "Physical irrigation commands are disabled and require a separate safety-reviewed activation.",
            ),
        )

    def configuration_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "api_base_url": {"type": "string", "format": "uri"},
                "connection_variant": {"type": "string", "enum": ["valley_direct", "agsense_contract", "unknown"]},
                "contract_reference": {"type": "string"},
            },
            "required": [],
        }

    def credential_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": True,
            "description": "Official Valley/AgSense credential schema is pending partner documentation.",
        }

    def validate_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": READINESS_AWAITING_CONTRACT,
            "authenticated": False,
            "message": "Valley credentials cannot be validated until the official contract and sandbox are available.",
            "write_capability": "disabled",
        }

    def discover_resources(self, credentials: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "status": READINESS_AWAITING_CONTRACT,
            "resources": [],
            "write_capability": "disabled",
            "message": "Valley read-only resource discovery is contract-ready but not live.",
        }

    def normalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        external_id = str(record.get("equipment_id") or record.get("pivot_id") or record.get("id") or "").strip()
        occurred_at = record.get("observed_at") or record.get("timestamp")
        if occurred_at:
            occurred_at = str(occurred_at)
        known = {
            "equipment_id",
            "pivot_id",
            "id",
            "field_id",
            "observed_at",
            "timestamp",
            "position",
            "operating_mode",
            "pressure",
            "flow",
            "alarm_code",
            "alarm_state",
            "event_type",
        }
        return {
            "provider": self.provider_id,
            "canonical_type": record.get("event_type") or ("alarm" if record.get("alarm_code") else "equipment_state"),
            "external_id": external_id,
            "field_id": record.get("field_id"),
            "observed_at": occurred_at,
            "equipment_state": {
                "position": record.get("position"),
                "operating_mode": record.get("operating_mode"),
                "pressure": record.get("pressure"),
                "flow": record.get("flow"),
            },
            "alarm": {
                "code": record.get("alarm_code"),
                "state": record.get("alarm_state"),
            }
            if record.get("alarm_code")
            else None,
            "provenance": {
                "provider": self.provider_id,
                "normalized_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "contract_status": READINESS_AWAITING_CONTRACT,
                "write_capability": "disabled",
            },
            "provider_extensions": {key: value for key, value in record.items() if key not in known},
        }
