from __future__ import annotations

from app.provider_adapters.base import ProviderAdapter
from app.provider_adapters.earthdaily import EarthDailyReadinessAdapter
from app.provider_adapters.valley_irrigation import ValleyIrrigationReadinessAdapter


_REGISTRY: dict[str, ProviderAdapter] = {
    "earthdaily": EarthDailyReadinessAdapter(),
    "valley_irrigation": ValleyIrrigationReadinessAdapter(),
}


def provider_ids() -> list[str]:
    return sorted(_REGISTRY)


def get_provider_adapter(provider_id: str) -> ProviderAdapter:
    try:
        return _REGISTRY[provider_id]
    except KeyError as exc:
        raise ValueError(f"unknown provider adapter: {provider_id}") from exc


def provider_catalog() -> list[dict]:
    result = []
    for adapter in _REGISTRY.values():
        meta = adapter.metadata()
        result.append(
            {
                "provider_id": meta.provider_id,
                "display_name": meta.display_name,
                "readiness": meta.readiness,
                "contract_required": meta.contract_required,
                "capabilities": [
                    {
                        "name": capability.name,
                        "status": capability.status,
                        "implemented": capability.implemented,
                        "write_capability": capability.write_capability,
                        "diagnostics": capability.diagnostics,
                    }
                    for capability in meta.capabilities
                ],
                "notes": list(meta.notes),
            }
        )
    return sorted(result, key=lambda item: item["provider_id"])
