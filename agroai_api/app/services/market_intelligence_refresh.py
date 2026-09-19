"""Production refresh orchestration for Market Intelligence.

This module connects provider observations to tenant-scoped commercial
positions. It updates only fields that can be reconciled safely and stores all
upstream evidence with provenance before any derived economics are recomputed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.market_intelligence import MarketContractPosition, MarketObservation, MarketPosition
from app.services.market_data_providers import MarketDataRequest, ProviderObservation, registry


def _metadata(position: MarketPosition) -> dict[str, Any]:
    value = position.metadata_json or {}
    return value if isinstance(value, dict) else {}


def _norm(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _canonical_quantity_unit(value: str | None) -> str | None:
    text = _norm(value)
    aliases = {
        "bu": "bushel",
        "bushel": "bushel",
        "bushels": "bushel",
        "lb": "pound",
        "lbs": "pound",
        "pound": "pound",
        "pounds": "pound",
        "kg": "kg",
        "kilogram": "kg",
        "kilograms": "kg",
        "t": "tonne",
        "ton": "tonne",
        "tons": "tonne",
        "tonne": "tonne",
        "tonnes": "tonne",
        "metric ton": "tonne",
        "metric tons": "tonne",
        "metric tonne": "tonne",
        "metric tonnes": "tonne",
    }
    return aliases.get(text)


def _quantity_unit_from_price_unit(value: str | None) -> str | None:
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


def _select_unambiguous_latest_price(
    observations: list[ProviderObservation],
) -> tuple[ProviderObservation | None, str | None]:
    if not observations:
        return None, "no_compatible_observation"
    latest_date = max(item.observed_at.date() for item in observations)
    latest_rows = [item for item in observations if item.observed_at.date() == latest_date]
    signatures = {
        (item.value, _norm(item.unit), str(item.currency or "").upper())
        for item in latest_rows
    }
    if len(signatures) != 1:
        return None, "ambiguous_latest_market_observations"
    return max(latest_rows, key=lambda item: item.observed_at), None


def _scoped_evidence_id(position_id: str, upstream_evidence_id: str) -> str:
    """Keep provider evidence independently attached to every commercial position.

    Provider evidence ids describe an upstream fact (for example one ECB pair/day)
    and can legitimately be shared by many positions. The persistence uniqueness
    contract is organization + evidence_id, so prefixing with the position id
    prevents a later refresh from moving a shared observation away from an earlier
    position while retaining the original upstream id in metadata.
    """
    return f"{position_id}:{upstream_evidence_id}"


def _upsert_observation(db: Session, organization_id: str, position_id: str, item: ProviderObservation) -> MarketObservation:
    evidence_id = _scoped_evidence_id(position_id, item.evidence_id)
    row = (
        db.query(MarketObservation)
        .filter(
            MarketObservation.organization_id == organization_id,
            MarketObservation.evidence_id == evidence_id,
        )
        .first()
    )
    values = {
        "position_id": position_id,
        "observation_type": item.observation_type,
        "provider": item.provider,
        "source_name": item.source_name,
        "source_status": item.source_status,
        "value": item.value,
        "unit": item.unit,
        "currency": item.currency,
        "observed_at": item.observed_at.astimezone(timezone.utc).replace(tzinfo=None) if item.observed_at.tzinfo else item.observed_at,
        "retrieved_at": item.retrieved_at.astimezone(timezone.utc).replace(tzinfo=None) if item.retrieved_at.tzinfo else item.retrieved_at,
        "delay_minutes": item.delay_minutes,
        "quality_json": item.quality,
        "licensing_json": item.licensing,
        "metadata_json": {**item.metadata, "upstream_evidence_id": item.evidence_id},
    }
    if row is None:
        row = MarketObservation(
            organization_id=organization_id,
            evidence_id=evidence_id,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


async def _fetch_fx_rate(
    db: Session,
    *,
    organization_id: str,
    position: MarketPosition,
    source_currency: str,
    reporting_currency: str,
    metadata: dict[str, Any],
) -> tuple[Decimal | None, int, str | None]:
    source = str(source_currency or "").upper()
    reporting = str(reporting_currency or "").upper()
    if not source or not reporting:
        return None, 0, "missing_currency"
    if source == reporting:
        return Decimal("1"), 0, None
    provider = registry.get("fx_reference")
    if provider is None:
        return None, 0, "provider_not_configured"
    request = MarketDataRequest(
        commodity=position.commodity,
        country_code=position.country_code,
        region=position.region,
        currency=source,
        market_structure=position.market_structure,
        source_currency=source,
        reporting_currency=reporting,
        metadata=metadata,
    )
    try:
        rows = await provider.observations(request)
    except Exception as exc:
        return None, 0, exc.__class__.__name__
    written = 0
    positive: list[ProviderObservation] = []
    for item in rows:
        _upsert_observation(db, organization_id, position.id, item)
        written += 1
        if item.value is not None and item.value > 0:
            positive.append(item)
    if not positive:
        return None, written, "no_matching_observation"
    latest = max(positive, key=lambda item: item.observed_at)
    return latest.value, written, None


async def refresh_position_market_data(
    db: Session,
    position: MarketPosition,
    *,
    contracts: list[MarketContractPosition] | None = None,
) -> dict[str, Any]:
    organization_id = str(position.organization_id)
    contracts = contracts if contracts is not None else (
        db.query(MarketContractPosition)
        .filter(
            MarketContractPosition.organization_id == organization_id,
            MarketContractPosition.position_id == position.id,
        )
        .all()
    )
    metadata = _metadata(position)
    provider_results: dict[str, Any] = {}
    observations_written = 0
    position_updates: list[str] = []
    contract_updates = 0

    # 1) Daily reference FX. Fetch every distinct commercial source currency
    # against the position reporting currency and reconcile both current price
    # and contract rows. A missing new rate never inherits a stale old rate.
    reporting = str(position.reporting_currency or "").upper()
    source_currencies = {
        str(position.price_currency or position.local_currency or reporting).upper(),
        *{str(contract.currency or reporting).upper() for contract in contracts},
    }
    fx_by_source: dict[str, Decimal] = {}
    fx_errors: list[str] = []
    for source_currency in sorted(source_currencies):
        rate, written, error = await _fetch_fx_rate(
            db,
            organization_id=organization_id,
            position=position,
            source_currency=source_currency,
            reporting_currency=reporting,
            metadata=metadata,
        )
        observations_written += written
        if rate is not None:
            fx_by_source[source_currency] = rate
        if error:
            fx_errors.append(f"{source_currency}:{error}")
    provider_results["fx_reference"] = (
        {"status": "DEGRADED", "pairs": sorted(fx_by_source), "errors": fx_errors}
        if fx_errors
        else {"status": "ok", "pairs": sorted(fx_by_source)}
    )

    price_currency = str(position.price_currency or position.local_currency or reporting).upper()
    if price_currency == reporting:
        if position.fx_rate_to_reporting is not None:
            position.fx_rate_to_reporting = None
            position_updates.append("fx_rate_to_reporting")
    elif price_currency in fx_by_source:
        position.fx_rate_to_reporting = fx_by_source[price_currency]
        position_updates.append("fx_rate_to_reporting")
    elif position.fx_rate_to_reporting is not None:
        # Existing rate is for a currency pair we could no longer verify.
        position.fx_rate_to_reporting = None
        position_updates.append("fx_rate_to_reporting")

    for contract in contracts:
        source = str(contract.currency or reporting).upper()
        if source == reporting:
            if contract.fx_rate_to_reporting is not None:
                contract.fx_rate_to_reporting = None
                contract_updates += 1
        elif source in fx_by_source:
            contract.fx_rate_to_reporting = fx_by_source[source]
            contract_updates += 1
        elif contract.fx_rate_to_reporting is not None:
            contract.fx_rate_to_reporting = None
            contract_updates += 1

    # 2) USDA AMS cash-market observations for configured U.S. positions.
    # Promote an upstream price only when its quantity unit exactly reconciles.
    usda_provider = registry.get("usda_mymarketnews")
    if usda_provider is not None and str(position.country_code or "").upper() == "US":
        request = MarketDataRequest(
            commodity=position.commodity,
            country_code=position.country_code,
            region=position.region,
            currency="USD",
            market_structure=position.market_structure,
            reporting_currency=reporting,
            metadata=metadata,
        )
        try:
            provider_state = await usda_provider.status()
        except Exception as exc:
            provider_state = {"status": "UNAVAILABLE", "error": exc.__class__.__name__}
        try:
            rows = await usda_provider.observations(request)
            compatible: list[ProviderObservation] = []
            for item in rows:
                _upsert_observation(db, organization_id, position.id, item)
                observations_written += 1
                observed_unit = _quantity_unit_from_price_unit(item.unit)
                if (
                    item.observation_type == "cash_price"
                    and item.value is not None
                    and item.currency
                    and observed_unit == _canonical_quantity_unit(position.quantity_unit)
                ):
                    compatible.append(item)
            latest, selection_error = _select_unambiguous_latest_price(compatible)
            if latest is not None:
                promoted_currency = str(latest.currency or "").upper()
                position.current_realizable_price = latest.value
                position.price_currency = promoted_currency
                position_updates.extend(["current_realizable_price", "price_currency"])

                if promoted_currency == reporting:
                    position.fx_rate_to_reporting = None
                    position_updates.append("fx_rate_to_reporting")
                else:
                    rate = fx_by_source.get(promoted_currency)
                    if rate is None:
                        rate, written, error = await _fetch_fx_rate(
                            db,
                            organization_id=organization_id,
                            position=position,
                            source_currency=promoted_currency,
                            reporting_currency=reporting,
                            metadata=metadata,
                        )
                        observations_written += written
                        if rate is not None:
                            fx_by_source[promoted_currency] = rate
                        if error:
                            fx_errors.append(f"{promoted_currency}:{error}")
                    # Never carry an FX rate that belonged to the previous price
                    # currency into a newly promoted upstream price.
                    position.fx_rate_to_reporting = rate
                    position_updates.append("fx_rate_to_reporting")

                provider_results["fx_reference"] = (
                    {"status": "DEGRADED", "pairs": sorted(fx_by_source), "errors": sorted(set(fx_errors))}
                    if fx_errors
                    else {"status": "ok", "pairs": sorted(fx_by_source)}
                )
            if str(provider_state.get("status") or "").upper() == "NOT_CONFIGURED":
                provider_results["usda_mymarketnews"] = {
                    **provider_state,
                    "observation_count": 0,
                    "promoted_to_position": False,
                }
            elif selection_error == "ambiguous_latest_market_observations":
                provider_results["usda_mymarketnews"] = {
                    "status": "REVIEW_REQUIRED",
                    "reason": selection_error,
                    "observation_count": len(rows),
                    "compatible_observation_count": len(compatible),
                    "promoted_to_position": False,
                }
            else:
                provider_results["usda_mymarketnews"] = {
                    "status": "ok" if rows else "no_matching_observation",
                    "observation_count": len(rows),
                    "promoted_to_position": latest is not None,
                }
        except Exception as exc:
            provider_results["usda_mymarketnews"] = {
                "status": "UNAVAILABLE",
                "error": exc.__class__.__name__,
            }

    position.updated_at = datetime.utcnow()
    db.commit()
    return {
        "position_id": position.id,
        "refreshed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "observations_written": observations_written,
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
    results: list[dict[str, Any]] = []
    for position in positions:
        results.append(await refresh_position_market_data(db, position))
    return {
        "organization_id": organization_id,
        "position_count": len(positions),
        "results": results,
    }
