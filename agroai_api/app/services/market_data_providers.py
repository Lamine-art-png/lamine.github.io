"""Provider-neutral market-data contracts for AGRO-AI Market Intelligence.

Adapters may emit a governed observation only when they actually retrieved and
validated it from their upstream.  No customer payload or fallback code can
self-assign LIVE authority.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

SOURCE_STATES = {"LIVE", "DELAYED", "DEMO", "STALE", "UNAVAILABLE", "NOT_CONFIGURED", "MANUAL"}
_ECB_DAILY_XML = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_USDA_MARS_BASE = "https://marsapi.ams.usda.gov/services/v1.2/reports"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _normalize_key(value: str) -> str:
    return "_".join(str(value or "").strip().lower().replace("-", " ").split())


def _parse_datetime(value: Any, *, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if text:
        normalized = text.replace("Z", "+00:00")
        for parser in (
            lambda: datetime.fromisoformat(normalized),
            lambda: datetime.strptime(text, "%m/%d/%Y"),
            lambda: datetime.strptime(text, "%Y-%m-%d"),
            lambda: datetime.strptime(text, "%m/%d/%Y %H:%M:%S"),
        ):
            try:
                parsed = parser()
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return fallback or _utc_now()


def _http_text(url: str, *, headers: dict[str, str] | None = None, timeout: float = 8.0) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AGRO-AI-Market-Intelligence/1.0", **(headers or {})},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed trusted upstreams only
        if int(getattr(response, "status", 200)) >= 400:
            raise RuntimeError(f"upstream returned HTTP {response.status}")
        return response.read().decode("utf-8")


def _http_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 8.0) -> dict[str, Any]:
    payload = json.loads(_http_text(url, headers=headers, timeout=timeout))
    if not isinstance(payload, dict):
        raise ValueError("market-data upstream returned a non-object JSON payload")
    return payload


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
    source_currency: str | None = None
    reporting_currency: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MarketDataProvider(ABC):
    """Contract for governed market-data integrations."""

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


class ECBReferenceFXProvider(MarketDataProvider):
    """Daily ECB reference FX adapter.

    ECB publishes currencies as units per EUR.  We convert those rates to the
    Market Intelligence convention: reporting-currency units per one unit of
    source currency.  ECB explicitly describes these as reference rates for
    information purposes, so observations are DELAYED rather than LIVE.
    """

    provider_id = "fx_reference"

    def __init__(self, fetch_text: Callable[..., str] | None = None) -> None:
        self._fetch_text = fetch_text or _http_text

    async def status(self) -> dict[str, Any]:
        return {
            "status": "DELAYED",
            "source_name": "European Central Bank euro foreign exchange reference rates",
            "configured": True,
            "coverage": "daily_reference",
            "quote_convention": "reporting_currency_per_source_currency",
        }

    def _parse(self, xml_text: str) -> tuple[datetime, dict[str, Decimal]]:
        root = ET.fromstring(xml_text)
        rates: dict[str, Decimal] = {"EUR": Decimal("1")}
        observed: datetime | None = None
        for element in root.iter():
            date_text = element.attrib.get("time")
            if date_text and observed is None:
                parsed_date = datetime.strptime(date_text, "%Y-%m-%d").date()
                observed = datetime.combine(parsed_date, dt_time(16, 0), tzinfo=timezone.utc)
            currency = str(element.attrib.get("currency") or "").upper()
            rate = _decimal(element.attrib.get("rate"))
            if currency and rate is not None and rate > 0:
                rates[currency] = rate
        if observed is None or len(rates) < 2:
            raise ValueError("ECB reference-rate payload is incomplete")
        return observed, rates

    async def observations(self, request: MarketDataRequest) -> list[ProviderObservation]:
        source = str(request.source_currency or request.currency or "").strip().upper()
        reporting = str(request.reporting_currency or "").strip().upper()
        if not source or not reporting or source == reporting:
            return []
        xml_text = await asyncio.to_thread(self._fetch_text, _ECB_DAILY_XML, timeout=8.0)
        observed_at, rates = self._parse(xml_text)
        if source not in rates or reporting not in rates:
            return []
        # Both rates are quoted as currency units per EUR.
        value = (rates[reporting] / rates[source]).quantize(Decimal("0.0000000001"))
        retrieved_at = _utc_now()
        age_minutes = max(Decimal("0"), Decimal(str((retrieved_at - observed_at).total_seconds() / 60)))
        pair = f"{source}{reporting}"
        return [ProviderObservation(
            evidence_id=f"ecb-fx-{pair}-{observed_at.date().isoformat()}",
            observation_type="fx_rate",
            provider=self.provider_id,
            source_name="ECB euro foreign exchange reference rates",
            source_status="DELAYED",
            value=value,
            unit=f"{reporting}/{source}",
            currency=reporting,
            observed_at=observed_at,
            retrieved_at=retrieved_at,
            delay_minutes=age_minutes.quantize(Decimal("0.01")),
            quality={"grade": "reference", "provider_quality": "high"},
            licensing={
                "display_allowed": True,
                "attribution_required": True,
                "usage_note": "Reference rate for information purposes; not a transaction execution rate.",
            },
            metadata={
                "upstream_request_verified": True,
                "source_url": _ECB_DAILY_XML,
                "freshness_max_age_minutes": 2160,
                "quote_convention": "reporting_currency_per_source_currency",
                "base_currency": "EUR",
            },
        )]


_USDA_REGION_REPORTS: dict[str, str] = {
    "california": "3146",
    "illinois": "3192",
    "iowa": "2850",
    "mississippi": "2928",
    "missouri": "2932",
    "ohio": "2851",
    "oregon": "3148",
    "pacific northwest": "3148",
    "washington": "3148",
}
_USDA_COMMODITY_ALIASES: dict[str, tuple[str, ...]] = {
    "corn": ("corn", "yellow corn"),
    "maize": ("corn", "maize", "yellow corn"),
    "soybean": ("soybean", "soybeans"),
    "soybeans": ("soybean", "soybeans"),
    "wheat": ("wheat",),
    "sorghum": ("sorghum", "milo"),
    "barley": ("barley",),
    "oats": ("oats",),
}


class USDAMyMarketNewsProvider(MarketDataProvider):
    """USDA AMS MyMarketNews/MARS cash-market adapter.

    The adapter supports explicit report slugs in position metadata and a small
    set of well-known state grain reports.  It intentionally refuses to invent
    a national cash price for regions/report structures that do not match.
    """

    provider_id = "usda_mymarketnews"

    def __init__(self, api_key: str, fetch_json: Callable[..., dict[str, Any]] | None = None) -> None:
        self.api_key = str(api_key or "").strip()
        self._fetch_json = fetch_json or _http_json

    async def status(self) -> dict[str, Any]:
        if not self.api_key:
            return {
                "status": "NOT_CONFIGURED",
                "source_name": "USDA MyMarketNews",
                "configuration_hint": "Set USDA_MMN_API_KEY from a MyMarketNews account.",
            }
        return {
            "status": "DELAYED",
            "source_name": "USDA AMS MyMarketNews / MARS",
            "configured": True,
            "coverage": "configured_report_and_supported_us_grain_regions",
        }

    def _slug(self, request: MarketDataRequest) -> str | None:
        explicit = str((request.metadata or {}).get("usda_mmn_slug") or "").strip()
        if explicit:
            return explicit
        region = _normalize_key(request.region or "").replace("_", " ")
        return _USDA_REGION_REPORTS.get(region)

    @staticmethod
    def _rows(value: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if isinstance(value, dict):
            rows.append(value)
            for nested in value.values():
                rows.extend(USDAMyMarketNewsProvider._rows(nested))
        elif isinstance(value, list):
            for nested in value:
                rows.extend(USDAMyMarketNewsProvider._rows(nested))
        return rows

    @staticmethod
    def _row_lookup(row: dict[str, Any]) -> dict[str, Any]:
        return {_normalize_key(key): value for key, value in row.items()}

    def _commodity_matches(self, row: dict[str, Any], request: MarketDataRequest) -> bool:
        lookup = self._row_lookup(row)
        text = " ".join(str(lookup.get(key) or "") for key in (
            "commodity", "commodity_name", "commodity_desc", "commodity_description", "class", "item",
        )).lower()
        aliases = _USDA_COMMODITY_ALIASES.get(_normalize_key(request.commodity), (request.commodity.lower(),))
        if not text.strip():
            return bool((request.metadata or {}).get("usda_allow_unlabelled_rows"))
        return any(alias.lower() in text for alias in aliases)

    @staticmethod
    def _price(row: dict[str, Any]) -> Decimal | None:
        lookup = USDAMyMarketNewsProvider._row_lookup(row)
        for key in (
            "weighted_average", "weighted_avg", "simple_average", "simple_avg", "average_price",
            "avg_price", "price_average", "price_avg", "cash_price", "bid_price", "price",
        ):
            value = _decimal(lookup.get(key))
            if value is not None and value >= 0:
                return value
        low = next((_decimal(lookup.get(key)) for key in ("price_low", "low_price", "min_price") if _decimal(lookup.get(key)) is not None), None)
        high = next((_decimal(lookup.get(key)) for key in ("price_high", "high_price", "max_price") if _decimal(lookup.get(key)) is not None), None)
        if low is not None and high is not None and low >= 0 and high >= 0:
            return (low + high) / Decimal("2")
        return None

    @staticmethod
    def _unit(row: dict[str, Any], metadata: dict[str, Any]) -> str | None:
        lookup = USDAMyMarketNewsProvider._row_lookup(row)
        for key in ("price_unit", "price_unit_desc", "unit_of_measure", "uom", "unit"):
            value = str(lookup.get(key) or "").strip()
            if value:
                return value
        fallback = str(metadata.get("usda_price_unit") or "").strip()
        return fallback or None

    @staticmethod
    def _observed_at(row: dict[str, Any]) -> datetime:
        lookup = USDAMyMarketNewsProvider._row_lookup(row)
        for key in (
            "report_begin_date", "report_date", "published_date", "publication_date", "date", "report_end_date",
        ):
            if lookup.get(key):
                return _parse_datetime(lookup[key])
        return _utc_now()

    async def observations(self, request: MarketDataRequest) -> list[ProviderObservation]:
        if not self.api_key or str(request.country_code or "").upper() != "US":
            return []
        slug = self._slug(request)
        if not slug:
            return []
        auth = base64.b64encode(f"{self.api_key}:".encode("utf-8")).decode("ascii")
        url = f"{_USDA_MARS_BASE}/{urllib.parse.quote(slug)}?allSections=true"
        payload = await asyncio.to_thread(
            self._fetch_json,
            url,
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
            timeout=8.0,
        )
        retrieved_at = _utc_now()
        metadata = request.metadata or {}
        observations: list[ProviderObservation] = []
        seen: set[tuple[str, str, str]] = set()
        for index, row in enumerate(self._rows(payload)):
            if not self._commodity_matches(row, request):
                continue
            price = self._price(row)
            if price is None:
                continue
            unit = self._unit(row, metadata)
            observed_at = self._observed_at(row)
            key = (str(price), unit or "", observed_at.date().isoformat())
            if key in seen:
                continue
            seen.add(key)
            age_minutes = max(Decimal("0"), Decimal(str((retrieved_at - observed_at).total_seconds() / 60)))
            evidence = f"usda-mmn-{slug}-{_normalize_key(request.commodity)}-{observed_at.date().isoformat()}-{index}"
            observations.append(ProviderObservation(
                evidence_id=evidence,
                observation_type="cash_price",
                provider=self.provider_id,
                source_name=f"USDA AMS MyMarketNews report {slug}",
                source_status="DELAYED",
                value=price,
                unit=unit,
                currency="USD",
                observed_at=observed_at,
                retrieved_at=retrieved_at,
                delay_minutes=age_minutes.quantize(Decimal("0.01")),
                quality={"grade": "government_report", "provider_quality": "high"},
                licensing={"display_allowed": True, "attribution_required": True},
                metadata={
                    "upstream_request_verified": True,
                    "source_url": url,
                    "report_slug": slug,
                    "freshness_max_age_minutes": int(metadata.get("usda_freshness_max_age_minutes") or 2880),
                },
            ))
            if len(observations) >= 12:
                break
        return observations


class ResilientMarketDataProvider(MarketDataProvider):
    """Bounded timeout/retry/cache/circuit-breaker reliability wrapper."""

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
                rows = await asyncio.wait_for(self.provider.observations(request), timeout=self.timeout_seconds)
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
registry.register(ResilientMarketDataProvider(
    ECBReferenceFXProvider(), timeout_seconds=8.0, max_attempts=2, cache_ttl_seconds=6 * 60 * 60,
))
_usda_key = os.getenv("USDA_MMN_API_KEY", "").strip()
if _usda_key:
    registry.register(ResilientMarketDataProvider(
        USDAMyMarketNewsProvider(_usda_key), timeout_seconds=10.0, max_attempts=2, cache_ttl_seconds=30 * 60,
    ))
else:
    registry.register(NotConfiguredMarketDataProvider(
        "usda_mymarketnews",
        source_name="USDA MyMarketNews",
        configuration_hint="Set USDA_MMN_API_KEY from a free USDA MyMarketNews account to enable automated U.S. cash-market observations.",
    ))
