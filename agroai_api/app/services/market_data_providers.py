"""Provider-neutral market-data contracts for AGRO-AI Market Intelligence.

Exchange, government, physical-market, FX and logistics feeds must implement
this boundary. No adapter is allowed to imply LIVE unless it actually retrieved
the observation from its configured upstream and can attach provenance.
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

SOURCE_STATES = {"LIVE", "DELAYED", "DEMO", "STALE", "UNAVAILABLE", "NOT_CONFIGURED", "MANUAL"}


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


class NotConfiguredMarketDataProvider(MarketDataProvider):
    """Truthful catalog entry for an integration that has no configured access."""

    def __init__(self, provider_id: str, *, source_name: str, configuration_hint: str) -> None:
        self.provider_id = provider_id
        self.source_name = source_name
        self.configuration_hint = configuration_hint

    async def status(self) -> dict[str, Any]:
        return {
            "status": "NOT_CONFIGURED",
            "source_name": self.source_name,
            "configuration_hint": self.configuration_hint,
        }

    async def observations(self, request: MarketDataRequest) -> list[ProviderObservation]:
        return []


class ResilientMarketDataProvider(MarketDataProvider):
    """Reliability boundary for licensed provider adapters.

    The wrapped adapter remains responsible for authentication, response
    validation, provenance and licensing. This boundary adds bounded retries,
    timeout, short-lived caching and a fail-closed circuit breaker without ever
    manufacturing observations.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        *,
        timeout_seconds: float = 8.0,
        max_attempts: int = 2,
        cache_ttl_seconds: float = 300.0,
        circuit_failure_threshold: int = 3,
        circuit_reset_seconds: float = 60.0,
    ) -> None:
        self.provider = provider
        self.provider_id = provider.provider_id
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.max_attempts = max(1, max_attempts)
        self.cache_ttl_seconds = max(0.0, cache_ttl_seconds)
        self.circuit_failure_threshold = max(1, circuit_failure_threshold)
        self.circuit_reset_seconds = max(1.0, circuit_reset_seconds)
        self._cache: dict[str, tuple[float, list[ProviderObservation]]] = {}
        self._failure_count = 0
        self._circuit_opened_at: float | None = None

    async def status(self) -> dict[str, Any]:
        status = await self.provider.status()
        return {
            **status,
            "runtime": {
                "timeout_seconds": self.timeout_seconds,
                "max_attempts": self.max_attempts,
                "cache_ttl_seconds": self.cache_ttl_seconds,
                "circuit": "open" if self._circuit_is_open() else "closed",
            },
        }

    def _circuit_is_open(self) -> bool:
        if self._circuit_opened_at is None:
            return False
        if time.monotonic() - self._circuit_opened_at >= self.circuit_reset_seconds:
            self._circuit_opened_at = None
            self._failure_count = 0
            return False
        return True

    async def observations(self, request: MarketDataRequest) -> list[ProviderObservation]:
        key = repr(request)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and now < cached[0]:
            return list(cached[1])
        if self._circuit_is_open():
            raise RuntimeError(f"market data provider circuit open: {self.provider_id}")

        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                rows = await asyncio.wait_for(
                    self.provider.observations(request),
                    timeout=self.timeout_seconds,
                )
                self._failure_count = 0
                self._circuit_opened_at = None
                self._cache[key] = (time.monotonic() + self.cache_ttl_seconds, list(rows))
                return list(rows)
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.max_attempts:
                    await asyncio.sleep(min(0.25 * (2 ** attempt), 1.0))

        self._failure_count += 1
        if self._failure_count >= self.circuit_failure_threshold:
            self._circuit_opened_at = time.monotonic()
        raise RuntimeError(f"market data provider unavailable: {self.provider_id}") from last_error


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
registry.register(NotConfiguredMarketDataProvider(
    "usda_mymarketnews",
    source_name="USDA MyMarketNews",
    configuration_hint="Configure licensed upstream access before requesting observations.",
))
registry.register(NotConfiguredMarketDataProvider(
    "fx_reference",
    source_name="FX reference provider",
    configuration_hint="Select and configure an approved FX upstream before requesting observations.",
))
