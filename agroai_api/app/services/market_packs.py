"""Market Packs: the market structure appropriate for a country + commodity.

The commercial engine is market-independent. A Market Pack only decides which
evidence sources, units and conventions apply to a commercial position, e.g.
Brazil soybean (physical producer price + official BRL FX + optional licensed
B3 benchmark) versus California almonds (physical/contract pricing, no futures
dependency at all).

Packs never fabricate evidence. Each evidence slot names a provider adapter;
whether that adapter is configured, licensed and fresh is decided at runtime
by the shared market-data plane and reported truthfully.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.market_normalization import (
    brazil_state_code,
    canonical_commodity,
    commodity_family,
    country_default_currency,
)

PACKS_VERSION = "market-packs-2026.10.1"

# Evidence roles a slot can play in a commercial position.
ROLE_PHYSICAL = "physical_price"      # local cash / producer / port price
ROLE_BENCHMARK = "benchmark_price"    # exchange or reference benchmark (optional)
ROLE_FX = "fx_rate"                   # reporting-currency conversion
ROLE_REFERENCE = "reference_statistic"  # official production/yield/supply context

EU_MEMBER_STATES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT",
    "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}
CFA_COUNTRIES = {"SN", "CI", "ML", "BF", "NE", "TG", "BJ", "GW", "CM", "GA", "CG", "TD", "CF", "GQ"}


@dataclass(frozen=True)
class EvidenceSlot:
    role: str
    provider_id: str
    description: str
    required: bool = False
    # Selector parameters the data plane passes to the provider (built per position).
    selector: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketPack:
    pack_id: str
    name: str
    countries: frozenset[str]
    commodities: frozenset[str]           # canonical commodity ids; empty = family match
    families: frozenset[str]
    market_structure: str                 # physical | hybrid | futures
    default_unit: str
    futures_role: str                     # none | optional_licensed
    evidence: tuple[EvidenceSlot, ...]
    notes: str

    def matches(self, country: str, commodity: str | None, family: str | None) -> int:
        """Specificity score; 0 = no match."""
        if self.countries and country not in self.countries:
            return 0
        if self.commodities:
            return 3 if commodity in self.commodities else 0
        if self.families:
            return 2 if family in self.families else 0
        return 1


def _fx_slots(country: str) -> tuple[EvidenceSlot, ...]:
    slots = [EvidenceSlot(ROLE_FX, "fx_reference", "ECB daily euro reference rates (cross rates)")]
    if country == "BR":
        slots.insert(0, EvidenceSlot(ROLE_FX, "bcb_ptax", "Banco Central do Brasil PTAX official BRL/USD rate"))
    return tuple(slots)


_PACKS: tuple[MarketPack, ...] = (
    MarketPack(
        pack_id="br_grains_oilseeds",
        name="Brazil grains and oilseeds",
        countries=frozenset({"BR"}),
        commodities=frozenset({"soybean", "corn", "wheat", "rice", "beans", "cotton"}),
        families=frozenset(),
        market_structure="hybrid",
        default_unit="saca_60kg",
        futures_role="optional_licensed",
        evidence=(
            EvidenceSlot(ROLE_PHYSICAL, "conab_precos", "CONAB weekly state producer prices (preço recebido pelo produtor)"),
            EvidenceSlot(ROLE_BENCHMARK, "b3_futures", "B3 agricultural futures (licensed market data)"),
            EvidenceSlot(ROLE_BENCHMARK, "cepea_indicators", "CEPEA/ESALQ physical indicators (licensed)"),
            EvidenceSlot(ROLE_BENCHMARK, "cme_futures", "CME/CBOT benchmark futures (licensed market data)"),
            *_fx_slots("BR"),
        ),
        notes="Physical producer price by state is the commercial anchor; exchange benchmarks are optional licensed evidence.",
    ),
    MarketPack(
        pack_id="br_coffee",
        name="Brazil coffee",
        countries=frozenset({"BR"}),
        commodities=frozenset({"coffee"}),
        families=frozenset(),
        market_structure="hybrid",
        default_unit="saca_60kg",
        futures_role="optional_licensed",
        evidence=(
            EvidenceSlot(ROLE_PHYSICAL, "conab_precos", "CONAB weekly state producer prices"),
            EvidenceSlot(ROLE_BENCHMARK, "ice_futures", "ICE coffee futures (licensed market data)"),
            *_fx_slots("BR"),
        ),
        notes="Producer price by state; ICE arabica/robusta benchmarks only under licence.",
    ),
    MarketPack(
        pack_id="us_row_crops",
        name="United States row crops",
        countries=frozenset({"US"}),
        commodities=frozenset({"corn", "soybean", "wheat", "sorghum", "barley", "oats"}),
        families=frozenset(),
        market_structure="hybrid",
        default_unit="bushel",
        futures_role="optional_licensed",
        evidence=(
            EvidenceSlot(ROLE_PHYSICAL, "usda_mymarketnews", "USDA AMS MyMarketNews state/elevator cash prices"),
            EvidenceSlot(ROLE_BENCHMARK, "cme_futures", "CME/CBOT futures for basis context (licensed market data)"),
            EvidenceSlot(ROLE_REFERENCE, "usda_nass", "USDA NASS state yield and production statistics"),
            *_fx_slots("US"),
        ),
        notes="Local cash price and basis drive economics; futures are optional licensed benchmark evidence.",
    ),
    MarketPack(
        pack_id="us_specialty_crops",
        name="United States specialty crops",
        countries=frozenset({"US"}),
        commodities=frozenset(),
        families=frozenset({"tree_nuts", "horticulture", "softs"}),
        market_structure="physical",
        default_unit="pound",
        futures_role="none",
        evidence=(
            EvidenceSlot(ROLE_PHYSICAL, "usda_mymarketnews", "USDA AMS MyMarketNews specialty-crop reports where published"),
            EvidenceSlot(ROLE_REFERENCE, "usda_nass", "USDA NASS production statistics"),
            *_fx_slots("US"),
        ),
        notes="No futures dependency: contracts, handler/processor pricing, inventory and costs are the commercial anchor.",
    ),
    MarketPack(
        pack_id="eu_cereals_oilseeds",
        name="European Union cereals and oilseeds",
        countries=frozenset(EU_MEMBER_STATES),
        commodities=frozenset({"wheat", "durum_wheat", "barley", "corn", "rapeseed", "sunflower", "soybean", "oats", "sorghum"}),
        families=frozenset(),
        market_structure="hybrid",
        default_unit="tonne",
        futures_role="optional_licensed",
        evidence=(
            EvidenceSlot(ROLE_PHYSICAL, "eu_agrifood", "European Commission weekly representative physical prices by market"),
            EvidenceSlot(ROLE_BENCHMARK, "euronext_futures", "Euronext (MATIF) futures (licensed market data)"),
            *_fx_slots("EU"),
        ),
        notes="EC weekly physical prices (EUR/t, delivered port/FOB/ex-farm) are the physical anchor.",
    ),
    MarketPack(
        pack_id="au_grains",
        name="Australia grains and oilseeds",
        countries=frozenset({"AU"}),
        commodities=frozenset({"wheat", "barley", "rapeseed", "sorghum", "oats"}),
        families=frozenset(),
        market_structure="hybrid",
        default_unit="tonne",
        futures_role="optional_licensed",
        evidence=(
            EvidenceSlot(ROLE_PHYSICAL, "au_physical_grain", "Australian physical grain prices (no public machine-readable source configured)"),
            EvidenceSlot(ROLE_BENCHMARK, "asx_futures", "ASX grain futures (licensed market data)"),
            *_fx_slots("AU"),
        ),
        notes="Physical port-zone pricing is the anchor; without a licensed or public feed it is customer-supplied (MANUAL).",
    ),
    MarketPack(
        pack_id="in_mandi",
        name="India agricultural mandi markets",
        countries=frozenset({"IN"}),
        commodities=frozenset(),
        families=frozenset({"grains", "pulses", "oilseeds", "horticulture", "fibre", "softs"}),
        market_structure="physical",
        default_unit="quintal",
        futures_role="none",
        evidence=(
            EvidenceSlot(ROLE_PHYSICAL, "india_agmarknet", "AGMARKNET daily mandi modal prices via data.gov.in"),
            *_fx_slots("IN"),
        ),
        notes="Mandi modal prices (Rs./quintal) by state/district/market; no futures dependency.",
    ),
    MarketPack(
        pack_id="ke_local_markets",
        name="Kenya local physical markets",
        countries=frozenset({"KE"}),
        commodities=frozenset(),
        families=frozenset({"grains", "pulses", "horticulture", "dairy", "softs"}),
        market_structure="physical",
        default_unit="bag_90kg",
        futures_role="none",
        evidence=(
            EvidenceSlot(ROLE_PHYSICAL, "kenya_kamis", "Kenya Agricultural Market Information System (no machine-readable API configured)"),
            EvidenceSlot(ROLE_FX, "kenya_cbk_fx", "Central Bank of Kenya indicative rates (no machine-readable API configured)"),
        ),
        notes="Local wholesale market prices in KES per 90 kg bag; KES FX needs a configured source or a customer-supplied rate.",
    ),
    MarketPack(
        pack_id="waemu_local_markets",
        name="West African (CFA franc) local markets",
        countries=frozenset(CFA_COUNTRIES),
        commodities=frozenset(),
        families=frozenset({"grains", "horticulture", "oilseeds", "pulses", "softs"}),
        market_structure="physical",
        default_unit="kg",
        futures_role="none",
        evidence=(
            EvidenceSlot(ROLE_PHYSICAL, "local_market_manual", "Customer-supplied local market and contract prices"),
            EvidenceSlot(ROLE_FX, "fx_reference", "XOF/XAF fixed EUR parity (655.957) with ECB cross rates"),
        ),
        notes="Physical/contract pricing; CFA franc converts exactly through its fixed EUR parity.",
    ),
    MarketPack(
        pack_id="global_livestock_dairy",
        name="Livestock and dairy",
        countries=frozenset(),
        commodities=frozenset(),
        families=frozenset({"livestock", "dairy"}),
        market_structure="physical",
        default_unit="kg",
        futures_role="optional_licensed",
        evidence=(
            EvidenceSlot(ROLE_PHYSICAL, "local_market_manual", "Customer-supplied processor/buyer prices"),
            EvidenceSlot(ROLE_BENCHMARK, "cme_futures", "CME livestock/dairy futures where relevant (licensed)"),
            EvidenceSlot(ROLE_FX, "fx_reference", "ECB daily euro reference rates"),
        ),
        notes="Processor and buyer contract pricing; benchmark futures only under licence and only where meaningful.",
    ),
    MarketPack(
        pack_id="global_physical",
        name="Physical market (any country)",
        countries=frozenset(),
        commodities=frozenset(),
        families=frozenset(),
        market_structure="physical",
        default_unit="tonne",
        futures_role="none",
        evidence=(
            EvidenceSlot(ROLE_PHYSICAL, "local_market_manual", "Customer-supplied local market and contract prices"),
            EvidenceSlot(ROLE_FX, "fx_reference", "ECB daily euro reference rates"),
        ),
        notes="Universal fallback: contracts, costs, inventory and customer-verified local prices; no futures assumed.",
    ),
)

PACKS_BY_ID: dict[str, MarketPack] = {pack.pack_id: pack for pack in _PACKS}


def resolve_pack(country_code: str | None, commodity: str | None) -> MarketPack:
    """Most specific pack for a country + commodity; always returns a pack."""
    country = str(country_code or "").upper()
    canonical = canonical_commodity(commodity)
    family = commodity_family(commodity)
    best = max(_PACKS, key=lambda pack: pack.matches(country, canonical, family))
    return best if best.matches(country, canonical, family) else PACKS_BY_ID["global_physical"]


def position_selectors(pack: MarketPack, *, country_code: str, commodity: str, region: str | None, metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Provider selector parameters for one position, keyed by provider id.

    Selectors are inferred from customer-language inputs (country, crop,
    region). Customers never supply provider report identifiers; an advanced
    administrator override may still be stored under metadata["source_overrides"].
    """
    country = str(country_code or "").upper()
    canonical = canonical_commodity(commodity) or str(commodity or "").lower()
    overrides = metadata.get("source_overrides") if isinstance(metadata.get("source_overrides"), dict) else {}
    selectors: dict[str, dict[str, Any]] = {}
    for slot in pack.evidence:
        if slot.provider_id == "conab_precos":
            uf = brazil_state_code(region)
            if uf:
                selectors["conab_precos"] = {"commodity": canonical, "uf": uf}
        elif slot.provider_id == "eu_agrifood":
            selectors["eu_agrifood"] = {"commodity": canonical, "member_state": country, "market": (region or None)}
        elif slot.provider_id == "usda_mymarketnews":
            selectors["usda_mymarketnews"] = {"commodity": canonical, "region": region}
        elif slot.provider_id == "india_agmarknet":
            selectors["india_agmarknet"] = {"commodity": canonical, "state": region}
        elif slot.provider_id == "usda_nass":
            selectors["usda_nass"] = {"commodity": canonical, "state": region}
    for provider_id, override in overrides.items():
        if isinstance(override, dict):
            selectors[str(provider_id)] = {**selectors.get(str(provider_id), {}), **override}
    # Legacy positions carried a raw USDA report id in metadata; keep honouring it.
    if metadata.get("usda_mmn_slug") and "usda_mymarketnews" in selectors:
        selectors["usda_mymarketnews"]["report_slug"] = str(metadata["usda_mmn_slug"])
    return selectors


def infer_onboarding(*, crop: str, country_code: str, region: str | None = None, reporting_currency: str | None = None) -> dict[str, Any]:
    """Turn customer-language answers into a position template.

    "Soybeans in Mato Grosso, Brazil" -> commodity soybean, BRL, saca 60 kg,
    hybrid structure, CONAB + PTAX evidence plan. Never requires a report id.
    """
    country = str(country_code or "").upper()
    canonical = canonical_commodity(crop)
    pack = resolve_pack(country, crop)
    local_currency = country_default_currency(country)
    # Stable codes only: the portal renders each in the viewer's locale.
    warnings: list[str] = []
    if canonical is None:
        warnings.append("crop_not_recognised")
    if local_currency is None:
        warnings.append("currency_not_inferred")
    if pack.pack_id.startswith("br_") and region and brazil_state_code(region) is None:
        warnings.append("state_not_recognised")
    return {
        "packs_version": PACKS_VERSION,
        "pack_id": pack.pack_id,
        "commodity": canonical or str(crop or "").strip().lower(),
        "commodity_recognised": canonical is not None,
        "country_code": country,
        "region": region,
        "local_currency": local_currency,
        "reporting_currency": (reporting_currency or local_currency or "USD").upper(),
        "quantity_unit": pack.default_unit,
        "market_structure": pack.market_structure,
        "futures_role": pack.futures_role,
        "evidence_plan": [{"role": slot.role, "provider_id": slot.provider_id} for slot in pack.evidence],
        "warnings": warnings,
    }


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "pack_id": pack.pack_id,
            # English reference documentation for API users; the portal
            # renders pack and provider names from pack_id/provider_id.
            "name": pack.name,
            "countries": sorted(pack.countries) or ["*"],
            "commodities": sorted(pack.commodities),
            "families": sorted(pack.families),
            "market_structure": pack.market_structure,
            "default_unit": pack.default_unit,
            "futures_role": pack.futures_role,
            "evidence": [
                {"role": slot.role, "provider_id": slot.provider_id, "description": slot.description}
                for slot in pack.evidence
            ],
            "notes": pack.notes,
        }
        for pack in _PACKS
    ]
