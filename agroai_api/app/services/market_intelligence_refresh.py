"""Tenant position refresh from the shared market-data plane.

Positions no longer call providers directly. A refresh:

1. optionally runs due *fast* provider demands for this position (slow
   publications such as CONAB are refreshed only by the scheduled cycle);
2. resolves the governed physical price and FX from persisted shared evidence;
3. promotes values into the position only when policy allows it:
   - a customer-entered price (``price_policy: manual``) is never overwritten;
   - a customer-supplied FX rate is never cleared when no governed source
     exists (e.g. KES); only automation-set FX is cleared when unverifiable;
4. writes a tenant-scoped audit observation for every promoted value that
   points at the shared series/point, so the position's provenance and data
   health are reconstructable.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.market_intelligence import MarketContractPosition, MarketObservation, MarketPosition
from app.services import market_data_plane as plane
from app.services.market_data_adapters import ADAPTERS
from app.services.market_packs import position_selectors, resolve_pack

AUTOMATED_FX_PREFIX = "data_plane:"


def _metadata(row: Any) -> dict[str, Any]:
    value = getattr(row, "metadata_json", None) or {}
    return dict(value) if isinstance(value, dict) else {}


def _norm(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _quantity_unit_from_price_unit(value: str | None) -> str | None:
    """Legacy helper kept for the USDA unit contract."""
    text = _norm(value)
    if not text:
        return None
    if "bushel" in text or text in {"bu", "usd/bu", "$/bu"}:
        return "bushel"
    if "pound" in text or text in {"lb", "lbs", "usd/lb", "$/lb"}:
        return "pound"
    if "kilogram" in text or text in {"kg", "usd/kg", "$/kg"}:
        return "kg"
    if "metric ton" in text or "metric tonne" in text or text in {"t", "tonne", "usd/t", "$/t"}:
        return "tonne"
    return None


def _scoped_evidence_id(position_id: str, upstream_evidence_id: str) -> str:
    """Tenant audit rows are position-scoped while keeping the upstream identity."""
    return f"{position_id}:{upstream_evidence_id}"


def price_policy(position: MarketPosition) -> str:
    """Whether automation may set this position's realizable price.

    Explicit policy wins. Without one, an empty price may be filled
    automatically; an existing price is customer-owned unless automation set it.
    """
    metadata = _metadata(position)
    policy = str(metadata.get("price_policy") or "").strip().lower()
    if policy in {"manual", "automatic"}:
        return policy
    if position.current_realizable_price is None:
        return "automatic"
    return "automatic" if str(metadata.get("price_source") or "").startswith(AUTOMATED_FX_PREFIX) else "manual"


def _audit(db: Session, position: MarketPosition, evidence: dict[str, Any], *, normalized_value: Decimal | None = None, trace: dict[str, Any] | None = None) -> None:
    upstream_id = f"plane:{evidence.get('point_id') or evidence.get('provider')}:{evidence.get('role')}"
    evidence_id = _scoped_evidence_id(position.id, upstream_id)
    row = (
        db.query(MarketObservation)
        .filter(MarketObservation.organization_id == position.organization_id, MarketObservation.evidence_id == evidence_id)
        .first()
    )
    observed = evidence.get("observed_at")
    values = {
        "position_id": position.id,
        "observation_type": evidence.get("role") or evidence.get("observation_type") or "market_evidence",
        "provider": evidence.get("provider") or "unknown",
        "source_name": evidence.get("source_name") or "",
        "source_status": evidence.get("state") or "DELAYED",
        "value": Decimal(str(evidence["value"])) if evidence.get("value") is not None else None,
        "unit": evidence.get("unit"),
        "currency": evidence.get("currency"),
        "observed_at": datetime.fromisoformat(str(observed).rstrip("Z")) if observed else datetime.utcnow(),
        "retrieved_at": datetime.fromisoformat(str(evidence["retrieved_at"]).rstrip("Z")) if evidence.get("retrieved_at") else datetime.utcnow(),
        "quality_json": {"freshness_max_age_minutes": evidence.get("freshness_max_age_minutes"), "grade": "governed_shared_evidence"},
        "licensing_json": evidence.get("licensing") or {},
        "metadata_json": {
            "upstream_evidence_id": upstream_id,
            "series_id": evidence.get("series_id"),
            "point_id": evidence.get("point_id"),
            "series_key": evidence.get("series_key"),
            "market_name": evidence.get("market_name"),
            "price_basis": evidence.get("price_basis"),
            "freshness_max_age_minutes": evidence.get("freshness_max_age_minutes"),
            "normalized_value": str(normalized_value) if normalized_value is not None else None,
            "normalization_trace": trace or {},
            "automated": True,
        },
    }
    if row is None:
        db.add(MarketObservation(organization_id=position.organization_id, evidence_id=evidence_id, **values))
    else:
        for key, value in values.items():
            setattr(row, key, value)


async def ensure_position_evidence(db: Session, position: MarketPosition, *, trigger: str = "on_demand") -> dict[str, Any]:
    """Run due fast-provider demands for one position (never slow publications)."""
    metadata = _metadata(position)
    pack = resolve_pack(position.country_code, position.commodity)
    selectors = position_selectors(pack, country_code=position.country_code, commodity=position.commodity, region=position.region, metadata=metadata)
    demands: dict[str, list[dict[str, Any]]] = {pid: [sel] for pid, sel in selectors.items()}
    currencies = {str(position.reporting_currency or "").upper(), str(position.price_currency or position.local_currency or "").upper()}
    if len(currencies - {""}) > 1:
        demands.setdefault("fx_reference", [{}])
        if {"BRL", "USD"}.issubset(currencies):
            demands.setdefault("bcb_ptax", [{}])
    results: dict[str, Any] = {}
    for provider_id, provider_selectors in demands.items():
        adapter = ADAPTERS.get(provider_id)
        if adapter is None:
            continue
        if provider_id in plane.SCHEDULED_ONLY:
            results[provider_id] = {"status": "scheduled_only"}
            continue
        if not adapter.configured():
            results[provider_id] = {"status": adapter.status().lower()}
            continue
        demand_key = "|".join(sorted({adapter.demand_key(s) for s in provider_selectors}))[:400]
        if not plane.provider_due(db, adapter, demand_key):
            results[provider_id] = {"status": "fresh_enough"}
            continue
        results[provider_id] = await plane.ingest(db, provider_id, provider_selectors, trigger=trigger, adapter=adapter)
    return results


def _apply_fx(db: Session, position: MarketPosition, target: Any, source_currency: str, cache: dict[str, plane.FxResolution]) -> tuple[str, plane.FxResolution | None]:
    """Set FX on a position or contract; returns (outcome, resolution)."""
    reporting = str(position.reporting_currency or "").upper()
    source = str(source_currency or reporting).upper()
    metadata = _metadata(target)
    fx_source = str(metadata.get("fx_source") or "")
    if source == reporting:
        if target.fx_rate_to_reporting is not None:
            target.fx_rate_to_reporting = None
            metadata.pop("fx_source", None)
            target.metadata_json = metadata
            return "cleared_same_currency", None
        return "same_currency", None
    if source not in cache:
        cache[source] = plane.resolve_fx(db, source, reporting)
    resolution = cache[source]
    if resolution.rate is not None:
        target.fx_rate_to_reporting = resolution.rate
        metadata["fx_source"] = f"{AUTOMATED_FX_PREFIX}{resolution.method}"
        metadata["fx_state"] = resolution.state
        target.metadata_json = metadata
        return "updated", resolution
    if fx_source.startswith(AUTOMATED_FX_PREFIX) and target.fx_rate_to_reporting is not None:
        # An automation-set rate that can no longer be verified is removed
        # rather than silently aged.
        target.fx_rate_to_reporting = None
        metadata["fx_state"] = "UNAVAILABLE"
        target.metadata_json = metadata
        return "cleared_unverifiable", resolution
    return ("kept_customer_rate" if target.fx_rate_to_reporting is not None else "missing"), resolution


async def refresh_position_market_data(
    db: Session,
    position: MarketPosition,
    *,
    contracts: list[MarketContractPosition] | None = None,
    ingest_missing: bool = True,
    trigger: str = "on_demand",
) -> dict[str, Any]:
    organization_id = str(position.organization_id)
    contracts = contracts if contracts is not None else (
        db.query(MarketContractPosition)
        .filter(MarketContractPosition.organization_id == organization_id, MarketContractPosition.position_id == position.id)
        .all()
    )
    provider_results = await ensure_position_evidence(db, position, trigger=trigger) if ingest_missing else {}
    position_updates: list[str] = []

    # Physical price.
    policy = price_policy(position)
    price = plane.resolve_physical_price(db, position)
    price_outcome = "unavailable"
    if price.price is not None:
        for item in price.evidence:
            _audit(db, position, item, normalized_value=price.price, trace=price.trace)
        if policy == "manual":
            price_outcome = "kept_customer_price"
        else:
            position.current_realizable_price = price.price
            position.price_currency = price.currency
            metadata = _metadata(position)
            metadata.update({
                "price_policy": "automatic",
                "price_source": f"{AUTOMATED_FX_PREFIX}{price.method}",
                "price_state": price.state,
                "price_resolved_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            })
            position.metadata_json = metadata
            position_updates.extend(["current_realizable_price", "price_currency"])
            price_outcome = "promoted"
    elif policy == "automatic" and str(_metadata(position).get("price_source") or "").startswith(AUTOMATED_FX_PREFIX):
        # Previously automated price can no longer be verified: do not keep
        # presenting it as current.
        metadata = _metadata(position)
        metadata["price_state"] = "UNAVAILABLE"
        position.metadata_json = metadata
        position.current_realizable_price = None
        position_updates.append("current_realizable_price")
        price_outcome = "cleared_unverifiable"

    # FX for the price and every contract currency.
    fx_cache: dict[str, plane.FxResolution] = {}
    price_currency = str(position.price_currency or position.local_currency or position.reporting_currency).upper()
    fx_outcome, fx_resolution = _apply_fx(db, position, position, price_currency, fx_cache)
    if fx_outcome in {"updated", "cleared_unverifiable", "cleared_same_currency"}:
        position_updates.append("fx_rate_to_reporting")
    contract_updates = 0
    for contract in contracts:
        outcome, _ = _apply_fx(db, position, contract, str(contract.currency or ""), fx_cache)
        if outcome in {"updated", "cleared_unverifiable", "cleared_same_currency"}:
            contract_updates += 1
    for resolution in fx_cache.values():
        for item in resolution.components:
            if item.get("point_id"):
                _audit(db, position, item)

    position.updated_at = datetime.utcnow()
    db.commit()
    return {
        "position_id": position.id,
        "refreshed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "pack_id": resolve_pack(position.country_code, position.commodity).pack_id,
        "price": {
            "outcome": price_outcome,
            "policy": policy,
            "state": price.state,
            "method": price.method,
            "reason": price.reason,
        },
        "fx": {
            "outcome": fx_outcome,
            "state": fx_resolution.state if fx_resolution else "NOT_REQUIRED",
            "method": fx_resolution.method if fx_resolution else None,
        },
        "position_updates": sorted(set(position_updates)),
        "contract_fx_updates": contract_updates,
        "providers": provider_results,
    }


async def refresh_organization_market_data(db: Session, organization_id: str) -> dict[str, Any]:
    positions = (
        db.query(MarketPosition)
        .filter(MarketPosition.organization_id == organization_id, MarketPosition.status == "active")
        .order_by(MarketPosition.updated_at.asc())
        .all()
    )
    results = [await refresh_position_market_data(db, position) for position in positions]
    return {"organization_id": organization_id, "position_count": len(positions), "results": results}
