"""Deterministic economics for AGRO-AI Market Intelligence.

LLMs are deliberately excluded from financial truth.  All quantities, money,
FX, exposure and scenario transformations are fixed-precision and auditable.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

CALCULATION_VERSION = "market-economics-2026.09.1"
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
    "rice": Decimal("20.41165665"),       # 45 lb common rough-rice convention
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

    cost_per_unit = dec(_attr(position, "production_cost_per_unit"), ZERO)
    freight_per_unit = dec(_attr(position, "freight_per_unit"), ZERO)
    storage_per_unit = dec(_attr(position, "storage_per_unit"), ZERO)
    if min(cost_per_unit, freight_per_unit, storage_per_unit) < ZERO:
        raise MarketCalculationError("cost values cannot be negative")

    warnings: list[str] = []
    missing_inputs: list[str] = []
    contracted = ZERO
    locked_revenue = ZERO
    weighted_price_numerator = ZERO
    contract_rows = 0
    missing_contract_fx = False

    for contract in contracts:
        if str(_attr(contract, "status", "active")).lower() not in {"active", "priced", "committed"}:
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

    over_contracted = contracted > expected
    uncontracted = max(ZERO, expected - contracted)
    if over_contracted:
        warnings.append("contracted volume exceeds expected production")
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

    commercial_cost_per_unit = cost_per_unit + freight_per_unit + storage_per_unit
    total_cost = expected * commercial_cost_per_unit
    break_even = commercial_cost_per_unit
    suppress_margin = over_contracted or missing_contract_fx or expected_revenue is None
    gross_margin = None if suppress_margin else expected_revenue - total_cost
    margin_pct = None if gross_margin is None or expected_revenue in {None, ZERO} else _pct(gross_margin, expected_revenue)
    weighted_contract_price = None if contracted <= ZERO or missing_contract_fx else weighted_price_numerator / contracted

    contracted_pct = _pct(contracted, expected)
    exposed_pct = _pct(uncontracted, expected)
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
        "contracted_quantity": _out(contracted),
        "uncontracted_quantity": _out(uncontracted),
        "contracted_percent": _out(contracted_pct, Decimal("0.0001")) if contracted_pct is not None else None,
        "exposed_percent": _out(exposed_pct, Decimal("0.0001")) if exposed_pct is not None else None,
        "weighted_contract_price": _out(weighted_contract_price) if weighted_contract_price is not None else None,
        "current_realizable_price": _out(spot_price_reporting) if spot_price_reporting is not None else None,
        "production_cost_per_unit": _out(cost_per_unit),
        "freight_per_unit": _out(freight_per_unit),
        "storage_per_unit": _out(storage_per_unit),
        "break_even_price": _out(break_even),
        "locked_revenue": None if missing_contract_fx else _out(locked_revenue, MONEY),
        "exposed_revenue": _out(exposed_revenue, MONEY) if exposed_revenue is not None else None,
        "projected_revenue": _out(expected_revenue, MONEY) if expected_revenue is not None and not over_contracted else None,
        "projected_cost": _out(total_cost, MONEY),
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
        "contracted_quantity": payload["contracted_quantity"],
        "uncontracted_quantity": payload["uncontracted_quantity"],
        "locked_revenue": payload["locked_revenue"] or "unavailable",
        "exposed_revenue": payload["exposed_revenue"] or "unavailable",
        "projected_revenue": payload["projected_revenue"] or "unavailable",
        "projected_margin": payload["projected_margin"] or "unavailable",
        "projected_margin_percent": payload["projected_margin_percent"] or "unavailable",
        "break_even_price": payload["break_even_price"],
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
    volume at the scenario spot price; it never executes a trade.
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
        )
    }
    mutable["expected_production"] = dec(mutable["expected_production"]) * (ONE + yield_pct / Decimal("100"))
    if mutable["current_realizable_price"] is not None:
        mutable["current_realizable_price"] = dec(mutable["current_realizable_price"]) * (ONE + price_pct / Decimal("100"))
    if mutable["fx_rate_to_reporting"] is not None:
        mutable["fx_rate_to_reporting"] = dec(mutable["fx_rate_to_reporting"]) * (ONE + fx_pct / Decimal("100"))
    if mutable["production_cost_per_unit"] is not None:
        mutable["production_cost_per_unit"] = dec(mutable["production_cost_per_unit"]) * (ONE + cost_pct / Decimal("100"))
    mutable["freight_per_unit"] = max(ZERO, dec(mutable["freight_per_unit"], ZERO) + freight_delta)
    mutable["storage_per_unit"] = max(ZERO, dec(mutable["storage_per_unit"], ZERO) + storage_delta)

    result = compute_position(mutable, contracts).payload
    if sell_pct > ZERO and result.get("current_realizable_price") is not None and not result.get("over_contracted"):
        remaining = dec(result["uncontracted_quantity"], ZERO)
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
        result["contracted_percent"] = _out(_pct(dec(result["contracted_quantity"]), dec(result["expected_production"])), Decimal("0.0001"))
        result["exposed_percent"] = _out(_pct(new_uncontracted, dec(result["expected_production"])), Decimal("0.0001"))
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
    for row in rows:
        state = str(_attr(row, "source_status", "UNAVAILABLE")).upper()
        counts[state] = counts.get(state, 0) + 1
        sources.append({
            "evidence_id": _attr(row, "evidence_id"),
            "provider": _attr(row, "provider"),
            "source_name": _attr(row, "source_name"),
            "status": state,
            "observed_at": _attr(row, "observed_at").isoformat() + "Z" if _attr(row, "observed_at") else None,
            "retrieved_at": _attr(row, "retrieved_at").isoformat() + "Z" if _attr(row, "retrieved_at") else None,
        })
    adverse = sum(counts.get(s, 0) for s in ("STALE", "UNAVAILABLE", "NOT_CONFIGURED"))
    demos = counts.get("DEMO", 0)
    if adverse:
        status, confidence = "degraded", "low" if adverse == len(rows) else "medium"
    elif demos == len(rows):
        status, confidence = "demo", "medium"
    else:
        status, confidence = "healthy", "high"
    return {"status": status, "confidence": confidence, "sources": sources, "counts": counts}
