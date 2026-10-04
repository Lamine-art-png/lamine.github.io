"""Series-level provider adapters for the shared AGRO-AI market-data plane.

Each adapter retrieves *canonical upstream series* (e.g. "CONAB soybean,
Mato Grosso, price received by producers") rather than answering one tenant's
question. The data plane persists each point once and every tenant position
reads the same governed observation.

Adapter contract:
- never fabricate a value; unparseable or ambiguous rows are skipped;
- every point carries provider, source, native identity, unit, currency,
  observed time, retrieval time, freshness policy and licensing metadata;
- no adapter emits LIVE: these are published reference/statistical series and
  are DELAYED by construction;
- adapters without credentials or licences report NOT_CONFIGURED truthfully.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable, Iterator

from app.services.market_normalization import (
    canonical_commodity,
    canonical_unit,
    country_default_currency,
    fold,
    parse_decimal,
    parse_price_unit,
)

USER_AGENT = "AGRO-AI-Commercial-Intelligence/2.0 (+https://agroai-pilot.com)"
MINUTES_PER_DAY = 1440


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SeriesDescriptor:
    provider: str
    series_key: str
    source_name: str
    observation_type: str
    native_id: str | None = None
    commodity: str | None = None
    country_code: str | None = None
    region: str | None = None
    market_name: str | None = None
    price_basis: str | None = None
    unit: str | None = None
    currency: str | None = None
    base_currency: str | None = None
    frequency: str = "daily"
    freshness_max_age_minutes: int = 4320
    last_known_max_age_minutes: int = 10080
    licensing: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SeriesPoint:
    descriptor: SeriesDescriptor
    observed_at: datetime
    value: Decimal
    retrieved_at: datetime
    source_status: str = "DELAYED"
    raw_value: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    upstream_ref: str | None = None
    quality: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_status not in {"DELAYED", "MANUAL"}:
            raise ValueError("series adapters may only emit DELAYED published evidence")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.value.is_finite():
            raise ValueError("series point value must be finite")


def licensing(
    *,
    license_id: str,
    attribution: str,
    license_url: str | None = None,
    display_allowed: bool = True,
    derived_values_allowed: bool = True,
    storage_allowed: bool = True,
    redistribution_allowed: bool = True,
    attribution_required: bool = True,
    retention_days: int | None = None,
) -> dict[str, Any]:
    return {
        "license_id": license_id,
        "license_url": license_url,
        "attribution": attribution,
        "attribution_required": attribution_required,
        "display_allowed": display_allowed,
        "derived_values_allowed": derived_values_allowed,
        "storage_allowed": storage_allowed,
        "redistribution_allowed": redistribution_allowed,
        "retention_days": retention_days,
    }


LICENSE_REQUIRED = licensing(
    license_id="commercial_market_data_license_required",
    attribution="",
    display_allowed=False,
    derived_values_allowed=False,
    storage_allowed=False,
    redistribution_allowed=False,
    attribution_required=False,
)


def http_get_text(url: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0, encoding: str = "utf-8") -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})}, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed official upstreams
        if int(getattr(response, "status", 200)) >= 400:
            raise RuntimeError(f"upstream returned HTTP {response.status}")
        return response.read().decode(encoding)


def http_iter_lines(url: str, *, timeout: float = 900.0, encoding: str = "latin-1") -> Iterator[str]:
    """Stream a large text publication line by line (bounded memory)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - fixed official upstreams
        if int(getattr(response, "status", 200)) >= 400:
            raise RuntimeError(f"upstream returned HTTP {response.status}")
        for raw in response:
            yield raw.decode(encoding, errors="replace")


class SeriesProvider:
    """Base class for data-plane adapters."""

    provider_id: str = ""
    name: str = ""
    access: str = "public_no_key"  # public_no_key | free_key_required | commercial_license_required | no_machine_readable_source | customer_input
    credential_env: str | None = None
    refresh_interval_minutes: int = 360
    request_timeout_seconds: float = 30.0
    validation: str = "fixture"
    coverage: dict[str, Any] = {}
    license: dict[str, Any] = {}

    def configured(self) -> bool:
        return self.access == "public_no_key" or bool(self.credential_env and os.getenv(self.credential_env, "").strip())

    def demand_key(self, selector: dict[str, Any]) -> str:
        return self.provider_id + ":" + json.dumps(selector, sort_keys=True, separators=(",", ":"), default=str)

    async def collect(self, selectors: list[dict[str, Any]]) -> list[SeriesPoint]:
        raise NotImplementedError

    def status(self) -> str:
        if self.access in {"commercial_license_required", "no_machine_readable_source"}:
            return "NOT_CONFIGURED"
        if self.access == "customer_input":
            return "MANUAL"
        return "DELAYED" if self.configured() else "NOT_CONFIGURED"

    def catalog(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "name": self.name,
            "status": self.status(),
            "access": self.access,
            "credential_env": self.credential_env,
            "configured": self.configured() if self.access not in {"commercial_license_required", "no_machine_readable_source"} else False,
            "refresh_interval_minutes": self.refresh_interval_minutes,
            "validation": self.validation,
            "coverage": self.coverage,
            "licensing": self.license,
        }


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------

ECB_HIST_90D = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
# Currencies in the ECB euro reference-rate basket (RUB suspended since 2022;
# BGN ended with Bulgaria's euro adoption on 2026-01-01).
ECB_REFERENCE_CURRENCIES = frozenset({
    "USD", "JPY", "CZK", "DKK", "GBP", "HUF", "PLN", "RON", "SEK", "CHF", "ISK", "NOK", "TRY", "AUD", "BRL", "CAD",
    "CNY", "HKD", "IDR", "ILS", "INR", "KRW", "MXN", "MYR", "NZD", "PHP", "SGD", "THB", "ZAR",
})
ECB_LICENSE = licensing(
    license_id="ECB-statistics-reuse",
    license_url="https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html",
    attribution="Source: European Central Bank euro foreign exchange reference rates",
)


class ECBReferenceRatesSeries(SeriesProvider):
    provider_id = "fx_reference"
    name = "European Central Bank euro foreign exchange reference rates"
    refresh_interval_minutes = 360
    validation = "live_verified_2026-10-03"
    coverage = {"countries": ["*"], "observation_types": ["fx_rate"], "currencies": "ECB reference basket (~30 currencies) + CFA franc fixed parity"}
    license = ECB_LICENSE

    def __init__(self, fetch_text: Callable[..., str] | None = None) -> None:
        self._fetch_text = fetch_text or http_get_text

    def demand_key(self, selector: dict[str, Any]) -> str:
        return "fx_reference:ecb-hist-90d"

    async def collect(self, selectors: list[dict[str, Any]]) -> list[SeriesPoint]:
        xml_text = await asyncio.to_thread(self._fetch_text, ECB_HIST_90D, timeout=20.0)
        root = ET.fromstring(xml_text)
        retrieved = _utc_now()
        points: list[SeriesPoint] = []
        for day in root.iter():
            date_text = day.attrib.get("time")
            if not date_text:
                continue
            observed = datetime.combine(datetime.strptime(date_text, "%Y-%m-%d").date(), dt_time(14, 0), tzinfo=timezone.utc)
            for rate in day:
                currency = str(rate.attrib.get("currency") or "").upper()
                value = parse_decimal(rate.attrib.get("rate"), decimal_comma=False)
                if len(currency) != 3 or value is None or value <= 0:
                    continue
                descriptor = SeriesDescriptor(
                    provider=self.provider_id,
                    series_key=f"fx_reference:EUR:{currency}",
                    source_name=self.name,
                    observation_type="fx_rate",
                    native_id=f"ECB EXR D.{currency}.EUR.SP00.A",
                    unit=f"{currency}/EUR",
                    currency=currency,
                    base_currency="EUR",
                    frequency="daily_business",
                    # ECB publishes on TARGET business days only; 72h covers weekends.
                    freshness_max_age_minutes=3 * MINUTES_PER_DAY,
                    last_known_max_age_minutes=7 * MINUTES_PER_DAY,
                    licensing=self.license,
                    metadata={"source_url": ECB_HIST_90D, "usage_note": "Reference rate for information purposes; not a transaction rate."},
                )
                points.append(SeriesPoint(
                    descriptor=descriptor, observed_at=observed, value=value, retrieved_at=retrieved,
                    raw_value=rate.attrib.get("rate"), upstream_ref=f"{ECB_HIST_90D}#{date_text}",
                    quality={"grade": "central_bank_reference"},
                ))
        if not points:
            raise ValueError("ECB reference-rate publication contained no rates")
        return points


BCB_PTAX = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
)
BCB_LICENSE = licensing(
    license_id="BCB-dados-abertos",
    license_url="https://dadosabertos.bcb.gov.br/",
    attribution="Fonte: Banco Central do Brasil — PTAX",
)


class BCBPtaxSeries(SeriesProvider):
    provider_id = "bcb_ptax"
    name = "Banco Central do Brasil PTAX (official BRL/USD)"
    refresh_interval_minutes = 240
    validation = "live_verified_2026-10-03"
    coverage = {"countries": ["BR"], "observation_types": ["fx_rate"], "pairs": ["USD/BRL"]}
    license = BCB_LICENSE

    def __init__(self, fetch_text: Callable[..., str] | None = None) -> None:
        self._fetch_text = fetch_text or http_get_text

    def demand_key(self, selector: dict[str, Any]) -> str:
        return "bcb_ptax:USD:BRL"

    async def collect(self, selectors: list[dict[str, Any]]) -> list[SeriesPoint]:
        today = _utc_now().date()
        start = today - timedelta(days=150)
        query = urllib.parse.urlencode({
            "@dataInicial": f"'{start.strftime('%m-%d-%Y')}'",
            "@dataFinalCotacao": f"'{today.strftime('%m-%d-%Y')}'",
            "$format": "json",
        }, safe="@'$")
        url = f"{BCB_PTAX}?{query}"
        payload = json.loads(await asyncio.to_thread(self._fetch_text, url, timeout=20.0))
        rows = payload.get("value") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("PTAX payload has no value array")
        retrieved = _utc_now()
        descriptor = SeriesDescriptor(
            provider=self.provider_id,
            series_key="bcb_ptax:USD:BRL",
            source_name=self.name,
            observation_type="fx_rate",
            native_id="PTAX CotacaoDolar venda",
            country_code="BR",
            unit="BRL/USD",
            currency="BRL",
            base_currency="USD",
            frequency="daily_business",
            freshness_max_age_minutes=3 * MINUTES_PER_DAY,
            last_known_max_age_minutes=7 * MINUTES_PER_DAY,
            licensing=self.license,
            metadata={"source_url": BCB_PTAX, "rate": "selling (venda)", "timezone": "America/Sao_Paulo"},
        )
        points: list[SeriesPoint] = []
        brasilia = timezone(timedelta(hours=-3))
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = parse_decimal(row.get("cotacaoVenda"), decimal_comma=False)
            stamp = str(row.get("dataHoraCotacao") or "")
            if value is None or value <= 0 or not stamp:
                continue
            try:
                local = datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=brasilia)
            except ValueError:
                continue
            points.append(SeriesPoint(
                descriptor=descriptor, observed_at=local.astimezone(timezone.utc), value=value,
                retrieved_at=retrieved, raw_value=str(row.get("cotacaoVenda")), upstream_ref=url,
                quality={"grade": "central_bank_official", "buy_rate": str(row.get("cotacaoCompra"))},
            ))
        if not points:
            raise ValueError("PTAX returned no quotations for the requested window")
        return points


# ---------------------------------------------------------------------------
# Physical markets
# ---------------------------------------------------------------------------

EU_AGRIFOOD_BASE = "https://api.tech.ec.europa.eu/agrifood/api"
EU_LICENSE = licensing(
    license_id="EC-2011-833-EU (CC BY 4.0)",
    license_url="https://agridata.ec.europa.eu/extensions/DataPortal/legal_notice.html",
    attribution="Source: European Commission, Agri-food data portal",
)
# Canonical commodity -> (dataset, upstream product selector)
_EU_PRODUCTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "wheat": ("cereal", ("BLTPAN", "BLTFOUR")),
    "durum_wheat": ("cereal", ("DUR",)),
    "barley": ("cereal", ("ORGFOUR", "ORGBRAS")),
    "corn": ("cereal", ("MAI",)),
    "oats": ("cereal", ("AVO",)),
    "sorghum": ("cereal", ("SOR",)),
    "rapeseed": ("oilseeds", ("Rapeseed",)),
    "sunflower": ("oilseeds", ("Sunflower seed",)),
    "soybean": ("oilseeds", ("Soya beans",)),
}


class EUAgriFoodPricesSeries(SeriesProvider):
    provider_id = "eu_agrifood"
    name = "European Commission agri-food weekly representative prices"
    refresh_interval_minutes = 720
    request_timeout_seconds = 60.0
    validation = "live_verified_2026-10-03"
    coverage = {
        "countries": "EU member states",
        "commodities": sorted(_EU_PRODUCTS),
        "observation_types": ["physical_price"],
        "price_basis": "per market and marketing stage (e.g. delivered port, FOB, ex-farm)",
    }
    license = EU_LICENSE

    def __init__(self, fetch_text: Callable[..., str] | None = None) -> None:
        self._fetch_text = fetch_text or http_get_text

    def demand_key(self, selector: dict[str, Any]) -> str:
        return f"eu_agrifood:{selector.get('member_state')}:{selector.get('commodity')}"

    def _url(self, dataset: str, member_state: str, product: str, begin: str) -> str:
        if dataset == "cereal":
            query = {"memberStateCodes": member_state, "productCodes": product, "beginDate": begin}
        else:
            query = {"memberStateCodes": member_state, "products": product, "beginDate": begin}
        return f"{EU_AGRIFOOD_BASE}/{dataset}/prices?{urllib.parse.urlencode(query)}"

    @staticmethod
    def _date(value: Any) -> datetime | None:
        try:
            return datetime.strptime(str(value), "%d/%m/%Y").replace(hour=12, tzinfo=timezone.utc)
        except ValueError:
            return None

    async def collect(self, selectors: list[dict[str, Any]]) -> list[SeriesPoint]:
        begin = (_utc_now() - timedelta(weeks=30)).strftime("%d/%m/%Y")
        retrieved = _utc_now()
        points: list[SeriesPoint] = []
        seen_requests: set[tuple[str, str, str]] = set()
        for selector in selectors:
            commodity = canonical_commodity(selector.get("commodity"))
            member_state = str(selector.get("member_state") or "").upper()
            if commodity not in _EU_PRODUCTS or len(member_state) != 2:
                continue
            dataset, products = _EU_PRODUCTS[commodity]
            for product in products:
                key = (dataset, member_state, product)
                if key in seen_requests:
                    continue
                seen_requests.add(key)
                url = self._url(dataset, member_state, product, begin)
                try:
                    rows = json.loads(await asyncio.to_thread(self._fetch_text, url, timeout=self.request_timeout_seconds))
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        continue  # the portal answers 404 when a product has no prices for the member state
                    raise
                if not isinstance(rows, list):
                    raise ValueError("EU agri-food payload is not a list")
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    raw_price = str(row.get("price") or "")
                    end = self._date(row.get("endDate"))
                    start = self._date(row.get("beginDate"))
                    market = str(row.get("marketName") or row.get("market") or "").strip()
                    stage = str(row.get("stageName") or row.get("marketStage") or "").strip()
                    product_label = str(row.get("productName") or row.get("product") or product).strip()
                    national = country_default_currency(member_state)
                    currency = "EUR" if "€" in raw_price else national
                    unit = parse_price_unit(str(row.get("unit") or ""), default_currency=currency)
                    value = parse_decimal(raw_price)
                    if end is None or value is None or value <= 0 or unit is None or not market or not currency:
                        continue
                    if unit.currency and unit.currency != currency:
                        continue  # contradicting currency labels: never guess
                    descriptor = SeriesDescriptor(
                        provider=self.provider_id,
                        series_key=f"eu_agrifood:{member_state}:{product}:{fold(market)}:{fold(stage)[:80]}",
                        source_name=self.name,
                        observation_type="physical_price",
                        native_id=f"{dataset}/{product}/{market}",
                        commodity=commodity,
                        country_code=member_state,
                        region=market,
                        market_name=market,
                        price_basis=stage or None,
                        unit=unit.quantity_unit,
                        currency=currency,
                        frequency="weekly",
                        freshness_max_age_minutes=14 * MINUTES_PER_DAY,
                        last_known_max_age_minutes=30 * MINUTES_PER_DAY,
                        licensing=self.license,
                        metadata={"product_label": product_label, "dataset": dataset, "source_url": url.split("?")[0]},
                    )
                    points.append(SeriesPoint(
                        descriptor=descriptor, observed_at=end, value=value, retrieved_at=retrieved,
                        raw_value=raw_price[:120], period_start=start, period_end=end, upstream_ref=url,
                        quality={"grade": "official_weekly_representative", "week": row.get("weekNumber")},
                    ))
        return points


CONAB_WEEKLY_UF = "https://portaldeinformacoes.conab.gov.br/downloads/arquivos/PrecosSemanalUF.txt"
CONAB_LICENSE = licensing(
    license_id="CONAB-dados-abertos",
    license_url="https://portaldeinformacoes.conab.gov.br/",
    attribution="Fonte: Conab — Companhia Nacional de Abastecimento",
)
# Canonical commodity -> (CONAB produto, accepted classifications or None = all)
_CONAB_PRODUCTS: dict[str, tuple[str, frozenset[str] | None]] = {
    "soybean": ("soja", frozenset({"em graos"})),
    "corn": ("milho", frozenset({"em graos"})),
    "wheat": ("trigo", None),
    "rice": ("arroz", None),
    "coffee": ("cafe", None),
    "beans": ("feijao", None),
    "cotton": ("algodao em caroco", None),
}


class CONABWeeklyPricesSeries(SeriesProvider):
    provider_id = "conab_precos"
    name = "CONAB weekly state agricultural prices"
    refresh_interval_minutes = 720
    request_timeout_seconds = 900.0  # the official portal serves ~12 MB slowly
    validation = "live_verified_2026-10-03"
    coverage = {
        "countries": ["BR"],
        "commodities": sorted(_CONAB_PRODUCTS),
        "observation_types": ["physical_price"],
        "price_basis": "price received by producers (preço recebido pelo produtor), weekly, by state",
        "unit": "BRL/kg",
    }
    license = CONAB_LICENSE

    def __init__(self, iter_lines: Callable[..., Iterable[str]] | None = None) -> None:
        self._iter_lines = iter_lines or http_iter_lines

    def demand_key(self, selector: dict[str, Any]) -> str:
        return f"conab_precos:{selector.get('uf')}:{selector.get('commodity')}"

    @staticmethod
    def _week_end(text: str) -> tuple[datetime | None, datetime | None]:
        parts = [part.strip() for part in str(text or "").split(" - ")]
        if len(parts) != 2:
            return None, None
        try:
            start = datetime.strptime(parts[0], "%d-%m-%Y").replace(hour=12, tzinfo=timezone.utc)
            end = datetime.strptime(parts[1], "%d-%m-%Y").replace(hour=12, tzinfo=timezone.utc)
        except ValueError:
            return None, None
        return start, end

    def _parse(self, lines: Iterable[str], wanted: set[tuple[str, str]], retrieved: datetime) -> list[SeriesPoint]:
        cutoff = retrieved - timedelta(days=400)
        iterator = iter(lines)
        header_line = next(iterator, "")
        header = [fold(item).replace(" ", "_") for item in header_line.rstrip("\r\n").split(";")]
        required = {"produto", "classificao_produto", "uf", "data_inicial_final_semana", "dsc_nivel_comercializacao", "valor_produto_kg"}
        if not required.issubset(header):
            raise ValueError("CONAB publication header changed; refusing to guess column meaning")
        index = {name: header.index(name) for name in required}
        wanted_products = {product for product, _uf in wanted}
        points: list[SeriesPoint] = []
        for line in iterator:
            fields = line.rstrip("\r\n").split(";")
            if len(fields) != len(header):
                continue
            produto = fold(fields[index["produto"]])
            canonical = next(
                (c for c, (name, _classes) in _CONAB_PRODUCTS.items() if c in wanted_products and produto == name),
                None,
            )
            if canonical is None:
                continue
            uf = fields[index["uf"]].strip().upper()
            if (canonical, uf) not in wanted:
                continue
            level = fold(fields[index["dsc_nivel_comercializacao"]])
            if not (level.startswith("preco recebido")):
                continue  # retail, wholesale and prices *paid* by producers are different evidence
            classification = fold(fields[index["classificao_produto"]])
            accepted = _CONAB_PRODUCTS[canonical][1]
            if accepted is not None and classification not in accepted:
                continue
            start, end = self._week_end(fields[index["data_inicial_final_semana"]])
            value = parse_decimal(fields[index["valor_produto_kg"]], decimal_comma=True)
            if end is None or end < cutoff or value is None or value <= 0:
                continue
            descriptor = SeriesDescriptor(
                provider=self.provider_id,
                series_key=f"conab_precos:{canonical}:{classification}:{uf}:producer_received",
                source_name=self.name,
                observation_type="physical_price",
                native_id=f"{fields[index['produto']].strip()} / {fields[index['classificao_produto']].strip()} / {uf}",
                commodity=canonical,
                country_code="BR",
                region=uf,
                market_name=f"{uf} state average",
                price_basis="producer_received",
                unit="kg",
                currency="BRL",
                frequency="weekly",
                freshness_max_age_minutes=14 * MINUTES_PER_DAY,
                last_known_max_age_minutes=30 * MINUTES_PER_DAY,
                licensing=self.license,
                metadata={"source_url": CONAB_WEEKLY_UF, "classification": fields[index["classificao_produto"]].strip()},
            )
            points.append(SeriesPoint(
                descriptor=descriptor, observed_at=end, value=value, retrieved_at=retrieved,
                raw_value=fields[index["valor_produto_kg"]].strip(), period_start=start, period_end=end,
                upstream_ref=CONAB_WEEKLY_UF, quality={"grade": "official_weekly_state_average"},
            ))
        return points

    async def collect(self, selectors: list[dict[str, Any]]) -> list[SeriesPoint]:
        wanted = {
            (canonical_commodity(item.get("commodity")) or "", str(item.get("uf") or "").upper())
            for item in selectors
        }
        wanted = {(c, uf) for c, uf in wanted if c in _CONAB_PRODUCTS and len(uf) == 2}
        if not wanted:
            return []
        retrieved = _utc_now()

        def run() -> list[SeriesPoint]:
            return self._parse(self._iter_lines(CONAB_WEEKLY_UF, timeout=self.request_timeout_seconds), wanted, retrieved)

        return await asyncio.to_thread(run)


USDA_MARS_BASE = "https://marsapi.ams.usda.gov/services/v1.2/reports"
USDA_LICENSE = licensing(
    license_id="US-Government-public-domain",
    license_url="https://www.usda.gov/policies-and-links",
    attribution="Source: USDA Agricultural Marketing Service, MyMarketNews",
    attribution_required=False,
)
_USDA_REGION_REPORTS: dict[str, str] = {
    "california": "3146", "illinois": "3192", "iowa": "2850", "mississippi": "2928",
    "missouri": "2932", "ohio": "2851", "oregon": "3148", "pacific northwest": "3148", "washington": "3148",
}
_USDA_COMMODITY_ALIASES: dict[str, tuple[str, ...]] = {
    "corn": ("corn", "yellow corn"), "soybean": ("soybean", "soybeans"), "wheat": ("wheat",),
    "sorghum": ("sorghum", "milo"), "barley": ("barley",), "oats": ("oats",),
}


# MARS row fields that distinguish separate quotes within one report.
_USDA_QUOTE_DIMENSIONS = (
    "grade", "class", "variety", "quality", "protein", "item_size", "package", "organic",
    "delivery_period", "delivery_point", "current", "trans_mode", "sale_type", "basis_type",
)


class USDAMyMarketNewsSeries(SeriesProvider):
    provider_id = "usda_mymarketnews"
    name = "USDA AMS MyMarketNews / MARS"
    access = "free_key_required"
    credential_env = "USDA_MMN_API_KEY"
    refresh_interval_minutes = 360
    validation = "fixture_and_prior_production_adapter"
    coverage = {"countries": ["US"], "commodities": sorted(_USDA_COMMODITY_ALIASES), "observation_types": ["physical_price"], "regions": sorted(_USDA_REGION_REPORTS)}
    license = USDA_LICENSE

    def __init__(self, fetch_text: Callable[..., str] | None = None, api_key: str | None = None) -> None:
        self._fetch_text = fetch_text or http_get_text
        self._api_key = api_key

    def _key(self) -> str:
        return str(self._api_key if self._api_key is not None else os.getenv("USDA_MMN_API_KEY", "")).strip()

    def configured(self) -> bool:
        return bool(self._key())

    def demand_key(self, selector: dict[str, Any]) -> str:
        return f"usda_mymarketnews:{self._slug(selector)}:{canonical_commodity(selector.get('commodity'))}"

    @staticmethod
    def _slug(selector: dict[str, Any]) -> str | None:
        explicit = str(selector.get("report_slug") or "").strip()
        if explicit:
            return explicit
        return _USDA_REGION_REPORTS.get(fold(selector.get("region")))

    @staticmethod
    def _rows(value: Any) -> Iterator[dict[str, Any]]:
        if isinstance(value, dict):
            yield value
            for nested in value.values():
                yield from USDAMyMarketNewsSeries._rows(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from USDAMyMarketNewsSeries._rows(nested)

    async def collect(self, selectors: list[dict[str, Any]]) -> list[SeriesPoint]:
        key = self._key()
        if not key:
            return []
        auth = base64.b64encode(f"{key}:".encode()).decode("ascii")
        retrieved = _utc_now()
        points: list[SeriesPoint] = []
        fetched: dict[str, Any] = {}
        for selector in selectors:
            slug = self._slug(selector)
            commodity = canonical_commodity(selector.get("commodity"))
            if not slug or commodity not in _USDA_COMMODITY_ALIASES:
                continue
            if slug not in fetched:
                url = f"{USDA_MARS_BASE}/{urllib.parse.quote(slug)}?allSections=true"
                fetched[slug] = json.loads(await asyncio.to_thread(
                    self._fetch_text, url, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"}, timeout=20.0,
                ))
            for row in self._rows(fetched[slug]):
                lookup = {fold(k).replace(" ", "_"): v for k, v in row.items() if not isinstance(v, (dict, list))}
                label = " ".join(str(lookup.get(k) or "") for k in ("commodity", "commodity_name", "commodity_desc", "class", "item")).lower()
                if not any(alias in label for alias in _USDA_COMMODITY_ALIASES[commodity]):
                    continue
                price = next((parse_decimal(lookup.get(k), decimal_comma=False) for k in (
                    "weighted_average", "weighted_avg", "simple_average", "simple_avg", "average_price", "avg_price", "price",
                ) if parse_decimal(lookup.get(k), decimal_comma=False) is not None), None)
                unit_text = next((str(lookup[k]) for k in ("price_unit", "price_unit_desc", "unit_of_measure", "uom", "unit") if lookup.get(k)), "")
                unit = parse_price_unit(unit_text, default_currency="USD")
                date_text = next((lookup[k] for k in ("report_begin_date", "report_date", "published_date", "date") if lookup.get(k)), None)
                if price is None or price < 0 or unit is None or date_text is None:
                    continue
                observed = None
                for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S"):
                    try:
                        observed = datetime.strptime(str(date_text)[:19], fmt).replace(hour=18, tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                if observed is None:
                    continue
                location = str(lookup.get("location") or lookup.get("office_city") or selector.get("region") or "").strip()
                # One report can quote the same commodity, location and date
                # several times (grades, classes, delivery periods, sale types);
                # each quote is its own series, never a "revision" of another.
                qualifiers = {key: str(lookup[key]).strip() for key in _USDA_QUOTE_DIMENSIONS if str(lookup.get(key) or "").strip()}
                qualifier_id = hashlib.sha256(json.dumps(qualifiers, sort_keys=True).encode()).hexdigest()[:12] if qualifiers else "base"
                descriptor = SeriesDescriptor(
                    provider=self.provider_id,
                    # Stable, content-derived identity (independent of row order).
                    series_key=f"usda_mymarketnews:{slug}:{commodity}:{fold(location)}:{unit.quantity_unit}:{qualifier_id}",
                    source_name=f"{self.name} report {slug}",
                    observation_type="physical_price",
                    native_id=f"MARS report {slug}",
                    commodity=commodity,
                    country_code="US",
                    region=selector.get("region"),
                    market_name=location or None,
                    price_basis="cash_bid",
                    unit=unit.quantity_unit,
                    currency="USD",
                    frequency="daily_business",
                    freshness_max_age_minutes=4 * MINUTES_PER_DAY,
                    last_known_max_age_minutes=14 * MINUTES_PER_DAY,
                    licensing=self.license,
                    metadata={"report_slug": slug, "source_url": f"{USDA_MARS_BASE}/{slug}", "quote": qualifiers},
                )
                points.append(SeriesPoint(
                    descriptor=descriptor, observed_at=observed, value=price, retrieved_at=retrieved,
                    raw_value=str(price), upstream_ref=f"{USDA_MARS_BASE}/{slug}", quality={"grade": "government_report"},
                ))
        return points


NASS_QUICKSTATS = "https://quickstats.nass.usda.gov/api/api_GET/"
_NASS_COMMODITIES = {"corn": "CORN", "soybean": "SOYBEANS", "wheat": "WHEAT", "sorghum": "SORGHUM", "barley": "BARLEY",
                     "oats": "OATS", "cotton": "COTTON", "rice": "RICE", "almonds": "ALMONDS"}


class USDANASSQuickStatsSeries(SeriesProvider):
    provider_id = "usda_nass"
    name = "USDA NASS Quick Stats (state yield statistics)"
    access = "free_key_required"
    credential_env = "USDA_NASS_API_KEY"
    refresh_interval_minutes = 7 * MINUTES_PER_DAY
    validation = "fixture_only_requires_key"
    coverage = {"countries": ["US"], "commodities": sorted(_NASS_COMMODITIES), "observation_types": ["reference_statistic"], "statistic": "YIELD, state level, annual"}
    license = licensing(
        license_id="US-Government-public-domain",
        license_url="https://quickstats.nass.usda.gov/api",
        attribution="Source: USDA National Agricultural Statistics Service",
        attribution_required=False,
    )

    def __init__(self, fetch_text: Callable[..., str] | None = None, api_key: str | None = None) -> None:
        self._fetch_text = fetch_text or http_get_text
        self._api_key = api_key

    def _key(self) -> str:
        return str(self._api_key if self._api_key is not None else os.getenv("USDA_NASS_API_KEY", "")).strip()

    def configured(self) -> bool:
        return bool(self._key())

    def demand_key(self, selector: dict[str, Any]) -> str:
        return f"usda_nass:{canonical_commodity(selector.get('commodity'))}:{fold(selector.get('state'))}"

    async def collect(self, selectors: list[dict[str, Any]]) -> list[SeriesPoint]:
        key = self._key()
        if not key:
            return []
        retrieved = _utc_now()
        points: list[SeriesPoint] = []
        for selector in selectors:
            commodity = canonical_commodity(selector.get("commodity"))
            state = fold(selector.get("state")).upper()
            if commodity not in _NASS_COMMODITIES or not state:
                continue
            query = urllib.parse.urlencode({
                "key": key, "commodity_desc": _NASS_COMMODITIES[commodity], "statisticcat_desc": "YIELD",
                "agg_level_desc": "STATE", "state_name": state, "reference_period_desc": "YEAR",
                "year__GE": str(retrieved.year - 10), "format": "JSON",
            })
            payload = json.loads(await asyncio.to_thread(self._fetch_text, f"{NASS_QUICKSTATS}?{query}", timeout=30.0))
            for row in (payload.get("data") or []) if isinstance(payload, dict) else []:
                value = parse_decimal(str(row.get("Value") or "").replace(",", ""), decimal_comma=False)
                year = str(row.get("year") or "")
                unit_text = str(row.get("unit_desc") or "")
                if value is None or not year.isdigit() or "/ ACRE" not in unit_text.upper():
                    continue
                quantity = canonical_unit(unit_text.upper().split("/")[0].strip())
                if quantity is None:
                    continue
                observed = datetime(int(year), 12, 31, 12, tzinfo=timezone.utc)
                descriptor = SeriesDescriptor(
                    provider=self.provider_id,
                    series_key=f"usda_nass:{commodity}:{fold(state)}:yield",
                    source_name=self.name,
                    observation_type="reference_statistic",
                    native_id=str(row.get("short_desc") or ""),
                    commodity=commodity,
                    country_code="US",
                    region=state.title(),
                    unit=f"{quantity}/acre",
                    frequency="annual",
                    freshness_max_age_minutes=550 * MINUTES_PER_DAY,
                    last_known_max_age_minutes=900 * MINUTES_PER_DAY,
                    licensing=self.license,
                    metadata={"statistic": "yield", "source_url": NASS_QUICKSTATS},
                )
                points.append(SeriesPoint(
                    descriptor=descriptor, observed_at=observed, value=value, retrieved_at=retrieved,
                    raw_value=str(row.get("Value"))[:120], upstream_ref=NASS_QUICKSTATS,
                    quality={"grade": "official_statistic", "load_time": row.get("load_time")},
                ))
        return points


AGMARKNET_RESOURCE = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
_AGMARKNET_COMMODITIES = {
    # Producers sell paddy; milled "Rice" is a different product and price level.
    "rice": ("Paddy(Dhan)(Common)",), "wheat": ("Wheat",), "corn": ("Maize",), "soybean": ("Soyabean",),
    "cotton": ("Cotton",), "onions": ("Onion",), "tomatoes": ("Tomato",), "groundnuts": ("Groundnut",),
}


class IndiaAgmarknetSeries(SeriesProvider):
    provider_id = "india_agmarknet"
    name = "AGMARKNET daily mandi prices (data.gov.in)"
    access = "free_key_required"
    credential_env = "DATA_GOV_IN_API_KEY"
    refresh_interval_minutes = 360
    validation = "fixture_only_requires_key"
    coverage = {"countries": ["IN"], "commodities": sorted(_AGMARKNET_COMMODITIES), "observation_types": ["physical_price"], "price_basis": "mandi modal price, Rs./quintal"}
    license = licensing(
        license_id="GODL-India",
        license_url="https://data.gov.in/government-open-data-license-india",
        attribution="Source: AGMARKNET, Directorate of Marketing & Inspection, Government of India (data.gov.in)",
    )

    def __init__(self, fetch_text: Callable[..., str] | None = None, api_key: str | None = None) -> None:
        self._fetch_text = fetch_text or http_get_text
        self._api_key = api_key

    def _key(self) -> str:
        return str(self._api_key if self._api_key is not None else os.getenv("DATA_GOV_IN_API_KEY", "")).strip()

    def configured(self) -> bool:
        return bool(self._key())

    def demand_key(self, selector: dict[str, Any]) -> str:
        return f"india_agmarknet:{fold(selector.get('state'))}:{canonical_commodity(selector.get('commodity'))}"

    async def collect(self, selectors: list[dict[str, Any]]) -> list[SeriesPoint]:
        key = self._key()
        if not key:
            return []
        retrieved = _utc_now()
        points: list[SeriesPoint] = []
        for selector in selectors:
            commodity = canonical_commodity(selector.get("commodity"))
            state = str(selector.get("state") or "").strip()
            if commodity not in _AGMARKNET_COMMODITIES or not state:
                continue
            for upstream_name in _AGMARKNET_COMMODITIES[commodity]:
                query = urllib.parse.urlencode({
                    "api-key": key, "format": "json", "limit": "500",
                    "filters[state]": state, "filters[commodity]": upstream_name,
                })
                payload = json.loads(await asyncio.to_thread(self._fetch_text, f"{AGMARKNET_RESOURCE}?{query}", timeout=30.0))
                for row in (payload.get("records") or []) if isinstance(payload, dict) else []:
                    value = parse_decimal(row.get("modal_price"), decimal_comma=False)
                    try:
                        observed = datetime.strptime(str(row.get("arrival_date")), "%d/%m/%Y").replace(hour=10, tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    market = str(row.get("market") or "").strip()
                    district = str(row.get("district") or "").strip()
                    variety = str(row.get("variety") or "").strip()
                    if value is None or value <= 0 or not market:
                        continue
                    if fold(row.get("commodity")) != fold(upstream_name):
                        continue  # never mix products under one series
                    descriptor = SeriesDescriptor(
                        provider=self.provider_id,
                        series_key=f"india_agmarknet:{fold(state)}:{fold(district)}:{fold(market)}:{fold(upstream_name)}:{fold(variety)}",
                        source_name=self.name,
                        observation_type="physical_price",
                        native_id=f"{upstream_name} / {variety} / {market}",
                        commodity=commodity,
                        country_code="IN",
                        region=state,
                        market_name=f"{market}, {district}",
                        price_basis="mandi_modal",
                        unit="quintal",
                        currency="INR",
                        frequency="daily",
                        freshness_max_age_minutes=4 * MINUTES_PER_DAY,
                        last_known_max_age_minutes=14 * MINUTES_PER_DAY,
                        licensing=self.license,
                        metadata={"variety": variety, "min_price": row.get("min_price"), "max_price": row.get("max_price"), "source_url": AGMARKNET_RESOURCE},
                    )
                    points.append(SeriesPoint(
                        descriptor=descriptor, observed_at=observed, value=value, retrieved_at=retrieved,
                        raw_value=str(row.get("modal_price"))[:120], upstream_ref=AGMARKNET_RESOURCE,
                        quality={"grade": "government_market_reporting"},
                    ))
        return points


# ---------------------------------------------------------------------------
# Truthful boundaries without data access
# ---------------------------------------------------------------------------


class BoundaryProvider(SeriesProvider):
    """A real adapter boundary with no configured data access.

    Licensed exchanges require a commercial agreement and entitlement keys;
    some public bodies publish no machine-readable source. These report
    NOT_CONFIGURED (or MANUAL for customer input) and never return values.
    """

    def __init__(self, provider_id: str, name: str, *, access: str, note: str, coverage: dict[str, Any]) -> None:
        self.provider_id = provider_id
        self.name = name
        self.access = access
        self.note = note
        self.coverage = coverage
        self.license = LICENSE_REQUIRED if access == "commercial_license_required" else {}
        self.validation = "boundary_only"

    def configured(self) -> bool:
        return False

    async def collect(self, selectors: list[dict[str, Any]]) -> list[SeriesPoint]:
        return []

    def catalog(self) -> dict[str, Any]:
        return {**super().catalog(), "configuration_hint": self.note}


def build_adapters() -> dict[str, SeriesProvider]:
    adapters: list[SeriesProvider] = [
        ECBReferenceRatesSeries(),
        BCBPtaxSeries(),
        EUAgriFoodPricesSeries(),
        CONABWeeklyPricesSeries(),
        USDAMyMarketNewsSeries(),
        USDANASSQuickStatsSeries(),
        IndiaAgmarknetSeries(),
        BoundaryProvider("cme_futures", "CME Group / CBOT futures", access="commercial_license_required",
                         note="Requires a CME market-data licence and entitlement feed; delayed display also requires agreement.",
                         coverage={"countries": ["US", "global benchmark"], "observation_types": ["benchmark_price"]}),
        BoundaryProvider("b3_futures", "B3 agricultural futures", access="commercial_license_required",
                         note="Requires a B3 market-data licence (UP2DATA or vendor).", coverage={"countries": ["BR"], "observation_types": ["benchmark_price"]}),
        BoundaryProvider("euronext_futures", "Euronext (MATIF) commodity futures", access="commercial_license_required",
                         note="Requires a Euronext market-data licence.", coverage={"countries": ["EU"], "observation_types": ["benchmark_price"]}),
        BoundaryProvider("asx_futures", "ASX grain futures", access="commercial_license_required",
                         note="Requires an ASX market-data licence.", coverage={"countries": ["AU"], "observation_types": ["benchmark_price"]}),
        BoundaryProvider("ice_futures", "ICE softs futures (coffee, cocoa, sugar)", access="commercial_license_required",
                         note="Requires an ICE market-data licence.", coverage={"countries": ["global benchmark"], "observation_types": ["benchmark_price"]}),
        BoundaryProvider("cepea_indicators", "CEPEA/ESALQ physical price indicators", access="commercial_license_required",
                         note="CEPEA indicators require a licence for commercial reuse and redistribution.", coverage={"countries": ["BR"], "observation_types": ["physical_price"]}),
        BoundaryProvider("au_physical_grain", "Australian physical grain prices", access="no_machine_readable_source",
                         note="No public machine-readable physical grain price feed identified; use customer-verified prices or a licensed vendor.",
                         coverage={"countries": ["AU"], "observation_types": ["physical_price"]}),
        BoundaryProvider("kenya_kamis", "Kenya Agricultural Market Information System (KAMIS)", access="no_machine_readable_source",
                         note="KAMIS publishes web pages without a documented machine-readable API; WFP/HDX Kenya prices end in December 2023.",
                         coverage={"countries": ["KE"], "observation_types": ["physical_price"]}),
        BoundaryProvider("kenya_cbk_fx", "Central Bank of Kenya indicative exchange rates", access="no_machine_readable_source",
                         note="CBK publishes indicative KES rates as web pages only; KES is not in the ECB reference basket.",
                         coverage={"countries": ["KE"], "observation_types": ["fx_rate"]}),
        BoundaryProvider("local_market_manual", "Customer-verified local market and contract prices", access="customer_input",
                         note="Authorized members record verified local prices; always labelled MANUAL with timestamp and author.",
                         coverage={"countries": ["*"], "observation_types": ["physical_price"]}),
    ]
    return {adapter.provider_id: adapter for adapter in adapters}


ADAPTERS: dict[str, SeriesProvider] = build_adapters()
