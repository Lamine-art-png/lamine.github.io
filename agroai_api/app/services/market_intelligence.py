"""Deterministic economics for AGRO-AI Market Intelligence.

LLMs are deliberately excluded from financial truth.  All quantities, money,
FX, exposure and scenario transformations are fixed-precision and auditable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

CALCULATION_VERSION = "market-economics-2026.09.2"
FX_QUOTE_CONVENTION = "reporting_currency_per_source_currency"
ZERO = Decimal("0")
ONE = Decimal("1")
Q8 = Decimal("0.00000001")
MONEY = Decimal("0.01")

# Kilograms represented by one unit. Bushel weights are commodity-specific.
_KG_PER_UNIT: dict[str, Decimal] = {
    "kg": Decimal("1"),
    "kilogram": Decimal("1"),
    "kilograms": Decimal("1"),
    "t": Decimal("1000"),
    "tonne": Decimal("1000"),
    "tonnes": Decimal("1000"),
    "metric_tonne": Decimal("1000"),
    "metric_tonnes": Decimal("1000"),
    "lb": Decimal("0.45359237"),
    "lbs": Decimal("0.45359237"),
    "pound": Decimal("0.45359237"),
    "pounds": Decimal("0.45359237"),
}
_BUSHEL_KG: dict[str, Decimal] = {
    "corn": Decimal("25.40117272"),       # 56 lb
    "maize": Decimal("25.40117272"),
    "soybean": Decimal("27.21554220"),    # 60 lb
    "soybeans": Decimal("27.21554220"),
    "wheat": Decimal("27.21554220"),      # 60 lb
    "sorghum": Decimal("25.40117272"),    # 56 lb
    "barley": Decimal("21.77243376"),     # 48 lb
    "oats": Decimal("14.51495584"),       # 32 lb
}


class MarketCalculationError(ValueError):
    """A safe, user-actionable quantitative validation error."""


def dec(value: Any, default: Decimal | None = None) -> Decimal:
    if value is None or value == "":
        if default is not None:
            return default
        raise MarketCalculationError("missing numeric value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MarketCalculationError(f"invalid numeric value: {value!r}") from exc
    if not result.is_finite():
        raise MarketCalculationError("numeric value must be finite")
    return result


def _attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _metadata(value: Any) -> dict[str, Any]:
    raw = _attr(value, "metadata_json", _attr(value, "metadata", {})) or {}
    return raw if isinstance(raw, dict) else {}


def _unit_key(unit: str) -> str:
    return str(unit or "").strip().lower().replace(" ", "_")


def _commodity_key(commodity: str) -> str:
    return str(commodity or "").strip().lower().replace(" ", "_")


def kg_per_unit(unit: str, commodity: str) -> Decimal:
    key = _unit_key(unit)
    if key in {"bu", "bushel", "bushels"}:
        crop = _commodity_key(commodity)
        if crop not in _BUSHEL_KG:
            raise MarketCalculationError(
                f"bushel conversion is commodity-specific and is not configured for {commodity!r}"
            )
        return _BUSHEL_KG[crop]
    if key not in _KG_PER_UNIT:
        raise MarketCalculationError(f"unsupported quantity unit: {unit!r}")
    return _KG_PER_UNIT[key]


def convert_quantity(value: Any, from_unit: str, to_unit: str, commodity: str) -> Decimal:
    amount = dec(value)
    if amount < ZERO:
        raise MarketCalculationError("quantity cannot be negative")
    if _unit_key(from_unit) == _unit_key(to_unit):
        return amount
    kilograms = amount * kg_per_unit(from_unit, commodity)
    return (kilograms / kg_per_unit(to_unit, commodity)).quantize(Q8, rounding=ROUND_HALF_UP)


def convert_price_per_unit(
    price: Any,
    from_unit: str,
    to_unit: str,
    commodity: str,
) -> Decimal:
    p = dec(price)
    if p < ZERO:
        raise MarketCalculationError("price cannot be negative")
    if _unit_key(from_unit) == _unit_key(to_unit):
        return p
    # One from-unit expressed in target units. Price per target unit is price
    # divided by that quantity (e.g. $5/bu -> ~$197/t for corn).
    target_units = convert_quantity(ONE, from_unit, to_unit, commodity)
    if target_units <= ZERO:
        raise MarketCalculationError("invalid unit conversion factor")
    return (p / target_units).quantize(Q8, rounding=ROUND_HALF_UP)


def fx_to_reporting(amount: Decimal, source_currency: str, reporting_currency: str, fx_rate: Any | None) -> Decimal:
    source = str(source_currency or "").upper()
    reporting = str(reporting_currency or "").upper()
    if not source or not reporting:
        raise MarketCalculationError("currency is required")
    if source == reporting:
        return amount
    if fx_rate is None:
        raise MarketCalculationError(f"FX rate required for {source}/{reporting}")
    rate = dec(fx_rate)
    if rate <= ZERO:
        raise MarketCalculationError("FX rate must be greater than zero")
    return amount * rate


def _out(value: Decimal | None, places: Decimal = Q8) -> str | None:
    if value is None:
        return None
    return format(value.quantize(places, rounding=ROUND_HALF_UP), "f")


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= ZERO:
        return None
    return (numerator / denominator * Decimal("100")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PositionComputation:
    payload: dict[str, Any]
    evidence: dict[str, str]


def compute_position(position: Any, contracts: Iterable[Any] = ()) -> PositionComputation:
    commodity = str(_attr(position, "commodity") or "").strip()
    unit = str(_attr(position, "quantity_unit") or "").strip()
    reporting_currency = str(_attr(position, "reporting_currency") or "").upper()
    expected = dec(_attr(position, "expected_production"))
    inventory = dec(_attr(position, "inventory_quantity"), ZERO)
    if expected < ZERO or inventory < ZERO:
        raise MarketCalculationError("production and inventory cannot be negative")
    marketable_supply = expected + inventory
    metadata = _metadata(position)

    production_cost_raw = _attr(position, "production_cost_per_unit")
    fixed_production_cost_raw = _attr(position, "fixed_production_cost_total")
    cost_per_unit = dec(production_cost_raw) if production_cost_raw is not None else None
    freight_per_unit = dec(_attr(position, "freight_per_unit"), ZERO)
    storage_per_unit = dec(_attr(position, "storage_per_unit"), ZERO)
    if (cost_per_unit is not None and cost_per_unit < ZERO) or min(freight_per_unit, storage_per_unit) < ZERO:
        raise MarketCalculationError("cost values cannot be negative")

    warnings: list[str] = []
    missing_inputs: list[str] = []
    if cost_per_unit is None and fixed_production_cost_raw is None:
        missing_inputs.append("production_cost_per_unit")
        warnings.append("production cost basis is required before projected cost, break-even and margin can be calculated")
    contracted = ZERO
    locked_revenue = ZERO
    weighted_price_numerator = ZERO
    contract_rows = 0
    missing_contract_fx = False

    for contract in contracts:
        # Fulfilled contracts remain part of the season's committed volume
        # and locked/realized commercial revenue. Cancelled contracts do not.
        if str(_attr(contract, "status", "active")).lower() not in {"active", "priced", "committed", "fulfilled"}:
            continue
        quantity = convert_quantity(
            _attr(contract, "quantity"),
            str(_attr(contract, "quantity_unit")),
            unit,
            commodity,
        )
        price_per_target = convert_price_per_unit(
            _attr(contract, "price"),
            str(_attr(contract, "quantity_unit")),
            unit,
            commodity,
        )
        try:
            reporting_price = fx_to_reporting(
                price_per_target,
                str(_attr(contract, "currency")),
                reporting_currency,
                _attr(contract, "fx_rate_to_reporting"),
            )
        except MarketCalculationError:
            missing_contract_fx = True
            reporting_price = ZERO
        contracted += quantity
        if not missing_contract_fx:
            locked_revenue += quantity * reporting_price
            weighted_price_numerator += quantity * reporting_price
        contract_rows += 1

    over_contracted = contracted > marketable_supply
    uncontracted = max(ZERO, marketable_supply - contracted)
    if over_contracted:
        warnings.append("contracted volume exceeds marketable supply")
    if missing_contract_fx:
        warnings.append("one or more contracts require an FX rate before revenue and margin can be reconciled")
        missing_inputs.append("contract_fx")

    spot_price_reporting: Decimal | None = None
    raw_price = _attr(position, "current_realizable_price")
    if raw_price is None:
        missing_inputs.append("current_realizable_price")
    else:
        try:
            spot_price_reporting = fx_to_reporting(
                dec(raw_price),
                str(_attr(position, "price_currency") or reporting_currency),
                reporting_currency,
                _attr(position, "fx_rate_to_reporting"),
            )
        except MarketCalculationError:
            missing_inputs.append("market_fx")
            warnings.append("current market price cannot be translated to reporting currency without FX")

    exposed_revenue = uncontracted * spot_price_reporting if spot_price_reporting is not None else None
    expected_revenue: Decimal | None = None
    if not missing_contract_fx and exposed_revenue is not None:
        expected_revenue = locked_revenue + exposed_revenue

    cost_behavior = str(metadata.get("production_cost_behavior") or "fixed_total_at_baseline_yield")
    if cost_behavior != "fixed_total_at_baseline_yield":
        raise MarketCalculationError("unsupported production_cost_behavior")
    if fixed_production_cost_raw is not None:
        fixed_production_cost_total = dec(fixed_production_cost_raw)
    elif cost_per_unit is not None:
        fixed_production_cost_total = expected * cost_per_unit
    else:
        fixed_production_cost_total = None
    if fixed_production_cost_total is not None and fixed_production_cost_total < ZERO:
        raise MarketCalculationError("fixed production cost cannot be negative")

    inventory_cost_raw = metadata.get("inventory_cost_per_unit")
    inventory_cost_per_unit = dec(inventory_cost_raw) if inventory_cost_raw is not None else None
    if inventory > ZERO and inventory_cost_per_unit is None:
        missing_inputs.append("inventory_cost_per_unit")
        warnings.append("carry inventory is included in marketable supply, but margin is suppressed until its cost basis is supplied")
    inventory_cost_total = inventory * inventory_cost_per_unit if inventory_cost_per_unit is not None else ZERO
    variable_commercial_cost = marketable_supply * (freight_per_unit + storage_per_unit)
    cost_basis_complete = (
        fixed_production_cost_total is not None
        and (inventory == ZERO or inventory_cost_per_unit is not None)
    )
    total_cost = (
        fixed_production_cost_total + inventory_cost_total + variable_commercial_cost
        if cost_basis_complete
        else None
    )
    break_even = total_cost / marketable_supply if total_cost is not None and marketable_supply > ZERO else None
    suppress_margin = (
        over_contracted
        or missing_contract_fx
        or expected_revenue is None
        or total_cost is None
    )
    gross_margin = None if suppress_margin else expected_revenue - total_cost
    margin_pct = None if gross_margin is None or expected_revenue in {None, ZERO} else _pct(gross_margin, expected_revenue)
    weighted_contract_price = None if contracted <= ZERO or missing_contract_fx else weighted_price_numerator / contracted

    contracted_pct = _pct(contracted, marketable_supply)
    exposed_pct = _pct(uncontracted, marketable_supply)
    data_complete = not suppress_margin and not missing_inputs

    payload = {
        "calculation_version": CALCULATION_VERSION,
        "position_id": str(_attr(position, "id") or ""),
        "position_key": str(_attr(position, "position_key") or ""),
        "name": str(_attr(position, "name") or ""),
        "commodity": commodity,
        "season": str(_attr(position, "season") or ""),
        "country_code": str(_attr(position, "country_code") or "").upper(),
        "region": _attr(position, "region"),
        "market_structure": str(_attr(position, "market_structure") or "physical"),
        "reporting_currency": reporting_currency,
        "quantity_unit": unit,
        "expected_production": _out(expected),
        "inventory_quantity": _out(inventory),
        "marketable_supply": _out(marketable_supply),
        "contracted_quantity": _out(contracted),
        "uncontracted_quantity": _out(uncontracted),
        "contracted_percent": _out(contracted_pct, Decimal("0.0001")) if contracted_pct is not None else None,
        "exposed_percent": _out(exposed_pct, Decimal("0.0001")) if exposed_pct is not None else None,
        "weighted_contract_price": _out(weighted_contract_price) if weighted_contract_price is not None else None,
        "current_realizable_price": _out(spot_price_reporting) if spot_price_reporting is not None else None,
        "production_cost_per_unit": _out(cost_per_unit) if cost_per_unit is not None else None,
        "production_cost_behavior": cost_behavior,
        "fixed_production_cost_total": _out(fixed_production_cost_total, MONEY) if fixed_production_cost_total is not None else None,
        "inventory_cost_per_unit": _out(inventory_cost_per_unit) if inventory_cost_per_unit is not None else None,
        "freight_per_unit": _out(freight_per_unit),
        "storage_per_unit": _out(storage_per_unit),
        "break_even_price": _out(break_even) if break_even is not None else None,
        "fx_quote_convention": FX_QUOTE_CONVENTION,
        "locked_revenue": None if missing_contract_fx else _out(locked_revenue, MONEY),
        "exposed_revenue": _out(exposed_revenue, MONEY) if exposed_revenue is not None else None,
        "projected_revenue": _out(expected_revenue, MONEY) if expected_revenue is not None and not over_contracted else None,
        "projected_cost": _out(total_cost, MONEY) if total_cost is not None else None,
        "projected_margin": _out(gross_margin, MONEY) if gross_margin is not None else None,
        "projected_margin_percent": _out(margin_pct, Decimal("0.0001")) if margin_pct is not None else None,
        "over_contracted": over_contracted,
        "data_complete": data_complete,
        "missing_inputs": sorted(set(missing_inputs)),
        "warnings": warnings,
        "contract_count": contract_rows,
    }
    evidence = {
        "expected_production": payload["expected_production"],
        "inventory_quantity": payload["inventory_quantity"],
        "marketable_supply": payload["marketable_supply"],
        "contracted_quantity": payload["contracted_quantity"],
        "uncontracted_quantity": payload["uncontracted_quantity"],
        "locked_revenue": payload["locked_revenue"] or "unavailable",
        "exposed_revenue": payload["exposed_revenue"] or "unavailable",
        "projected_revenue": payload["projected_revenue"] or "unavailable",
        "projected_margin": payload["projected_margin"] or "unavailable",
        "projected_margin_percent": payload["projected_margin_percent"] or "unavailable",
        "break_even_price": payload["break_even_price"] or "unavailable",
        "current_realizable_price": payload["current_realizable_price"] or "unavailable",
    }
    return PositionComputation(payload=payload, evidence=evidence)


def _scenario_decimal(assumptions: dict[str, Any], key: str) -> Decimal:
    value = dec(assumptions.get(key, ZERO), ZERO)
    if value < Decimal("-100") and key in {"price_pct", "yield_pct", "production_cost_pct", "fx_pct"}:
        raise MarketCalculationError(f"{key} cannot reduce a value below zero")
    return value


def scenario_position(position: Any, contracts: list[Any], assumptions: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic baseline/result/delta for a commercial scenario.

    Supported assumptions: price_pct, yield_pct, fx_pct,
    production_cost_pct, freight_per_unit_delta, storage_per_unit_delta,
    sell_pct_now.  `sell_pct_now` locks a share of the *remaining* uncontracted
    volume at the scenario spot price; it never executes a trade. ``fx_pct``
    changes the quote expressed as reporting-currency units per one unit of
    source currency, so +5% raises that rate by exactly 5%.
    """
    baseline = compute_position(position, contracts).payload
    price_pct = _scenario_decimal(assumptions, "price_pct")
    yield_pct = _scenario_decimal(assumptions, "yield_pct")
    fx_pct = _scenario_decimal(assumptions, "fx_pct")
    cost_pct = _scenario_decimal(assumptions, "production_cost_pct")
    freight_delta = dec(assumptions.get("freight_per_unit_delta", ZERO), ZERO)
    storage_delta = dec(assumptions.get("storage_per_unit_delta", ZERO), ZERO)
    sell_pct = dec(assumptions.get("sell_pct_now", ZERO), ZERO)
    if sell_pct < ZERO or sell_pct > Decimal("100"):
        raise MarketCalculationError("sell_pct_now must be between 0 and 100")

    zero_change = all(v == ZERO for v in (price_pct, yield_pct, fx_pct, cost_pct, freight_delta, storage_delta, sell_pct))
    if zero_change:
        return {
            "calculation_version": CALCULATION_VERSION,
            "assumptions": {k: str(v) for k, v in assumptions.items()},
            "baseline": baseline,
            "result": dict(baseline),
            "delta": {"projected_revenue": "0.00", "projected_margin": "0.00", "exposed_revenue": "0.00"},
            "zero_change_invariant": True,
        }

    mutable = {
        key: _attr(position, key)
        for key in (
            "id", "position_key", "name", "commodity", "season", "country_code", "region", "market_structure",
            "reporting_currency", "quantity_unit", "expected_production", "inventory_quantity", "production_cost_per_unit",
            "current_realizable_price", "price_currency", "fx_rate_to_reporting", "freight_per_unit", "storage_per_unit",
            "metadata_json",
        )
    }
    baseline_cost_per_unit = (
        dec(mutable["production_cost_per_unit"])
        if mutable["production_cost_per_unit"] is not None
        else None
    )
    baseline_production_cost_total = (
        dec(mutable["expected_production"]) * baseline_cost_per_unit
        if baseline_cost_per_unit is not None
        else None
    )
    mutable["expected_production"] = dec(mutable["expected_production"]) * (ONE + yield_pct / Decimal("100"))
    if mutable["current_realizable_price"] is not None:
        mutable["current_realizable_price"] = dec(mutable["current_realizable_price"]) * (ONE + price_pct / Decimal("100"))
    if mutable["fx_rate_to_reporting"] is not None:
        mutable["fx_rate_to_reporting"] = dec(mutable["fx_rate_to_reporting"]) * (ONE + fx_pct / Decimal("100"))
    if mutable["production_cost_per_unit"] is not None:
        mutable["production_cost_per_unit"] = dec(mutable["production_cost_per_unit"]) * (ONE + cost_pct / Decimal("100"))
    if baseline_production_cost_total is not None:
        mutable["fixed_production_cost_total"] = baseline_production_cost_total * (ONE + cost_pct / Decimal("100"))
    mutable["freight_per_unit"] = dec(mutable["freight_per_unit"], ZERO) + freight_delta
    mutable["storage_per_unit"] = dec(mutable["storage_per_unit"], ZERO) + storage_delta
    if mutable["freight_per_unit"] < ZERO or mutable["storage_per_unit"] < ZERO:
        raise MarketCalculationError("scenario freight and storage costs cannot be negative")

    scenario_contracts: list[dict[str, Any]] = []
    for contract in contracts:
        scenario_contract = {
            key: _attr(contract, key)
            for key in ("status", "quantity", "quantity_unit", "price", "currency", "fx_rate_to_reporting")
        }
        contract_currency = str(scenario_contract.get("currency") or "").upper()
        if contract_currency != str(mutable["reporting_currency"] or "").upper() and scenario_contract["fx_rate_to_reporting"] is not None:
            scenario_contract["fx_rate_to_reporting"] = dec(scenario_contract["fx_rate_to_reporting"]) * (
                ONE + fx_pct / Decimal("100")
            )
        scenario_contracts.append(scenario_contract)

    result = compute_position(mutable, scenario_contracts).payload
    if sell_pct > ZERO and (
        result.get("current_realizable_price") is None
        or result.get("locked_revenue") is None
        or result.get("projected_revenue") is None
        or result.get("over_contracted")
    ):
        raise MarketCalculationError("sell_pct_now requires a reconciled position and realizable market price")
    if sell_pct > ZERO:
        remaining = dec(result["uncontracted_quantity"], ZERO)
        if remaining <= ZERO:
            raise MarketCalculationError("sell_pct_now requires positive uncontracted production")
        sold_now = remaining * sell_pct / Decimal("100")
        price = dec(result["current_realizable_price"])
        add_locked = sold_now * price
        locked = dec(result.get("locked_revenue"), ZERO) + add_locked
        new_uncontracted = remaining - sold_now
        exposed = new_uncontracted * price
        result["contracted_quantity"] = _out(dec(result["contracted_quantity"]) + sold_now)
        result["uncontracted_quantity"] = _out(new_uncontracted)
        result["locked_revenue"] = _out(locked, MONEY)
        result["exposed_revenue"] = _out(exposed, MONEY)
        result["contracted_percent"] = _out(_pct(dec(result["contracted_quantity"]), dec(result["marketable_supply"])), Decimal("0.0001"))
        result["exposed_percent"] = _out(_pct(new_uncontracted, dec(result["marketable_supply"])), Decimal("0.0001"))
        result["weighted_contract_price"] = _out(locked / dec(result["contracted_quantity"]))
        result["scenario_volume_locked_now"] = _out(sold_now)
        # Revenue is unchanged by locking at the same spot price; the risk mix changes.

    def delta(field: str) -> str | None:
        before = baseline.get(field)
        after = result.get(field)
        if before is None or after is None:
            return None
        return _out(dec(after) - dec(before), MONEY)

    return {
        "calculation_version": CALCULATION_VERSION,
        "assumptions": {k: str(v) for k, v in assumptions.items()},
        "baseline": baseline,
        "result": result,
        "delta": {
            "projected_revenue": delta("projected_revenue"),
            "projected_margin": delta("projected_margin"),
            "exposed_revenue": delta("exposed_revenue"),
        },
        "zero_change_invariant": False,
    }


def data_health(observations: Iterable[Any]) -> dict[str, Any]:
    rows = list(observations)
    if not rows:
        return {"status": "missing", "confidence": "low", "sources": [], "counts": {}}
    counts: dict[str, int] = {}
    sources: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    derived_stale = 0
    missing_freshness = 0
    low_quality = 0
    for row in rows:
        declared_state = str(_attr(row, "source_status", "UNAVAILABLE")).upper()
        observed_at = _attr(row, "observed_at")
        retrieved_at = _attr(row, "retrieved_at")
        observed_utc = None
        if observed_at:
            observed_utc = observed_at.replace(tzinfo=timezone.utc) if observed_at.tzinfo is None else observed_at.astimezone(timezone.utc)
        retrieved_utc = None
        if retrieved_at:
            retrieved_utc = retrieved_at.replace(tzinfo=timezone.utc) if retrieved_at.tzinfo is None else retrieved_at.astimezone(timezone.utc)
        age_minutes = max(0, int((now - observed_utc).total_seconds() // 60)) if observed_utc else None
        metadata = _metadata(row)
        quality = _attr(row, "quality_json", _attr(row, "quality", {})) or {}
        freshness_raw = metadata.get("freshness_max_age_minutes", quality.get("freshness_max_age_minutes"))
        freshness_minutes = int(dec(freshness_raw)) if freshness_raw is not None else None
        state = declared_state
        health_reasons: list[str] = []
        clock_skew_limit = now + timedelta(minutes=5)
        if observed_utc is not None and observed_utc > clock_skew_limit:
            state = "STALE"
            derived_stale += 1
            health_reasons.append("observed_at_in_future")
        if retrieved_utc is not None and retrieved_utc > clock_skew_limit:
            state = "STALE"
            health_reasons.append("retrieved_at_in_future")
        if freshness_minutes is not None:
            if age_minutes is None:
                missing_freshness += 1
                health_reasons.append("missing_observed_at")
            elif age_minutes > freshness_minutes and state not in {"DEMO", "UNAVAILABLE", "NOT_CONFIGURED"}:
                state = "STALE"
                derived_stale += 1
                health_reasons.append("freshness_policy_exceeded")
        elif state not in {"DEMO", "UNAVAILABLE", "NOT_CONFIGURED"}:
            missing_freshness += 1
            health_reasons.append("freshness_policy_missing")
        quality_label = str(quality.get("confidence") or quality.get("quality") or "").lower()
        fitness = str(quality.get("fitness") or "").lower()
        if quality_label in {"low", "poor", "rejected"} or fitness in {"unsupported", "unfit", "rejected"}:
            low_quality += 1
            health_reasons.append("provider_quality_low")
        counts[state] = counts.get(state, 0) + 1
        sources.append({
            "evidence_id": _attr(row, "evidence_id"),
            "provider": _attr(row, "provider"),
            "source_name": _attr(row, "source_name"),
            "status": state,
            "declared_status": declared_state,
            "observation_type": _attr(row, "observation_type"),
            "unit": _attr(row, "unit"),
            "currency": _attr(row, "currency"),
            "observed_at": observed_utc.isoformat().replace("+00:00", "Z") if observed_utc else None,
            "retrieved_at": retrieved_utc.isoformat().replace("+00:00", "Z") if retrieved_utc else None,
            "age_minutes": age_minutes,
            "freshness_max_age_minutes": freshness_minutes,
            "quality": quality,
            "licensing": _attr(row, "licensing_json", _attr(row, "licensing", {})) or {},
            "health_reasons": health_reasons,
        })
    adverse = sum(counts.get(s, 0) for s in ("STALE", "UNAVAILABLE", "NOT_CONFIGURED"))
    demos = counts.get("DEMO", 0)
    manual_or_delayed = counts.get("MANUAL", 0) + counts.get("DELAYED", 0)
    mixed_demo = demos > 0 and demos < len(rows)
    if adverse or missing_freshness or low_quality or mixed_demo:
        status, confidence = "degraded", "low" if adverse == len(rows) else "medium"
    elif demos == len(rows):
        status, confidence = "demo", "medium"
    elif manual_or_delayed:
        status, confidence = "review", "low" if manual_or_delayed == len(rows) else "medium"
    else:
        status, confidence = "healthy", "high"
    return {
        "status": status,
        "confidence": confidence,
        "sources": sources,
        "counts": counts,
        "derived_stale_count": derived_stale,
        "missing_freshness_count": missing_freshness,
        "low_quality_count": low_quality,
        "mixed_demo_and_non_demo": mixed_demo,
    }
