from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


READINESS_AWAITING_CONTRACT = "awaiting_partner_contract"


@dataclass(frozen=True)
class ProviderCapability:
    name: str
    status: str
    implemented: bool = False
    write_capability: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderMetadata:
    provider_id: str
    display_name: str
    readiness: str
    contract_required: bool
    capabilities: tuple[ProviderCapability, ...]
    notes: tuple[str, ...] = ()


class ProviderAdapter(Protocol):
    provider_id: str

    def metadata(self) -> ProviderMetadata:
        ...

    def configuration_schema(self) -> dict[str, Any]:
        ...

    def credential_schema(self) -> dict[str, Any]:
        ...

    def validate_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        ...

    def discover_resources(self, credentials: dict[str, Any] | None = None) -> dict[str, Any]:
        ...

    def normalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        ...
