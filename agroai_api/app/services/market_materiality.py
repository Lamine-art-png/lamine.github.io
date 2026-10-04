"""Materiality Engine for AGRO-AI Commercial Intelligence.

The question is not "did soybeans move 3%?" but "does this matter to THIS
enterprise?". Conceptually:

    market or operational change x tenant exposure x economic sensitivity

Methodology (deterministic, versioned, inspectable):

1. Every evaluation compares the position's current deterministic economics
   with a *reference snapshot* (the latest snapshot at least 20 hours old, i.e.
   "since yesterday"), both computed by the same fixed-precision engine.
2. Commercial impact = |change in projected margin| when margin is complete in
   both snapshots, otherwise |change in exposed revenue|. It is expressed in the
   position's reporting currency and as a ratio of reference projected revenue.
3. Impact is attributed to drivers by sequential substitution (production,
   price, FX, costs, contracts): inputs are switched from reference to current
   one group at a time and each step's margin change is that driver's
   contribution. Contributions sum exactly to the total change.
4. Levels come from configurable thresholds on the impact ratio (defaults:
   MEDIUM >= 2%, HIGH >= 5%, CRITICAL >= 10%) plus qualitative transitions
   (margin turning negative, realizable price falling below break-even,
   becoming over-contracted). There is no probabilistic "confidence %".
5. Data quality gates emission: an economic change computed from STALE or
   UNAVAILABLE evidence is suppressed and surfaced as a data-quality change.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.market_intelligence import (
    MarketContractPosition,
    MarketMaterialityEvent,
    MarketObservation,
    MarketPosition,
    MarketPositionSnapshot,
)
from app.services.market_intelligence import (
    ACTIVE_CONTRACT_STATUSES,
    CALCULATION_VERSION,
    MarketCalculationError,
    compute_position,
    redact_reasons,
)

METHODOLOGY_VERSION = "materiality-2026.10.1"
# Evidence states that cannot support an emitted economic change.
DEGRADED_STATES = frozenset({"STALE", "UNAVAILABLE", "SELECTION_REQUIRED"})
LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
DEFAULT_THRESHOLDS = {"MEDIUM": Decimal("2"), "HIGH": Decimal("5"), "CRITICAL": Decimal("10")}
REFERENCE_MIN_AGE = timedelta(hours=20)
SNAPSHOT_ANCHOR_INTERVAL = timedelta(hours=20)
COOLDOWN = timedelta(hours=12)

_POSITION_FIELDS = (
    "id", "position_key", "name", "commodity", "season", "country_code", "region", "market_structure",
    "reporting_currency", "quantity_unit", "expected_production", "inventory_quantity", "production_cost_per_unit",
    "current_realizable_price", "price_currency", "fx_rate_to_reporting", "freight_per_unit", "storage_per_unit",
)
_CONTRACT_FIELDS = ("id", "status", "quantity", "quantity_unit", "price", "currency", "fx_rate_to_reporting")
DRIVER_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("production", ("expected_production", "inventory_quantity")),
    ("price", ("current_realizable_price", "price_currency")),
    ("fx", ("fx_rate_to_reporting",)),
    ("costs", ("production_cost_per_unit", "freight_per_unit", "storage_per_unit", "inventory_cost_per_unit")),
)


def _s(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value) if not isinstance(value, (str, int, bool)) else value


def position_inputs(position: MarketPosition, contracts: list[MarketContractPosition]) -> dict[str, Any]:
    """Exact deterministic inputs of a position, JSON-serialisable."""
    metadata = position.metadata_json if isinstance(position.metadata_json, dict) else {}
    inputs = {name: _s(getattr(position, name, None)) for name in _POSITION_FIELDS}
    inputs["metadata_json"] = {
        key: metadata.get(key)
        for key in ("inventory_cost_per_unit", "production_cost_behavior", "price_state", "fx_state", "price_source",
                    "cost_currency", "cost_fx_rate", "cost_fx_state")
        if key in metadata
    }
    inputs["inventory_cost_per_unit"] = _s(metadata.get("inventory_cost_per_unit"))
    inputs["contracts"] = sorted(
        (
            {
                **{name: _s(getattr(contract, name, None)) for name in _CONTRACT_FIELDS},
                # Freshness of the contract's conversion is part of what changed.
                "fx_state": (contract.metadata_json or {}).get("fx_state") if isinstance(contract.metadata_json, dict) else None,
                "contract_code": getattr(contract, "contract_code", None),
            }
            for contract in contracts
        ),
        key=lambda row: str(row.get("id")),
    )
    return inputs


def inputs_hash(inputs: dict[str, Any]) -> str:
    material = json.loads(json.dumps({k: v for k, v in inputs.items() if k not in {"id", "name", "position_key"}}, default=str))
    if isinstance(material.get("metadata_json"), dict):
        material["metadata_json"].pop("price_source", None)  # label only; values are hashed separately
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _compute(inputs: dict[str, Any]) -> dict[str, Any] | None:
    position = {k: v for k, v in inputs.items() if k != "contracts"}
    position.setdefault("metadata_json", {})
    if inputs.get("inventory_cost_per_unit") is not None:
        position["metadata_json"] = {**position["metadata_json"], "inventory_cost_per_unit": inputs["inventory_cost_per_unit"]}
    try:
        return compute_position(position, inputs.get("contracts") or []).payload
    except MarketCalculationError:
        return None


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def evidence_states(db: Session, position: MarketPosition, contracts: list[MarketContractPosition] | None = None) -> dict[str, Any]:
    """Freshness of the evidence currently driving price, FX, cost FX and contract FX.

    Contract conversions are tracked per contract (``contract_fx:<code>``) so a
    stale or missing USD rate on one contract is visible and gates materiality
    instead of silently producing incomplete commercial truth.
    """
    metadata = position.metadata_json if isinstance(position.metadata_json, dict) else {}
    price_state = metadata.get("price_state")
    if price_state is None:
        latest_manual = (
            db.query(MarketObservation)
            .filter(
                MarketObservation.organization_id == position.organization_id,
                MarketObservation.position_id == position.id,
                MarketObservation.observation_type.in_(("cash_price", "physical_price", "realizable_price")),
            )
            .order_by(MarketObservation.observed_at.desc())
            .first()
        )
        price_state = latest_manual.source_status if latest_manual else ("MANUAL" if position.current_realizable_price is not None else "UNAVAILABLE")
    fx_needed = str(position.price_currency or position.reporting_currency).upper() != str(position.reporting_currency).upper()
    fx_state = metadata.get("fx_state") if fx_needed else "NOT_REQUIRED"
    if fx_needed and fx_state is None:
        fx_state = "MANUAL" if position.fx_rate_to_reporting is not None else "UNAVAILABLE"
    states = {"price": str(price_state).upper(), "fx": str(fx_state).upper()}
    reporting = str(position.reporting_currency or "").upper()
    cost_currency = str(metadata.get("cost_currency") or reporting).upper()
    price_currency = str(position.price_currency or position.local_currency or reporting).upper()
    if cost_currency not in {reporting, price_currency}:
        cost_state = metadata.get("cost_fx_state") or ("MANUAL" if metadata.get("cost_fx_rate") else "UNAVAILABLE")
        states["cost_fx"] = str(cost_state).upper()
    for contract in contracts or []:
        if str(contract.status or "active").lower() not in ACTIVE_CONTRACT_STATUSES:
            continue
        if str(contract.currency or reporting).upper() == reporting:
            continue
        contract_metadata = contract.metadata_json if isinstance(contract.metadata_json, dict) else {}
        state = contract_metadata.get("fx_state") or ("MANUAL" if contract.fx_rate_to_reporting is not None else "UNAVAILABLE")
        states[f"contract_fx:{contract.contract_code}"] = str(state).upper()
    return states


def record_snapshot(db: Session, position: MarketPosition, contracts: list[MarketContractPosition], *, now: datetime | None = None) -> tuple[MarketPositionSnapshot, bool]:
    """Persist a snapshot when inputs changed or the daily anchor is due."""
    now = now or datetime.utcnow()
    inputs = position_inputs(position, contracts)
    digest = inputs_hash(inputs)
    latest = (
        db.query(MarketPositionSnapshot)
        .filter(MarketPositionSnapshot.organization_id == position.organization_id, MarketPositionSnapshot.position_id == position.id)
        .order_by(MarketPositionSnapshot.computed_at.desc())
        .first()
    )
    if latest is not None and latest.inputs_hash == digest and now - latest.computed_at < SNAPSHOT_ANCHOR_INTERVAL:
        return latest, False
    computation = compute_position(position, contracts)
    snapshot = MarketPositionSnapshot(
        organization_id=position.organization_id,
        position_id=position.id,
        computed_at=now,
        inputs_hash=digest,
        inputs_json=inputs,
        payload_json=computation.payload,
        evidence_json={"states": evidence_states(db, position, contracts)},
        calculation_version=CALCULATION_VERSION,
    )
    db.add(snapshot)
    db.flush()
    return snapshot, True


def reference_snapshot(db: Session, position: MarketPosition, *, now: datetime | None = None) -> MarketPositionSnapshot | None:
    now = now or datetime.utcnow()
    base = db.query(MarketPositionSnapshot).filter(
        MarketPositionSnapshot.organization_id == position.organization_id,
        MarketPositionSnapshot.position_id == position.id,
    )
    aged = base.filter(MarketPositionSnapshot.computed_at <= now - REFERENCE_MIN_AGE).order_by(MarketPositionSnapshot.computed_at.desc()).first()
    return aged or base.order_by(MarketPositionSnapshot.computed_at.asc()).first()


def _metric(payload: dict[str, Any] | None, use_margin: bool) -> Decimal | None:
    if payload is None:
        return None
    return _dec(payload.get("projected_margin") if use_margin else payload.get("exposed_revenue"))


def attribute_drivers(reference_inputs: dict[str, Any], current_inputs: dict[str, Any], *, use_margin: bool) -> list[dict[str, str]] | None:
    """Sequential-substitution attribution; contributions sum to the total."""
    working = json.loads(json.dumps(reference_inputs, default=str))
    previous = _metric(_compute(working), use_margin)
    if previous is None:
        return None
    contributions: list[dict[str, str]] = []
    groups = [*DRIVER_GROUPS, ("contracts", ("contracts",))]
    for driver, keys in groups:
        changed = any(working.get(key) != current_inputs.get(key) for key in keys)
        for key in keys:
            working[key] = current_inputs.get(key)
        if driver == "price" and working.get("price_currency") != reference_inputs.get("price_currency"):
            working["fx_rate_to_reporting"] = current_inputs.get("fx_rate_to_reporting")
        value = _metric(_compute(working), use_margin)
        if value is None:
            return None
        if changed or value != previous:
            contributions.append({"driver": driver, "contribution": format((value - previous).quantize(Decimal("0.01")), "f")})
        previous = value
    # Anything else that changed (unit, currency, commodity edits) is reported
    # explicitly so contributions always sum to the total change.
    final = _metric(_compute(json.loads(json.dumps(current_inputs, default=str))), use_margin)
    if final is None:
        return None
    if final != previous:
        contributions.append({"driver": "other", "contribution": format((final - previous).quantize(Decimal("0.01")), "f")})
    return contributions


@dataclass
class MaterialityResult:
    level: str
    kind: str
    emit: bool
    title_key: str
    reasons: list[dict[str, Any]] = field(default_factory=list)
    impact: dict[str, Any] = field(default_factory=dict)
    data_quality: dict[str, Any] = field(default_factory=dict)
    suppressed_reason: str | None = None


def _level_for_ratio(ratio: Decimal | None, thresholds: dict[str, Decimal]) -> str:
    if ratio is None:
        return "LOW"
    for level in ("CRITICAL", "HIGH", "MEDIUM"):
        if ratio >= thresholds[level]:
            return level
    return "LOW"


def _max_level(*levels: str) -> str:
    return max(levels, key=LEVELS.index)


def thresholds_for(position: MarketPosition) -> tuple[dict[str, Decimal], Decimal]:
    metadata = position.metadata_json if isinstance(position.metadata_json, dict) else {}
    config = metadata.get("materiality") if isinstance(metadata.get("materiality"), dict) else {}
    thresholds = dict(DEFAULT_THRESHOLDS)
    for level in ("MEDIUM", "HIGH", "CRITICAL"):
        value = _dec(config.get(f"{level.lower()}_pct"))
        if value is not None and value > 0:
            thresholds[level] = value
    minimum = _dec(config.get("min_absolute_impact")) or Decimal("0")
    return thresholds, max(Decimal("0"), minimum)


def evaluate(
    reference: MarketPositionSnapshot,
    current: MarketPositionSnapshot,
    *,
    thresholds: dict[str, Decimal] | None = None,
    min_absolute_impact: Decimal = Decimal("0"),
) -> list[MaterialityResult]:
    thresholds = thresholds or DEFAULT_THRESHOLDS
    before, after = reference.payload_json or {}, current.payload_json or {}
    states_before = (reference.evidence_json or {}).get("states") or {}
    states_after = (current.evidence_json or {}).get("states") or {}
    currency = after.get("reporting_currency")
    results: list[MaterialityResult] = []

    # --- data quality transitions -------------------------------------------------
    degraded_now = [k for k, v in states_after.items() if v in DEGRADED_STATES]
    newly_degraded = [k for k in degraded_now if states_before.get(k) not in DEGRADED_STATES]
    if newly_degraded:
        results.append(MaterialityResult(
            level="MEDIUM", kind="data_quality", emit=True, title_key="market.materiality.data_quality",
            reasons=[{"code": "evidence_degraded", "evidence": k, "state": states_after[k]} for k in newly_degraded],
            data_quality={"states": states_after},
        ))
    if before.get("data_complete") and not after.get("data_complete"):
        results.append(MaterialityResult(
            level="MEDIUM", kind="data_quality", emit=True, title_key="market.materiality.inputs_incomplete",
            reasons=[{"code": "missing_inputs", "inputs": after.get("missing_inputs") or []}],
            data_quality={"states": states_after},
        ))

    # --- economic change ----------------------------------------------------------
    use_margin = before.get("projected_margin") is not None and after.get("projected_margin") is not None
    metric_before, metric_after = _metric(before, use_margin), _metric(after, use_margin)
    reasons: list[dict[str, Any]] = []
    level = "LOW"
    impact: dict[str, Any] = {"currency": currency, "basis": "projected_margin" if use_margin else "exposed_revenue"}
    if metric_before is not None and metric_after is not None:
        change = metric_after - metric_before
        revenue_base = _dec(before.get("projected_revenue")) or (
            (_dec(before.get("locked_revenue")) or Decimal("0")) + (_dec(before.get("exposed_revenue")) or Decimal("0"))
        )
        ratio = (abs(change) / revenue_base * Decimal("100")).quantize(Decimal("0.01")) if revenue_base and revenue_base > 0 else None
        level = _level_for_ratio(ratio, thresholds) if abs(change) >= min_absolute_impact else "LOW"
        impact.update({
            "change": format(change.quantize(Decimal("0.01")), "f"),
            "direction": "down" if change < 0 else "up" if change > 0 else "flat",
            "impact_percent_of_revenue": format(ratio, "f") if ratio is not None else None,
            "reference_value": format(metric_before.quantize(Decimal("0.01")), "f"),
            "current_value": format(metric_after.quantize(Decimal("0.01")), "f"),
            "thresholds_percent": {k: format(v, "f") for k, v in thresholds.items()},
        })
        drivers = attribute_drivers(reference.inputs_json or {}, current.inputs_json or {}, use_margin=use_margin)
        if drivers:
            impact["drivers"] = drivers
            impact["attribution_method"] = "sequential_substitution(production, price, fx, costs, contracts)"
        if change != 0:
            reasons.append({"code": "economic_change", "metric": impact["basis"], "change": impact["change"], "currency": currency,
                            "impact_percent_of_revenue": impact["impact_percent_of_revenue"]})
        price_before, price_after = _dec(before.get("current_realizable_price")), _dec(after.get("current_realizable_price"))
        if price_before and price_after and price_before > 0 and price_after != price_before:
            reasons.append({"code": "price_change", "from": format(price_before, "f"), "to": format(price_after, "f"),
                            "percent": format(((price_after - price_before) / price_before * 100).quantize(Decimal("0.01")), "f"),
                            "unit": after.get("quantity_unit"), "currency": currency})
    exposed_value = _dec(after.get("exposed_revenue"))
    if exposed_value is not None and exposed_value > 0:
        reasons.append({"code": "exposure", "uncontracted_quantity": after.get("uncontracted_quantity"), "unit": after.get("quantity_unit"),
                        "exposed_revenue": after.get("exposed_revenue"), "exposed_percent": after.get("exposed_percent"), "currency": currency})

    margin_before, margin_after = _dec(before.get("projected_margin")), _dec(after.get("projected_margin"))
    if margin_before is not None and margin_after is not None and margin_before >= 0 > margin_after:
        level = _max_level(level, "CRITICAL")
        reasons.append({"code": "margin_turned_negative", "projected_margin": after.get("projected_margin"), "currency": currency})
    price_after = _dec(after.get("current_realizable_price"))
    breakeven_after = _dec(after.get("break_even_price"))
    price_before = _dec(before.get("current_realizable_price"))
    breakeven_before = _dec(before.get("break_even_price"))
    if price_after is not None and breakeven_after is not None and price_after < breakeven_after and not (
        price_before is not None and breakeven_before is not None and price_before < breakeven_before
    ):
        level = _max_level(level, "HIGH")
        reasons.append({"code": "price_below_break_even", "current_realizable_price": after.get("current_realizable_price"),
                        "break_even_price": after.get("break_even_price"), "currency": currency})
    if after.get("over_contracted") and not before.get("over_contracted"):
        level = _max_level(level, "HIGH")
        reasons.append({"code": "over_contracted", "contracted_quantity": after.get("contracted_quantity"),
                        "marketable_supply": after.get("marketable_supply"), "unit": after.get("quantity_unit")})

    if level != "LOW":
        # Every input conversion counts: a stale contract or cost FX makes the
        # computed change unreliable, so it is suppressed like a stale price.
        evidence_ok = all(state not in DEGRADED_STATES for state in states_after.values())
        result = MaterialityResult(
            level=level, kind="commercial_change", emit=evidence_ok, title_key="market.materiality.commercial_change",
            reasons=reasons, impact=impact, data_quality={"states": states_after},
            suppressed_reason=None if evidence_ok else "evidence_not_fresh",
        )
        results.append(result)
    return results


def _dedupe_key(position_id: str, result: MaterialityResult, reference: MarketPositionSnapshot, current: MarketPositionSnapshot) -> str:
    material = f"{position_id}|{result.kind}|{result.level}|{reference.id}|{current.inputs_hash}"
    return hashlib.sha256(material.encode()).hexdigest()


def persist_events(
    db: Session,
    position: MarketPosition,
    reference: MarketPositionSnapshot,
    current: MarketPositionSnapshot,
    results: list[MaterialityResult],
    *,
    now: datetime | None = None,
) -> list[MarketMaterialityEvent]:
    """Persist emitted MEDIUM+ results with dedupe and cooldown. Does not commit."""
    now = now or datetime.utcnow()
    created: list[MarketMaterialityEvent] = []
    for result in results:
        if not result.emit or result.level == "LOW":
            continue
        key = _dedupe_key(position.id, result, reference, current)
        if db.query(MarketMaterialityEvent.id).filter(
            MarketMaterialityEvent.organization_id == position.organization_id, MarketMaterialityEvent.dedupe_key == key,
        ).first():
            continue
        recent = (
            db.query(MarketMaterialityEvent)
            .filter(
                MarketMaterialityEvent.organization_id == position.organization_id,
                MarketMaterialityEvent.position_id == position.id,
                MarketMaterialityEvent.kind == result.kind,
                MarketMaterialityEvent.created_at >= now - COOLDOWN,
            )
            .order_by(MarketMaterialityEvent.created_at.desc())
            .first()
        )
        if recent is not None and LEVELS.index(result.level) <= LEVELS.index(recent.level):
            continue  # cooldown: only an escalation may re-alert within 12 hours
        event = MarketMaterialityEvent(
            organization_id=position.organization_id,
            position_id=position.id,
            dedupe_key=key,
            kind=result.kind,
            level=result.level,
            status="open",
            title_key=result.title_key,
            reasons_json=redact_reasons(result.reasons, position),
            impact_json=result.impact,
            data_quality_json=result.data_quality,
            reference_snapshot_id=reference.id,
            current_snapshot_id=current.id,
            methodology_version=METHODOLOGY_VERSION,
            notified_json={},
            created_at=now,
        )
        db.add(event)
        created.append(event)
    db.flush()
    return created


def evaluate_position(db: Session, position: MarketPosition, *, now: datetime | None = None) -> dict[str, Any]:
    """Snapshot, compare with the reference and persist material events."""
    now = now or datetime.utcnow()
    contracts = (
        db.query(MarketContractPosition)
        .filter(MarketContractPosition.organization_id == position.organization_id, MarketContractPosition.position_id == position.id)
        .all()
    )
    try:
        current, created_snapshot = record_snapshot(db, position, contracts, now=now)
    except MarketCalculationError as exc:
        return {"position_id": position.id, "status": "invalid_position", "reason": str(exc)}
    reference = reference_snapshot(db, position, now=now)
    if reference is None or reference.id == current.id:
        return {"position_id": position.id, "status": "baseline_recorded", "snapshot_id": current.id}
    thresholds, minimum = thresholds_for(position)
    results = evaluate(reference, current, thresholds=thresholds, min_absolute_impact=minimum)
    events = persist_events(db, position, reference, current, results, now=now)
    return {
        "position_id": position.id,
        "status": "evaluated",
        "snapshot_created": created_snapshot,
        "reference_snapshot_id": reference.id,
        "current_snapshot_id": current.id,
        "results": [{"kind": r.kind, "level": r.level, "emit": r.emit, "suppressed_reason": r.suppressed_reason} for r in results],
        "events_created": [event.id for event in events],
    }


def event_payload(event: MarketMaterialityEvent, position: MarketPosition | None = None) -> dict[str, Any]:
    return {
        "id": event.id,
        "position_id": event.position_id,
        "position_name": position.name if position is not None else None,
        "kind": event.kind,
        "level": event.level,
        "status": event.status,
        "title_key": event.title_key,
        "reasons": event.reasons_json or [],
        "impact": event.impact_json or {},
        "data_quality": event.data_quality_json or {},
        "methodology_version": event.methodology_version,
        "reference_snapshot_id": event.reference_snapshot_id,
        "current_snapshot_id": event.current_snapshot_id,
        "created_at": event.created_at.isoformat() + "Z" if event.created_at else None,
        "acknowledged_at": event.acknowledged_at.isoformat() + "Z" if event.acknowledged_at else None,
    }
