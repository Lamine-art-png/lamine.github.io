"""Shared market-data plane for AGRO-AI Commercial Intelligence.

GLOBAL PROVIDER INGESTION  ->  NORMALIZED SERIES/POINTS  ->  TENANT RESOLUTION

- Ingestion is independent of tenants: the demand set is the de-duplicated
  union of what active positions need, each provider runs on its own schedule,
  and each upstream fact is stored once (unique series + observation time).
- Re-ingesting the same fact is idempotent; a changed upstream value is kept as
  a tracked revision rather than a silent overwrite.
- Resolution for a tenant position reads governed persisted points. It never
  calls a provider synchronously for slow publications and never fabricates a
  value: evidence is DELAYED (fresh), STALE (older than the freshness policy
  but within the explicit last-known policy) or UNAVAILABLE (not used).
"""
from __future__ import annotations

import hashlib
import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.market_intelligence import (
    MarketDataPoint,
    MarketDataSeries,
    MarketPosition,
    MarketProviderRun,
)
from app.services.market_data_adapters import ADAPTERS, SeriesPoint, SeriesProvider
from app.services.market_intelligence import MarketCalculationError, convert_price_per_unit
from app.services.market_normalization import EUR_FIXED_PARITIES, canonical_commodity, fold
from app.services.market_packs import ROLE_PHYSICAL, position_selectors, resolve_pack

logger = logging.getLogger("agroai.market_data_plane")
DATA_PLANE_VERSION = "market-data-plane-2026.10.1"
Q10 = Decimal("0.0000000001")
# Providers whose publication is too slow for a user-facing request; they are
# refreshed only by the scheduled cycle.
SCHEDULED_ONLY = {"conab_precos"}
MAX_BACKOFF_MINUTES = 24 * 60


def _naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _content_hash(point: SeriesPoint) -> str:
    material = json.dumps(
        [point.descriptor.series_key, _naive(point.observed_at).isoformat(), str(point.value), point.source_status],
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


@dataclass
class IngestStats:
    seen: int = 0
    inserted: int = 0
    revised: int = 0
    duplicates: int = 0
    series_touched: set[str] = field(default_factory=set)


def _series_row(db: Session, descriptor: Any, cache: dict[str, MarketDataSeries]) -> MarketDataSeries:
    if descriptor.series_key in cache:
        return cache[descriptor.series_key]
    row = db.query(MarketDataSeries).filter(MarketDataSeries.series_key == descriptor.series_key).first()
    values = {
        "provider": descriptor.provider,
        "source_name": descriptor.source_name,
        "native_id": descriptor.native_id,
        "observation_type": descriptor.observation_type,
        "commodity": descriptor.commodity,
        "country_code": descriptor.country_code,
        "region": descriptor.region,
        "market_name": descriptor.market_name,
        "price_basis": descriptor.price_basis,
        "unit": descriptor.unit,
        "currency": descriptor.currency,
        "base_currency": descriptor.base_currency,
        "frequency": descriptor.frequency,
        "freshness_max_age_minutes": Decimal(descriptor.freshness_max_age_minutes),
        "last_known_max_age_minutes": Decimal(descriptor.last_known_max_age_minutes),
        "licensing_json": dict(descriptor.licensing),
        "metadata_json": dict(descriptor.metadata),
    }
    if row is None:
        try:
            with db.begin_nested():
                row = MarketDataSeries(series_key=descriptor.series_key, status="active", **values)
                db.add(row)
        except IntegrityError:
            row = db.query(MarketDataSeries).filter(MarketDataSeries.series_key == descriptor.series_key).one()
    else:
        for key, value in values.items():
            setattr(row, key, value)
    cache[descriptor.series_key] = row
    return row


def persist_points(db: Session, points: Iterable[SeriesPoint]) -> IngestStats:
    """Idempotently persist provider points. Does not commit."""
    stats = IngestStats()
    cache: dict[str, MarketDataSeries] = {}
    for point in points:
        stats.seen += 1
        if not (point.descriptor.licensing or {}).get("storage_allowed", True):
            continue  # licence forbids storage: evidence may only be used transiently
        series = _series_row(db, point.descriptor, cache)
        db.flush()
        observed = _naive(point.observed_at)
        digest = _content_hash(point)
        existing = (
            db.query(MarketDataPoint)
            .filter(MarketDataPoint.series_id == series.id, MarketDataPoint.observed_at == observed)
            .first()
        )
        if existing is None:
            try:
                with db.begin_nested():
                    db.add(MarketDataPoint(
                        series_id=series.id,
                        observed_at=observed,
                        period_start=_naive(point.period_start) if point.period_start else None,
                        period_end=_naive(point.period_end) if point.period_end else None,
                        value=point.value,
                        raw_value=(point.raw_value or "")[:120] or None,
                        source_status=point.source_status,
                        retrieved_at=_naive(point.retrieved_at),
                        content_hash=digest,
                        revision=Decimal(0),
                        upstream_ref=(point.upstream_ref or "")[:600] or None,
                        quality_json=dict(point.quality),
                    ))
                stats.inserted += 1
            except IntegrityError:
                stats.duplicates += 1
        elif existing.content_hash == digest:
            stats.duplicates += 1
            existing.retrieved_at = _naive(point.retrieved_at)
        else:
            quality = dict(existing.quality_json or {})
            revisions = list(quality.get("revisions") or [])[-9:]
            revisions.append({
                "previous_value": str(existing.value),
                "previous_retrieved_at": existing.retrieved_at.isoformat() + "Z" if existing.retrieved_at else None,
                "revised_at": _naive(point.retrieved_at).isoformat() + "Z",
            })
            existing.value = point.value
            existing.raw_value = (point.raw_value or "")[:120] or None
            existing.content_hash = digest
            existing.retrieved_at = _naive(point.retrieved_at)
            existing.revision = Decimal(int(existing.revision or 0) + 1)
            existing.quality_json = {**dict(point.quality), "revisions": revisions}
            stats.revised += 1
        stats.series_touched.add(series.id)
        if series.last_observed_at is None or observed > series.last_observed_at:
            series.last_observed_at = observed
        series.last_retrieved_at = _naive(point.retrieved_at)
    return stats


def _recent_runs(db: Session, provider_id: str, demand_key: str, limit: int = 6) -> list[MarketProviderRun]:
    return (
        db.query(MarketProviderRun)
        .filter(MarketProviderRun.provider == provider_id, MarketProviderRun.demand_key == demand_key)
        .order_by(MarketProviderRun.started_at.desc())
        .limit(limit)
        .all()
    )


def provider_due(db: Session, adapter: SeriesProvider, demand_key: str, now: datetime | None = None) -> bool:
    """Due when the last successful run is older than the refresh interval.

    Consecutive failures back off exponentially (capped at 24h) so an outage
    upstream is not hammered by every scheduled cycle.
    """
    now = _naive(now or utc_now())
    runs = _recent_runs(db, adapter.provider_id, demand_key)
    if not runs:
        return True
    last = runs[0]
    if last.status in {"ok", "partial"}:
        return now - last.started_at >= timedelta(minutes=adapter.refresh_interval_minutes)
    failures = 0
    for run in runs:
        if run.status in {"ok", "partial"}:
            break
        failures += 1
    backoff = min(adapter.refresh_interval_minutes * (2 ** max(0, failures - 1)), MAX_BACKOFF_MINUTES)
    return now - last.started_at >= timedelta(minutes=max(15, min(backoff, MAX_BACKOFF_MINUTES)))


async def ingest(
    db: Session,
    provider_id: str,
    selectors: list[dict[str, Any]],
    *,
    trigger: str = "scheduled",
    adapter: SeriesProvider | None = None,
) -> dict[str, Any]:
    """Run one provider for a batch of selectors and persist its evidence."""
    adapter = adapter or ADAPTERS.get(provider_id)
    if adapter is None:
        return {"provider": provider_id, "status": "unknown_provider"}
    demand_key = "|".join(sorted({adapter.demand_key(selector) for selector in selectors})) or adapter.demand_key({})
    demand_key = demand_key[:400]
    run = MarketProviderRun(
        provider=provider_id,
        demand_key=demand_key,
        trigger=trigger,
        status="running",
        started_at=_naive(utc_now()),
        observations_seen=Decimal(0),
        points_inserted=Decimal(0),
        points_revised=Decimal(0),
        duplicates=Decimal(0),
        trace_json={"selectors": selectors[:50], "data_plane_version": DATA_PLANE_VERSION},
    )
    if not adapter.configured():
        run.status = "not_configured"
        run.finished_at = run.started_at
        db.add(run)
        db.commit()
        return {"provider": provider_id, "status": "not_configured"}
    db.add(run)
    db.commit()
    try:
        points = await adapter.collect(selectors)
        stats = persist_points(db, points)
        run.status = "ok" if points or not selectors else "partial"
        run.observations_seen = Decimal(stats.seen)
        run.points_inserted = Decimal(stats.inserted)
        run.points_revised = Decimal(stats.revised)
        run.duplicates = Decimal(stats.duplicates)
        run.trace_json = {**run.trace_json, "series": len(stats.series_touched)}
    except Exception as exc:  # noqa: BLE001 - provider failures become UNAVAILABLE evidence, never 500s
        db.rollback()
        run = db.get(MarketProviderRun, run.id) or run
        run.status = "unavailable"
        run.error_class = exc.__class__.__name__
        logger.warning("market provider %s unavailable: %s", provider_id, exc.__class__.__name__)
    run.finished_at = _naive(utc_now())
    db.commit()
    return {
        "provider": provider_id,
        "status": run.status,
        "seen": int(run.observations_seen or 0),
        "inserted": int(run.points_inserted or 0),
        "revised": int(run.points_revised or 0),
        "duplicates": int(run.duplicates or 0),
        "error": run.error_class,
    }


def demand_set(db: Session, *, organization_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """De-duplicated provider selectors needed by active positions.

    Hundreds of tenants holding Mato Grosso soybean positions produce one
    CONAB selector; FX is a single global demand.
    """
    query = db.query(MarketPosition).filter(MarketPosition.status == "active")
    if organization_id:
        query = query.filter(MarketPosition.organization_id == organization_id)
    demands: dict[str, dict[str, dict[str, Any]]] = {}
    needs_fx = False
    needs_ptax = False
    for position in query.all():
        metadata = position.metadata_json if isinstance(position.metadata_json, dict) else {}
        pack = resolve_pack(position.country_code, position.commodity)
        selectors = position_selectors(
            pack, country_code=position.country_code, commodity=position.commodity, region=position.region, metadata=metadata,
        )
        for provider_id, selector in selectors.items():
            adapter = ADAPTERS.get(provider_id)
            if adapter is None:
                continue
            demands.setdefault(provider_id, {})[adapter.demand_key(selector)] = selector
        currencies = {str(position.reporting_currency or "").upper(), str(position.price_currency or position.local_currency or "").upper()}
        if len(currencies - {""}) > 1:
            needs_fx = True
            needs_ptax = needs_ptax or {"BRL", "USD"}.issubset(currencies)
    if needs_fx:
        demands.setdefault("fx_reference", {})["fx_reference:ecb-hist-90d"] = {}
    if needs_ptax:
        demands.setdefault("bcb_ptax", {})["bcb_ptax:USD:BRL"] = {}
    return {provider_id: list(selectors.values()) for provider_id, selectors in demands.items()}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def point_state(series: MarketDataSeries, point: MarketDataPoint | None, now: datetime | None = None) -> tuple[str, int | None]:
    """Freshness state of a persisted point: DELAYED, STALE or UNAVAILABLE."""
    if point is None:
        return "UNAVAILABLE", None
    now = _naive(now or utc_now())
    age = int((now - point.observed_at).total_seconds() // 60)
    if age <= int(series.freshness_max_age_minutes):
        return "DELAYED", age
    if age <= int(series.last_known_max_age_minutes):
        return "STALE", age
    return "UNAVAILABLE", age


def latest_point(db: Session, series_id: str, *, as_of: datetime | None = None) -> MarketDataPoint | None:
    query = db.query(MarketDataPoint).filter(MarketDataPoint.series_id == series_id)
    if as_of is not None:
        query = query.filter(MarketDataPoint.observed_at <= _naive(as_of))
    return query.order_by(MarketDataPoint.observed_at.desc()).first()


def series_history(db: Session, series_id: str, *, since: datetime) -> list[MarketDataPoint]:
    return (
        db.query(MarketDataPoint)
        .filter(MarketDataPoint.series_id == series_id, MarketDataPoint.observed_at >= _naive(since))
        .order_by(MarketDataPoint.observed_at.asc())
        .all()
    )


def evidence_record(series: MarketDataSeries, point: MarketDataPoint, state: str, age: int | None, *, role: str) -> dict[str, Any]:
    licensing = dict(series.licensing_json or {})
    return {
        "role": role,
        "series_id": series.id,
        "point_id": point.id,
        "series_key": series.series_key,
        "provider": series.provider,
        "source_name": series.source_name,
        "native_id": series.native_id,
        "observation_type": series.observation_type,
        "commodity": series.commodity,
        "country_code": series.country_code,
        "region": series.region,
        "market_name": series.market_name,
        "price_basis": series.price_basis,
        "unit": series.unit,
        "currency": series.currency,
        "base_currency": series.base_currency,
        "value": str(point.value),
        "raw_value": point.raw_value,
        "observed_at": point.observed_at.isoformat() + "Z",
        "retrieved_at": point.retrieved_at.isoformat() + "Z",
        "age_minutes": age,
        "freshness_max_age_minutes": int(series.freshness_max_age_minutes),
        "last_known_max_age_minutes": int(series.last_known_max_age_minutes),
        "state": state,
        "revision": int(point.revision or 0),
        "upstream_ref": point.upstream_ref,
        "licensing": licensing,
        "automated": True,
    }


_STATE_RANK = {"DELAYED": 0, "STALE": 1, "UNAVAILABLE": 2}


@dataclass
class FxResolution:
    rate: Decimal | None
    state: str
    method: str
    components: list[dict[str, Any]]


def _per_eur(db: Session, currency: str, now: datetime) -> tuple[Decimal | None, str, list[dict[str, Any]]]:
    """Currency units per one EUR from ECB (or exact CFA parity)."""
    if currency == "EUR":
        return Decimal(1), "DELAYED", []
    if currency in EUR_FIXED_PARITIES:
        return EUR_FIXED_PARITIES[currency], "DELAYED", [{
            "role": "fx_rate", "provider": "fixed_parity", "source_name": "CFA franc fixed parity (655.957 per EUR)",
            "value": str(EUR_FIXED_PARITIES[currency]), "unit": f"{currency}/EUR", "state": "DELAYED", "automated": True,
            "licensing": {"display_allowed": True, "derived_values_allowed": True}, "method": "legal_fixed_parity",
        }]
    series = db.query(MarketDataSeries).filter(MarketDataSeries.series_key == f"fx_reference:EUR:{currency}").first()
    if series is None:
        return None, "UNAVAILABLE", []
    point = latest_point(db, series.id)
    state, age = point_state(series, point, now)
    if point is None or state == "UNAVAILABLE":
        return None, "UNAVAILABLE", []
    return Decimal(point.value), state, [evidence_record(series, point, state, age, role="fx_rate")]


def resolve_fx(db: Session, source_currency: str, reporting_currency: str, *, now: datetime | None = None) -> FxResolution:
    """Reporting-currency units per one unit of source currency."""
    now = now or utc_now()
    source = str(source_currency or "").upper()
    reporting = str(reporting_currency or "").upper()
    if not source or not reporting:
        return FxResolution(None, "UNAVAILABLE", "missing_currency", [])
    if source == reporting:
        return FxResolution(Decimal(1), "DELAYED", "identity", [])
    candidates: list[FxResolution] = []
    if {source, reporting} == {"USD", "BRL"}:
        series = db.query(MarketDataSeries).filter(MarketDataSeries.series_key == "bcb_ptax:USD:BRL").first()
        point = latest_point(db, series.id) if series else None
        if series is not None and point is not None:
            state, age = point_state(series, point, now)
            if state != "UNAVAILABLE":
                brl_per_usd = Decimal(point.value)
                rate = brl_per_usd if source == "USD" else (Decimal(1) / brl_per_usd)
                candidates.append(FxResolution(rate.quantize(Q10, rounding=ROUND_HALF_UP), state, "bcb_ptax_official",
                                               [evidence_record(series, point, state, age, role="fx_rate")]))
    source_per_eur, source_state, source_evidence = _per_eur(db, source, now)
    reporting_per_eur, reporting_state, reporting_evidence = _per_eur(db, reporting, now)
    if source_per_eur and reporting_per_eur:
        state = max(source_state, reporting_state, key=lambda item: _STATE_RANK[item])
        candidates.append(FxResolution(
            (reporting_per_eur / source_per_eur).quantize(Q10, rounding=ROUND_HALF_UP),
            state,
            "ecb_cross_via_eur",
            source_evidence + reporting_evidence,
        ))
    if not candidates:
        return FxResolution(None, "UNAVAILABLE", "no_governed_source", [])
    return min(candidates, key=lambda item: _STATE_RANK[item.state])


@dataclass
class PriceResolution:
    price: Decimal | None
    currency: str | None
    state: str
    method: str
    evidence: list[dict[str, Any]]
    trace: dict[str, Any]
    reason: str | None = None


def _physical_series(db: Session, provider_id: str, selector: dict[str, Any], commodity: str) -> list[MarketDataSeries]:
    query = db.query(MarketDataSeries).filter(
        MarketDataSeries.provider == provider_id,
        MarketDataSeries.observation_type == "physical_price",
        MarketDataSeries.commodity == commodity,
        MarketDataSeries.status == "active",
    )
    if provider_id == "conab_precos":
        query = query.filter(MarketDataSeries.region == str(selector.get("uf") or "").upper())
    elif provider_id == "eu_agrifood":
        query = query.filter(MarketDataSeries.country_code == str(selector.get("member_state") or "").upper())
    elif provider_id == "india_agmarknet":
        query = query.filter(MarketDataSeries.country_code == "IN")
    elif provider_id == "usda_mymarketnews":
        query = query.filter(MarketDataSeries.country_code == "US")
    rows = query.all()
    if provider_id == "india_agmarknet" and selector.get("state"):
        rows = [row for row in rows if fold(row.region) == fold(selector.get("state"))]
    if provider_id == "usda_mymarketnews" and selector.get("report_slug"):
        rows = [row for row in rows if (row.metadata_json or {}).get("report_slug") == str(selector["report_slug"])]
    return rows


def resolve_physical_price(
    db: Session,
    position: Any,
    *,
    now: datetime | None = None,
) -> PriceResolution:
    """Governed physical price for a position, in the position's quantity unit.

    Selection is deterministic and recorded: an exact market match for the
    position's region when one exists; otherwise the median of the latest
    fresh points across the pack's markets (each contributing point listed).
    """
    now = now or utc_now()
    metadata = position.metadata_json if isinstance(getattr(position, "metadata_json", None), dict) else {}
    commodity = canonical_commodity(position.commodity)
    pack = resolve_pack(position.country_code, position.commodity)
    selectors = position_selectors(pack, country_code=position.country_code, commodity=position.commodity, region=position.region, metadata=metadata)
    physical_providers = [slot.provider_id for slot in pack.evidence if slot.role == ROLE_PHYSICAL]
    if commodity is None:
        return PriceResolution(None, None, "UNAVAILABLE", "commodity_not_recognised", [], {}, "commodity_not_recognised")
    reasons: list[str] = []
    for provider_id in physical_providers:
        selector = selectors.get(provider_id)
        if selector is None:
            reasons.append(f"{provider_id}:no_selector")
            continue
        candidates: list[tuple[MarketDataSeries, MarketDataPoint, str, int | None]] = []
        for series in _physical_series(db, provider_id, selector, commodity):
            point = latest_point(db, series.id)
            state, age = point_state(series, point, now)
            if point is None or state == "UNAVAILABLE":
                continue
            if not (series.licensing_json or {}).get("derived_values_allowed", True):
                continue  # licence forbids using the value in calculations
            candidates.append((series, point, state, age))
        if not candidates:
            reasons.append(f"{provider_id}:no_usable_points")
            continue
        region = fold(position.region)
        exact = [c for c in candidates if region and (fold(c[0].market_name) == region or fold(c[0].region) == region)]
        best_state = min((c[2] for c in candidates), key=lambda s: _STATE_RANK[s])
        pool = exact or [c for c in candidates if c[2] == best_state]
        # Normalize every candidate into the position's unit before comparing.
        normalized: list[tuple[Decimal, tuple[MarketDataSeries, MarketDataPoint, str, int | None]]] = []
        currencies = {c[0].currency for c in pool}
        if len(currencies) != 1:
            reasons.append(f"{provider_id}:mixed_currencies")
            continue
        for candidate in pool:
            series = candidate[0]
            try:
                converted = convert_price_per_unit(candidate[1].value, series.unit, position.quantity_unit, commodity)
            except MarketCalculationError:
                continue
            normalized.append((converted, candidate))
        if not normalized:
            reasons.append(f"{provider_id}:unit_not_convertible")
            continue
        if exact and len(normalized) == 1:
            price, chosen = normalized[0]
            method = "exact_market_match"
            contributing = [chosen]
        elif len(normalized) == 1:
            price, chosen = normalized[0]
            method = "single_market"
            contributing = [chosen]
        else:
            values = sorted(value for value, _ in normalized)
            price = Decimal(str(statistics.median(values)))
            method = "median_of_markets"
            contributing = [c for _, c in normalized]
        state = max((c[2] for c in contributing), key=lambda s: _STATE_RANK[s])
        evidence = [evidence_record(c[0], c[1], c[2], c[3], role="physical_price") for c in contributing]
        trace = {
            "provider": provider_id,
            "method": method,
            "target_unit": position.quantity_unit,
            "source_units": sorted({c[0].unit for c in contributing}),
            "contributing_points": len(contributing),
            "normalization": "convert_price_per_unit (commodity-specific mass conversion)",
            "data_plane_version": DATA_PLANE_VERSION,
        }
        return PriceResolution(price.quantize(Decimal("0.00000001")), currencies.pop(), state, method, evidence, trace)
    return PriceResolution(None, None, "UNAVAILABLE", "no_governed_physical_price", [], {"attempts": reasons}, ";".join(reasons) or "no_physical_provider")


def provider_health(db: Session) -> dict[str, Any]:
    """Latest run and series freshness per provider for Data Health / admin."""
    result: dict[str, Any] = {}
    now = _naive(utc_now())
    for provider_id, adapter in ADAPTERS.items():
        last = (
            db.query(MarketProviderRun)
            .filter(MarketProviderRun.provider == provider_id)
            .order_by(MarketProviderRun.started_at.desc())
            .first()
        )
        series_count, newest = (
            db.query(func.count(MarketDataSeries.id), func.max(MarketDataSeries.last_observed_at))
            .filter(MarketDataSeries.provider == provider_id)
            .one()
        )
        result[provider_id] = {
            **adapter.catalog(),
            "last_run": {
                "status": last.status,
                "started_at": last.started_at.isoformat() + "Z",
                "inserted": int(last.points_inserted or 0),
                "duplicates": int(last.duplicates or 0),
                "error_class": last.error_class,
            } if last else None,
            "series_count": int(series_count or 0),
            "newest_observation_at": newest.isoformat() + "Z" if newest else None,
            "newest_observation_age_minutes": int((now - newest).total_seconds() // 60) if newest else None,
        }
    return result
