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
    MarketContractPosition,
    MarketDataPoint,
    MarketDataPointRevision,
    MarketDataSeries,
    MarketPosition,
    MarketProviderRun,
)
from app.services.market_data_adapters import ADAPTERS, ECB_REFERENCE_CURRENCIES, SeriesPoint, SeriesProvider
from app.services.market_intelligence import ACTIVE_CONTRACT_STATUSES, MarketCalculationError, convert_price_per_unit
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


def demand_identity(adapter: SeriesProvider, selectors: Iterable[dict[str, Any]]) -> tuple[str, list[str]]:
    """Stable, bounded identity of a provider demand.

    Returns ``(sha256 key, readable labels)``. The key hashes the canonical
    (sorted, de-duplicated, key-sorted JSON) selector set, so it never collides
    through truncation however many selectors the tenant population produces;
    the labels are kept only as trace metadata.
    """
    canonical = sorted({json.dumps(selector or {}, sort_keys=True, separators=(",", ":"), default=str) for selector in selectors} or {"{}"})
    digest = hashlib.sha256(json.dumps([adapter.provider_id, canonical], separators=(",", ":")).encode()).hexdigest()
    labels = sorted({adapter.demand_key(json.loads(item)) for item in canonical})
    return f"sha256:{digest}", labels


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


def persist_points(db: Session, points: Iterable[SeriesPoint], *, provider_run_id: str | None = None) -> IngestStats:
    """Idempotently persist provider points. Does not commit.

    Existing points are loaded once per series (one query per series, not per
    point), so a 90-day ECB history or a year of CONAB weeks ingests quickly.
    """
    stats = IngestStats()
    cache: dict[str, MarketDataSeries] = {}
    by_series: dict[str, list[SeriesPoint]] = {}
    for point in points:
        stats.seen += 1
        if not (point.descriptor.licensing or {}).get("storage_allowed", True):
            continue  # licence forbids storage: evidence may only be used transiently
        by_series.setdefault(point.descriptor.series_key, []).append(point)
    for series_points in by_series.values():
        series = _series_row(db, series_points[0].descriptor, cache)
        db.flush()
        observed_times = sorted({_naive(point.observed_at) for point in series_points})
        known: dict[datetime, MarketDataPoint] = {
            row.observed_at: row
            for row in db.query(MarketDataPoint).filter(
                MarketDataPoint.series_id == series.id,
                MarketDataPoint.observed_at >= observed_times[0],
                MarketDataPoint.observed_at <= observed_times[-1],
            )
        }
        for point in series_points:
            stats.series_touched.add(series.id)
            _persist_point(db, series, point, known, stats, provider_run_id=provider_run_id)
    return stats


def _persist_point(
    db: Session,
    series: MarketDataSeries,
    point: SeriesPoint,
    known: dict[datetime, MarketDataPoint],
    stats: IngestStats,
    *,
    provider_run_id: str | None = None,
) -> None:
    observed = _naive(point.observed_at)
    digest = _content_hash(point)
    existing = known.get(observed)
    if existing is None:
        try:
            with db.begin_nested():
                row = MarketDataPoint(
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
                )
                db.add(row)
            stats.inserted += 1
            known[observed] = row  # a repeated row later in the same batch is a duplicate
        except IntegrityError:
            stats.duplicates += 1
    elif existing.content_hash == digest:
        stats.duplicates += 1
        existing.retrieved_at = _naive(point.retrieved_at)
    else:
        # Upstream correction: the point keeps the latest value for fast reads
        # and the full before/after is appended to the audit history.
        revision = int(existing.revision or 0) + 1
        new_raw = (point.raw_value or "")[:120] or None
        db.add(MarketDataPointRevision(
            point_id=existing.id,
            series_id=series.id,
            observed_at=observed,
            revision=revision,
            previous_value=existing.value,
            new_value=point.value,
            previous_raw_value=existing.raw_value,
            new_raw_value=new_raw,
            previous_source_status=existing.source_status,
            new_source_status=point.source_status,
            previous_content_hash=existing.content_hash,
            new_content_hash=digest,
            previous_retrieved_at=existing.retrieved_at,
            revised_retrieved_at=_naive(point.retrieved_at),
            provider_run_id=provider_run_id,
            upstream_ref=(point.upstream_ref or "")[:600] or None,
        ))
        existing.value = point.value
        existing.raw_value = new_raw
        existing.source_status = point.source_status
        existing.content_hash = digest
        existing.retrieved_at = _naive(point.retrieved_at)
        existing.revision = Decimal(revision)
        existing.quality_json = dict(point.quality)
        stats.revised += 1
    if series.last_observed_at is None or observed > series.last_observed_at:
        series.last_observed_at = observed
    series.last_retrieved_at = _naive(point.retrieved_at)


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
    demand_key, demand_labels = demand_identity(adapter, selectors)
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
        trace_json={"demand_labels": demand_labels[:200], "selector_count": len(demand_labels), "selectors": selectors[:50], "data_plane_version": DATA_PLANE_VERSION},
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
        stats = persist_points(db, points, provider_run_id=run.id)
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


def position_fx_currencies(position: MarketPosition, contracts: Iterable[MarketContractPosition] = ()) -> set[str]:
    """Every currency that must convert to the position's reporting currency.

    The realizable-price currency, the cost currency and the currency of every
    contract that still carries exposure (active, priced or committed): a
    USD-priced contract on a BRL-reported Brazilian position needs USD/BRL even
    when price and reporting currency are the same.
    """
    reporting = str(position.reporting_currency or "").upper()
    metadata = position.metadata_json if isinstance(position.metadata_json, dict) else {}
    currencies = {
        str(position.price_currency or position.local_currency or "").upper(),
        str(metadata.get("cost_currency") or "").upper(),
    }
    for contract in contracts:
        if str(contract.status or "active").lower() in ACTIVE_CONTRACT_STATUSES:
            currencies.add(str(contract.currency or "").upper())
    return {code for code in currencies if code and code != reporting}


def fx_demands(reporting_currency: str, foreign: set[str]) -> dict[str, dict[str, Any]]:
    """Shared FX provider demands for one reporting currency and its foreign currencies."""
    reporting = str(reporting_currency or "").upper()
    if not foreign:
        return {}
    demands: dict[str, dict[str, Any]] = {"fx_reference": {}}
    if any({code, reporting} == {"BRL", "USD"} for code in foreign):
        demands["bcb_ptax"] = {}
    return demands


def active_contracts_by_position(db: Session, positions: list[MarketPosition]) -> dict[str, list[MarketContractPosition]]:
    """Exposure-carrying contracts per position, loaded in one query, tenant-scoped."""
    if not positions:
        return {}
    rows = (
        db.query(MarketContractPosition)
        .filter(
            MarketContractPosition.position_id.in_([position.id for position in positions]),
            MarketContractPosition.status.in_(sorted(ACTIVE_CONTRACT_STATUSES)),
        )
        .all()
    )
    owners = {position.id: position.organization_id for position in positions}
    grouped: dict[str, list[MarketContractPosition]] = {}
    for row in rows:
        if owners.get(row.position_id) == row.organization_id:
            grouped.setdefault(row.position_id, []).append(row)
    return grouped


def demand_set(db: Session, *, organization_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """De-duplicated provider selectors needed by active positions.

    Hundreds of tenants holding Mato Grosso soybean positions produce one
    CONAB selector; FX is a single global demand covering price, cost and
    every exposure-carrying contract currency.
    """
    query = db.query(MarketPosition).filter(MarketPosition.status == "active")
    if organization_id:
        query = query.filter(MarketPosition.organization_id == organization_id)
    positions = query.all()
    contracts = active_contracts_by_position(db, positions)
    demands: dict[str, dict[str, dict[str, Any]]] = {}
    for position in positions:
        metadata = position.metadata_json if isinstance(position.metadata_json, dict) else {}
        pack = resolve_pack(position.country_code, position.commodity)
        selectors = position_selectors(
            pack, country_code=position.country_code, commodity=position.commodity, region=position.region, metadata=metadata,
        )
        for provider_id, selector in selectors.items():
            adapter = ADAPTERS.get(provider_id)
            if adapter is None:
                continue
            demands.setdefault(provider_id, {})[json.dumps(selector, sort_keys=True, default=str)] = selector
        foreign = position_fx_currencies(position, contracts.get(position.id, []))
        for provider_id, selector in fx_demands(str(position.reporting_currency or ""), foreign).items():
            demands.setdefault(provider_id, {})[json.dumps(selector, sort_keys=True, default=str)] = selector
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


def fx_pair_coverage(source_currency: str | None, reporting_currency: str | None) -> dict[str, bool]:
    """Which governed FX providers can convert this pair at all.

    PTAX covers USD/BRL; the ECB basket covers any two of EUR, its reference
    currencies and the EUR-pegged CFA francs. Anything else (e.g. UGX, KES)
    needs a customer-entered rate.
    """
    source = str(source_currency or "").upper()
    reporting = str(reporting_currency or "").upper()

    def ecb(code: str) -> bool:
        return code == "EUR" or code in ECB_REFERENCE_CURRENCIES or code in EUR_FIXED_PARITIES

    return {"bcb_ptax": {source, reporting} == {"USD", "BRL"}, "fx_reference": bool(source and reporting) and ecb(source) and ecb(reporting)}


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


# Fields that make two physical quotes commercially different: product,
# class, grade, variety, delivery period/point, marketing stage, price basis
# and location. Quotes are only ever aggregated when all of these are equal.
_QUOTE_METADATA_KEYS = ("quote", "product_label", "classification", "variety", "stage", "dataset")


def commercial_signature(series: MarketDataSeries) -> dict[str, Any]:
    """Explicit compatibility signature of a physical price series."""
    metadata = series.metadata_json if isinstance(series.metadata_json, dict) else {}
    return {
        "provider": series.provider,
        "commodity": series.commodity,
        "product": {key: metadata[key] for key in _QUOTE_METADATA_KEYS if metadata.get(key) not in (None, "", {})},
        "price_basis": fold(series.price_basis),
        "market": fold(series.market_name or series.region),
        "currency": series.currency,
    }


def _signature_key(series: MarketDataSeries) -> str:
    return json.dumps(commercial_signature(series), sort_keys=True, default=str)


def _candidate_summary(series: MarketDataSeries, point: MarketDataPoint, state: str, display_allowed: bool) -> dict[str, Any]:
    return {
        "series_key": series.series_key,
        "provider": series.provider,
        "market_name": series.market_name,
        "price_basis": series.price_basis,
        "signature": commercial_signature(series),
        "state": state,
        "observed_at": point.observed_at.isoformat() + "Z" if point.observed_at else None,
        "value": str(point.value) if display_allowed else None,
        "unit": series.unit,
        "currency": series.currency,
    }


def resolve_physical_price(
    db: Session,
    position: Any,
    *,
    now: datetime | None = None,
    ignore_selection: bool = False,
) -> PriceResolution:
    """Governed physical price for a position, in the position's quantity unit.

    Selection is deterministic, recorded and never blends different products:
    - a customer-selected series (``metadata.price_series_key``) is used alone;
    - otherwise an exact market match for the position's region narrows the
      candidates; candidates are grouped by ``commercial_signature`` and only
      a single homogeneous group is used (its median when the same quote is
      reported more than once);
    - several commercially different candidates (grades, classes, delivery
      periods, stages, locations) yield ``SELECTION_REQUIRED`` with the
      candidates listed, and no price is promoted.
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
        selected_key = None if ignore_selection else str(metadata.get("price_series_key") or "") or None
        for series in _physical_series(db, provider_id, selector, commodity):
            if selected_key and series.series_key != selected_key:
                continue
            point = latest_point(db, series.id)
            state, age = point_state(series, point, now)
            if point is None or state == "UNAVAILABLE":
                continue
            if not (series.licensing_json or {}).get("derived_values_allowed", True):
                continue  # licence forbids using the value in calculations
            candidates.append((series, point, state, age))
        if not candidates:
            reasons.append(f"{provider_id}:{'selected_series_unavailable' if selected_key else 'no_usable_points'}")
            continue
        region = fold(position.region)
        exact = [c for c in candidates if region and (fold(c[0].market_name) == region or fold(c[0].region) == region)]
        best_state = min((c[2] for c in candidates), key=lambda s: _STATE_RANK[s])
        pool = exact or [c for c in candidates if c[2] == best_state]
        groups: dict[str, list[tuple[MarketDataSeries, MarketDataPoint, str, int | None]]] = {}
        for candidate in pool:
            groups.setdefault(_signature_key(candidate[0]), []).append(candidate)
        if len(groups) > 1:
            # Commercially different quotes: never synthesize one price.
            listed = [
                _candidate_summary(c[0], c[1], c[2], (c[0].licensing_json or {}).get("display_allowed", True) is not False)
                for c in sorted(pool, key=lambda item: item[0].series_key)
            ]
            return PriceResolution(
                None, None, "SELECTION_REQUIRED", "selection_required", [],
                {"provider": provider_id, "candidates": listed, "data_plane_version": DATA_PLANE_VERSION},
                "heterogeneous_candidates",
            )
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
        if selected_key:
            price, chosen = normalized[0]
            method = "customer_selected_series"
            contributing = [chosen]
        elif exact and len(normalized) == 1:
            price, chosen = normalized[0]
            method = "exact_market_match"
            contributing = [chosen]
        elif len(normalized) == 1:
            price, chosen = normalized[0]
            method = "single_market"
            contributing = [chosen]
        else:
            # Same commercial signature reported more than once (one quote).
            values = sorted(value for value, _ in normalized)
            price = Decimal(str(statistics.median(values)))
            method = "median_of_identical_quotes"
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
