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
from app.services.market_intelligence import ACTIVE_CONTRACT_STATUSES
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


def _active_contracts(db: Session, position: MarketPosition) -> list[MarketContractPosition]:
    return plane.active_contracts_by_position(db, [position]).get(position.id, [])


async def ensure_position_evidence(
    db: Session,
    position: MarketPosition,
    *,
    contracts: list[MarketContractPosition] | None = None,
    trigger: str = "on_demand",
) -> dict[str, Any]:
    """Run due fast-provider demands for one position (never slow publications).

    FX demand covers the price, cost and every exposure-carrying contract
    currency, exactly as the scheduled demand set does.
    """
    metadata = _metadata(position)
    pack = resolve_pack(position.country_code, position.commodity)
    selectors = position_selectors(pack, country_code=position.country_code, commodity=position.commodity, region=position.region, metadata=metadata)
    demands: dict[str, list[dict[str, Any]]] = {
        pid: [sel] for pid, sel in selectors.items() if pid not in ADAPTERS or ADAPTERS[pid].covers(sel)
    }
    contracts = contracts if contracts is not None else _active_contracts(db, position)
    foreign = plane.position_fx_currencies(position, contracts)
    for provider_id, selector in plane.fx_demands(str(position.reporting_currency or ""), foreign).items():
        demands.setdefault(provider_id, [selector])
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
        demand_key, _ = plane.demand_identity(adapter, provider_selectors)
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
    # No governed rate: a customer-entered rate stays (MANUAL); otherwise the
    # conversion is explicitly UNAVAILABLE so economics and data health say so.
    metadata["fx_state"] = "MANUAL" if target.fx_rate_to_reporting is not None else "UNAVAILABLE"
    target.metadata_json = metadata
    return ("kept_customer_rate" if target.fx_rate_to_reporting is not None else "missing"), resolution


def _apply_cost_fx(db: Session, position: MarketPosition, cache: dict[str, plane.FxResolution]) -> dict[str, Any] | None:
    """Governed FX for costs recorded in a third currency (not price, not reporting).

    Costs in the price currency reuse the position FX; this covers e.g. a
    USD-reporting operation selling in USD while paying costs in BRL.
    """
    metadata = _metadata(position)
    reporting = str(position.reporting_currency or "").upper()
    cost_currency = str(metadata.get("cost_currency") or reporting).upper()
    price_currency = str(position.price_currency or position.local_currency or reporting).upper()
    if cost_currency in {reporting, price_currency}:
        changed = any(key in metadata for key in ("cost_fx_rate", "cost_fx_state"))
        if changed and str(metadata.get("cost_fx_source") or "").startswith(AUTOMATED_FX_PREFIX):
            for key in ("cost_fx_rate", "cost_fx_state", "cost_fx_source"):
                metadata.pop(key, None)
            position.metadata_json = metadata
        return None
    if cost_currency not in cache:
        cache[cost_currency] = plane.resolve_fx(db, cost_currency, reporting)
    resolution = cache[cost_currency]
    customer_rate = metadata.get("cost_fx_rate") if not str(metadata.get("cost_fx_source") or "").startswith(AUTOMATED_FX_PREFIX) else None
    if resolution.rate is not None:
        metadata.update({"cost_fx_rate": str(resolution.rate), "cost_fx_state": resolution.state, "cost_fx_source": f"{AUTOMATED_FX_PREFIX}{resolution.method}"})
        outcome = "updated"
    elif customer_rate is not None:
        metadata["cost_fx_state"] = "MANUAL"
        outcome = "kept_customer_rate"
    else:
        metadata.pop("cost_fx_rate", None)
        metadata.update({"cost_fx_state": "UNAVAILABLE", "cost_fx_source": f"{AUTOMATED_FX_PREFIX}unavailable"})
        outcome = "missing"
    position.metadata_json = metadata
    return {"currency": cost_currency, "outcome": outcome, "state": metadata.get("cost_fx_state")}


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
    provider_results = await ensure_position_evidence(db, position, contracts=contracts, trigger=trigger) if ingest_missing else {}
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
                # Derived use is allowed (the plane filtered that); display may not be.
                "price_display_allowed": all((item.get("licensing") or {}).get("display_allowed", True) is not False for item in price.evidence),
                "price_resolved_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                # The governed series actually pricing the position (risk history reads it).
                "price_series_id": (price.evidence[0] or {}).get("series_id") if price.evidence else None,
            })
            position.metadata_json = metadata
            position_updates.extend(["current_realizable_price", "price_currency"])
            price_outcome = "promoted"
    elif policy == "automatic" and price.state == "SELECTION_REQUIRED":
        # Several commercially different quotes: the customer chooses which one
        # applies; a previously automated price is not kept as if it were current.
        metadata = _metadata(position)
        metadata["price_state"] = "SELECTION_REQUIRED"
        metadata.pop("price_series_id", None)
        if str(metadata.get("price_source") or "").startswith(AUTOMATED_FX_PREFIX) and position.current_realizable_price is not None:
            position.current_realizable_price = None
            position_updates.append("current_realizable_price")
        position.metadata_json = metadata
        price_outcome = "selection_required"
    elif policy == "automatic" and str(_metadata(position).get("price_source") or "").startswith(AUTOMATED_FX_PREFIX):
        # Previously automated price can no longer be verified: do not keep
        # presenting it as current.
        metadata = _metadata(position)
        metadata["price_state"] = "UNAVAILABLE"
        metadata.pop("price_series_id", None)
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
    contract_fx: list[dict[str, Any]] = []
    for contract in contracts:
        if str(contract.status or "active").lower() not in ACTIVE_CONTRACT_STATUSES:
            continue
        outcome, resolution = _apply_fx(db, position, contract, str(contract.currency or ""), fx_cache)
        if outcome in {"updated", "cleared_unverifiable", "cleared_same_currency"}:
            contract_updates += 1
        if outcome not in {"same_currency", "cleared_same_currency"}:
            contract_fx.append({
                "contract_id": contract.id,
                "contract_code": contract.contract_code,
                "currency": str(contract.currency or "").upper(),
                "outcome": outcome,
                "state": _metadata(contract).get("fx_state"),
                "method": resolution.method if resolution else None,
            })
    cost_fx = _apply_cost_fx(db, position, fx_cache)
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
            "candidates": price.trace.get("candidates") if price.state == "SELECTION_REQUIRED" else None,
        },
        "fx": {
            "outcome": fx_outcome,
            "state": fx_resolution.state if fx_resolution else "NOT_REQUIRED",
            "method": fx_resolution.method if fx_resolution else None,
        },
        "position_updates": sorted(set(position_updates)),
        "contract_fx_updates": contract_updates,
        "contract_fx": contract_fx,
        "cost_fx": cost_fx,
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
