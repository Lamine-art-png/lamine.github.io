"""Provider-neutral market-data contracts for AGRO-AI Market Intelligence.

Exchange, government, physical-market, FX and logistics feeds must implement
this boundary. No adapter is allowed to imply LIVE unless it actually retrieved
the observation from its configured upstream and can attach provenance.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

SOURCE_STATES = {"LIVE", "DELAYED", "DEMO", "STALE", "UNAVAILABLE", "NOT_CONFIGURED"}


@dataclass(frozen=True)
class ProviderObservation:
    evidence_id: str
    observation_type: str
    provider: str
    source_name: str
    source_status: str
    value: Decimal | None
    unit: str | None
    currency: str | None
    observed_at: datetime
    retrieved_at: datetime
    delay_minutes: Decimal | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    licensing: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        state = self.source_status.upper()
        if state not in SOURCE_STATES:
            raise ValueError(f"Unsupported market-data source state: {state}")
        object.__setattr__(self, "source_status", state)
        if state == "LIVE" and not self.metadata.get("upstream_request_verified"):
            raise ValueError("LIVE market observations require verified upstream retrieval metadata")


@dataclass(frozen=True)
class MarketDataRequest:
    commodity: str
    country_code: str
    region: str | None = None
    currency: str | None = None
    market_structure: str | None = None
    as_of: datetime | None = None


class MarketDataProvider(ABC):
    """Contract for licensed/configured market data integrations."""

    provider_id: str

    @abstractmethod
    async def status(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def observations(self, request: MarketDataRequest) -> list[ProviderObservation]:
        raise NotImplementedError


class MarketDataRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, MarketDataProvider] = {}

    def register(self, provider: MarketDataProvider) -> None:
        key = str(provider.provider_id or "").strip().lower()
        if not key:
            raise ValueError("provider_id is required")
        self._providers[key] = provider

    def get(self, provider_id: str) -> MarketDataProvider | None:
        return self._providers.get(str(provider_id or "").strip().lower())

    def ids(self) -> list[str]:
        return sorted(self._providers)

    async def status(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, provider in self._providers.items():
            try:
                result[key] = await provider.status()
            except Exception as exc:
                result[key] = {"status": "UNAVAILABLE", "error": exc.__class__.__name__}
        return result


registry = MarketDataRegistry()
