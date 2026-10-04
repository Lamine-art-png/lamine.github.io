"""Commercial Intelligence API: home, onboarding, provenance, risk, alerts.

Every route inherits the Market Intelligence release gate. Reads and writes
are organization-scoped by the authenticated context; ids from another
organization resolve to 404. Shared market evidence is global, but a tenant
only ever sees it projected through its own positions and licensing flags.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.api.v1.market_intelligence import (
    ADMIN_ROLES,
    WRITE_ROLES,
    _contracts,
    _org_id,
    _position,
    _position_payload,
    _require_write,
    enforce_market_intelligence_release,
)
from app.db.base import get_db
from app.models.market_intelligence import (
    MarketContractPosition,
    MarketDecisionJournalEntry,
    MarketMaterialityEvent,
    MarketObservation,
    MarketPosition,
    MarketPositionFieldLink,
)
from app.models.saas import ManagedEntity
from app.services import market_data_plane as plane
from app.services.market_data_adapters import ADAPTERS
from app.services.market_intelligence import (
    ACTIVE_CONTRACT_STATUSES,
    CALCULATION_VERSION,
    MarketCalculationError,
    apply_display_policy,
    compute_position,
    convert_quantity,
    redact_reasons,
    redact_scenario,
    scenario_position,
)
from app.services.market_intelligence_refresh import refresh_position_market_data
from app.services.market_materiality import DEGRADED_STATES, METHODOLOGY_VERSION, evaluate_position, event_payload, evidence_states
from app.services.market_normalization import canonical_unit, validate_country_code, validate_currency_code
from app.services.market_packs import catalog as pack_catalog, infer_onboarding, resolve_pack
from app.services.market_risk import position_risk

router = APIRouter(
    prefix="/market-intelligence",
    tags=["market-intelligence"],
    dependencies=[Depends(enforce_market_intelligence_release)],
)

ACRE_IN_HECTARES = Decimal("0.40468564224")
FIELD_ENTITY_TYPES = ("platform_field",)
POLICY = {"scope": "commercial_decision_support", "trade_execution": False, "personalized_derivatives_instructions": False}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Commercial Intelligence Home
# ---------------------------------------------------------------------------


@router.get("/home")
def commercial_home(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Answers first: is anything materially affecting my business?

    Core economics come from the deterministic engine only; no model call.
    """
    org_id = _org_id(ctx)
    rows = (
        db.query(MarketPosition)
        .filter(MarketPosition.organization_id == org_id, MarketPosition.status == "active")
        .order_by(MarketPosition.country_code.asc(), MarketPosition.commodity.asc(), MarketPosition.season.asc())
        .all()
    )
    ids = [row.id for row in rows]
    contracts_by_position: dict[str, list[MarketContractPosition]] = defaultdict(list)
    if ids:
        for contract in db.query(MarketContractPosition).filter(
            MarketContractPosition.organization_id == org_id, MarketContractPosition.position_id.in_(ids)
        ):
            contracts_by_position[contract.position_id].append(contract)
    positions: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload, _ = apply_display_policy(compute_position(row, contracts_by_position[row.id]).payload, None, row)
        except MarketCalculationError as exc:
            payload = {"position_id": row.id, "name": row.name, "error": str(exc), "error_code": "calculation_error"}
        states = evidence_states(db, row, contracts_by_position[row.id])
        payload["evidence_states"] = states
        payload["price_state"] = states["price"]
        payload["fx_state"] = states["fx"]
        payload["pack_id"] = resolve_pack(row.country_code, row.commodity).pack_id
        positions.append(payload)

    events = (
        db.query(MarketMaterialityEvent)
        .filter(MarketMaterialityEvent.organization_id == org_id, MarketMaterialityEvent.status == "open")
        .order_by(MarketMaterialityEvent.created_at.desc())
        .limit(50)
        .all()
    )
    names = {row.id: row.name for row in rows}
    level_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    material = sorted(
        (event_payload(event) | {"position_name": names.get(event.position_id)} for event in events if event.position_id in names),
        key=lambda item: (level_rank.get(item["level"], 9), item["created_at"] or ""),
    )

    totals: dict[str, dict[str, Any]] = {}
    for item in positions:
        currency = str(item.get("reporting_currency") or "")
        if not currency:
            continue
        bucket = totals.setdefault(currency, {"currency": currency, "locked_revenue": Decimal(0), "exposed_revenue": Decimal(0),
                                              "projected_margin": Decimal(0), "positions": 0, "complete": 0})
        bucket["positions"] += 1
        if item.get("locked_revenue") is not None:
            bucket["locked_revenue"] += Decimal(item["locked_revenue"])
        if item.get("exposed_revenue") is not None:
            bucket["exposed_revenue"] += Decimal(item["exposed_revenue"])
        if item.get("projected_margin") is not None:
            bucket["projected_margin"] += Decimal(item["projected_margin"])
            bucket["complete"] += 1
    portfolio = [
        {
            "currency": bucket["currency"],
            "positions": bucket["positions"],
            "locked_revenue": format(bucket["locked_revenue"].quantize(Decimal("0.01")), "f"),
            "exposed_revenue": format(bucket["exposed_revenue"].quantize(Decimal("0.01")), "f"),
            "projected_margin": format(bucket["projected_margin"].quantize(Decimal("0.01")), "f") if bucket["complete"] == bucket["positions"] else None,
            "margin_partial": bucket["complete"] != bucket["positions"],
        }
        for bucket in sorted(totals.values(), key=lambda b: b["currency"])
    ]

    horizon = datetime.utcnow() + timedelta(days=60)
    deadlines = [
        {
            "contract_id": contract.id,
            "position_id": contract.position_id,
            "position_name": names.get(contract.position_id),
            "contract_code": contract.contract_code,
            "buyer": contract.buyer,
            "quantity": format(contract.quantity, "f"),
            "quantity_unit": contract.quantity_unit,
            "delivery_start": _iso(contract.delivery_start),
            "delivery_end": _iso(contract.delivery_end),
        }
        for contracts in contracts_by_position.values()
        for contract in contracts
        if str(contract.status).lower() in ACTIVE_CONTRACT_STATUSES
        and contract.delivery_start is not None and datetime.utcnow() - timedelta(days=1) <= contract.delivery_start <= horizon
    ]
    deadlines.sort(key=lambda item: item["delivery_start"] or "")

    stale = []
    for item in positions:
        degraded = {key: state for key, state in (item.get("evidence_states") or {}).items() if state in DEGRADED_STATES}
        if degraded:
            stale.append({
                "position_id": item.get("position_id"),
                "name": item.get("name"),
                "price_state": item.get("price_state"),
                "fx_state": item.get("fx_state"),
                "degraded_evidence": degraded,
            })
    urgent = [m for m in material if m["level"] in {"HIGH", "CRITICAL"}]
    return {
        "module": "commercial_intelligence",
        "calculation_version": CALCULATION_VERSION,
        "materiality_methodology_version": METHODOLOGY_VERSION,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "status": "attention" if urgent else ("review" if material or stale else "steady"),
        "material_changes": material[:10],
        "material_change_count": len(material),
        "portfolio_by_reporting_currency": portfolio,
        "positions": positions,
        "deadlines": deadlines[:10],
        "data_health": {
            "positions_with_stale_or_missing_evidence": stale,
            "complete_positions": sum(1 for item in positions if item.get("data_complete")),
            "total_positions": len(positions),
        },
        "onboarding_required": not positions,
        "policy": POLICY,
    }


# ---------------------------------------------------------------------------
# Onboarding in customer language
# ---------------------------------------------------------------------------


class InferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crop: str = Field(min_length=1, max_length=120)
    country_code: str = Field(min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=160)
    reporting_currency: str | None = Field(default=None, min_length=3, max_length=3)
    local_currency: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("country_code")
    @classmethod
    def country(cls, value: str) -> str:
        return validate_country_code(value)

    @field_validator("reporting_currency", "local_currency")
    @classmethod
    def currency(cls, value: str | None) -> str | None:
        return validate_currency_code(value) if value is not None else None


def _provider_availability(plan: list[dict[str, Any]], *, local_currency: str | None, reporting_currency: str | None) -> list[dict[str, Any]]:
    """Real status per evidence slot. FX slots are judged for the actual pair:
    a configured provider that does not cover it (e.g. ECB for UGX) is
    NOT_COVERED, so the portal asks for the customer's own rate."""
    coverage = plane.fx_pair_coverage(local_currency, reporting_currency)
    same_currency = bool(local_currency) and str(local_currency).upper() == str(reporting_currency or "").upper()
    result = []
    for slot in plan:
        adapter = ADAPTERS.get(slot["provider_id"])
        status = adapter.status() if adapter else "NOT_CONFIGURED"
        if slot["role"] == "fx_rate":
            if same_currency:
                status = "NOT_REQUIRED"
            elif not coverage.get(slot["provider_id"], False):
                status = "NOT_COVERED"
        result.append({**slot, "status": status})
    return result


@router.get("/market-packs")
def market_packs(ctx: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
    _org_id(ctx)
    return {"packs": pack_catalog()}


@router.post("/onboarding/infer")
def onboarding_infer(payload: InferRequest, ctx: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
    _org_id(ctx)
    inferred = infer_onboarding(crop=payload.crop, country_code=payload.country_code, region=payload.region,
                                reporting_currency=payload.reporting_currency, local_currency=payload.local_currency)
    inferred["evidence_plan"] = _provider_availability(inferred["evidence_plan"], local_currency=inferred["local_currency"], reporting_currency=inferred["reporting_currency"])
    return inferred


def _supported_unit(value: str | None) -> str | None:
    """Canonical quantity unit, or a validation error (never a NULL column)."""
    if value is None or not str(value).strip():
        return None
    unit = canonical_unit(value)
    if unit is None:
        raise ValueError("unit_not_supported")
    return unit


class OnboardingContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buyer: str | None = Field(default=None, max_length=240)
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    quantity_unit: str | None = Field(default=None, max_length=40)
    delivery_start: datetime | None = None
    delivery_end: datetime | None = None

    @field_validator("currency")
    @classmethod
    def contract_currency(cls, value: str | None) -> str | None:
        return validate_currency_code(value) if value is not None else None

    @field_validator("quantity_unit")
    @classmethod
    def contract_unit(cls, value: str | None) -> str | None:
        return _supported_unit(value)


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crop: str = Field(min_length=1, max_length=120)
    country_code: str = Field(min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=160)
    season: str = Field(min_length=1, max_length=80)
    name: str | None = Field(default=None, max_length=200)
    quantity_unit: str | None = Field(default=None, max_length=40)
    expected_production: Decimal = Field(ge=0)
    inventory_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    inventory_cost_per_unit: Decimal | None = Field(default=None, ge=0)
    production_cost_per_unit: Decimal | None = Field(default=None, ge=0)
    reporting_currency: str | None = Field(default=None, min_length=3, max_length=3)
    # The currency the operation sells and pays costs in; required where the
    # country has several tender currencies.
    local_currency: str | None = Field(default=None, min_length=3, max_length=3)
    local_price: Decimal | None = Field(default=None, ge=0)
    local_price_currency: str | None = Field(default=None, min_length=3, max_length=3)
    fx_rate_to_reporting: Decimal | None = Field(default=None, gt=0)
    freight_per_unit: Decimal = Field(default=Decimal("0"), ge=0)
    storage_per_unit: Decimal = Field(default=Decimal("0"), ge=0)
    contracts: list[OnboardingContract] = Field(default_factory=list, max_length=50)
    field_ids: list[str] = Field(default_factory=list, max_length=200)
    workspace_id: str | None = Field(default=None, max_length=120)

    @field_validator("country_code")
    @classmethod
    def country(cls, value: str) -> str:
        return validate_country_code(value)

    @field_validator("quantity_unit")
    @classmethod
    def position_unit(cls, value: str | None) -> str | None:
        return _supported_unit(value)

    @field_validator("reporting_currency", "local_price_currency", "local_currency")
    @classmethod
    def currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_currency_code(value)


def _org_fields(db: Session, org_id: str, field_ids: list[str]) -> list[ManagedEntity]:
    if not field_ids:
        return []
    rows = (
        db.query(ManagedEntity)
        .filter(
            ManagedEntity.organization_id == org_id,
            ManagedEntity.id.in_(field_ids),
            ManagedEntity.entity_type.in_(FIELD_ENTITY_TYPES),
            ManagedEntity.status == "active",
        )
        .all()
    )
    if len({row.id for row in rows}) != len(set(field_ids)):
        raise HTTPException(status_code=404, detail="Field not found")
    return rows


def _field_operational(row: ManagedEntity) -> bool:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    return not metadata.get("synthetic") and metadata.get("data_class") != "simulated_or_evaluation"


@router.post("/onboarding", status_code=status.HTTP_201_CREATED)
async def onboarding_create(payload: OnboardingRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Create a commercial position from plain answers; AGRO-AI infers the rest."""
    _require_write(ctx)
    org_id = _org_id(ctx)
    inferred = infer_onboarding(crop=payload.crop, country_code=payload.country_code, region=payload.region,
                                reporting_currency=payload.reporting_currency, local_currency=payload.local_currency)
    unit = canonical_unit(payload.quantity_unit) if payload.quantity_unit else inferred["quantity_unit"]
    if unit is None:
        raise HTTPException(status_code=422, detail={"code": "unit_not_supported", "message": "Choose a supported quantity unit."})
    if "local_currency_ambiguous" in inferred["warnings"]:
        # Never assume which of several tender currencies the operation uses.
        raise HTTPException(status_code=422, detail={"code": "local_currency_required", "options": inferred["local_currency_options"],
                                                     "message": "Choose the currency your operation sells and pays costs in."})
    local_currency = inferred["local_currency"] or payload.local_price_currency or inferred["reporting_currency"]
    fields = _org_fields(db, org_id, payload.field_ids)
    if payload.workspace_id:
        from app.models.saas import Workspace

        if db.query(Workspace.id).filter(Workspace.id == payload.workspace_id, Workspace.organization_id == org_id).first() is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
    metadata: dict[str, Any] = {
        "input_source": "customer_onboarding",
        "pack_id": inferred["pack_id"],
        "price_policy": "manual" if payload.local_price is not None else "automatic",
    }
    if payload.inventory_cost_per_unit is not None:
        metadata["inventory_cost_per_unit"] = str(payload.inventory_cost_per_unit)
    # Operators state costs in the currency they operate in; the engine converts
    # them with the same governed FX rate as the market price.
    if local_currency and local_currency != inferred["reporting_currency"]:
        metadata["cost_currency"] = local_currency
    if payload.fx_rate_to_reporting is not None:
        metadata["fx_source"] = "customer"
    position = MarketPosition(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        workspace_id=payload.workspace_id,
        position_key=f"{inferred['commodity']}-{payload.country_code.lower()}-{payload.season}-{uuid.uuid4().hex[:8]}"[:160],
        name=(payload.name or f"{payload.crop.strip().title()} {payload.season}").strip()[:200],
        commodity=inferred["commodity"],
        season=payload.season.strip(),
        country_code=payload.country_code,
        region=payload.region.strip() if payload.region else None,
        market_structure=inferred["market_structure"],
        local_currency=local_currency,
        reporting_currency=inferred["reporting_currency"],
        quantity_unit=unit,
        expected_production=payload.expected_production,
        inventory_quantity=payload.inventory_quantity,
        production_cost_per_unit=payload.production_cost_per_unit,
        current_realizable_price=payload.local_price,
        price_currency=(payload.local_price_currency or local_currency) if payload.local_price is not None else local_currency,
        fx_rate_to_reporting=payload.fx_rate_to_reporting,
        freight_per_unit=payload.freight_per_unit,
        storage_per_unit=payload.storage_per_unit,
        metadata_json=metadata,
    )
    db.add(position)
    db.flush()
    if payload.local_price is not None:
        db.add(MarketObservation(
            organization_id=org_id, position_id=position.id, evidence_id=f"{position.id}:onboarding-price",
            observation_type="physical_price", provider="customer", source_name="Customer-verified local price",
            source_status="MANUAL", value=payload.local_price, unit=unit, currency=position.price_currency,
            observed_at=datetime.utcnow(), retrieved_at=datetime.utcnow(),
            quality_json={"freshness_max_age_minutes": 10080}, licensing_json={"display_allowed": True},
            metadata_json={"input_source": "customer_onboarding", "author_user_id": ctx.user.id if ctx.user else None},
        ))
    for index, item in enumerate(payload.contracts):
        db.add(MarketContractPosition(
            id=str(uuid.uuid4()), organization_id=org_id, position_id=position.id,
            contract_code=f"{position.position_key}-c{index + 1}"[:160], buyer=item.buyer, status="active",
            quantity=item.quantity, quantity_unit=canonical_unit(item.quantity_unit) if item.quantity_unit else unit,
            price=item.price, currency=(item.currency or local_currency).upper(),
            delivery_start=item.delivery_start, delivery_end=item.delivery_end,
            metadata_json={"input_source": "customer_onboarding"},
        ))
    for field in fields:
        db.add(MarketPositionFieldLink(organization_id=org_id, position_id=position.id, field_entity_id=field.id,
                                       created_by_user_id=ctx.user.id if ctx.user else None))
    db.commit()
    try:
        refresh = await asyncio.wait_for(refresh_position_market_data(db, position), timeout=25.0)
    except Exception as exc:  # noqa: BLE001 - the position exists; evidence follows on the scheduled cycle
        db.rollback()
        refresh = {"status": "deferred_to_scheduled_cycle", "reason": exc.__class__.__name__}
    evaluate_position(db, position)
    db.commit()
    return {
        "id": position.id,
        "status": "created",
        "inferred": {k: inferred[k] for k in ("pack_id", "commodity", "local_currency", "reporting_currency", "market_structure", "futures_role")} | {"quantity_unit": unit},
        "evidence_plan": _provider_availability(inferred["evidence_plan"], local_currency=local_currency, reporting_currency=position.reporting_currency),
        "refresh": refresh,
        "position": _position_payload(db, org_id, position),
    }


# ---------------------------------------------------------------------------
# Provenance, risk, scenarios
# ---------------------------------------------------------------------------


@router.get("/positions/{position_id}/provenance")
def position_provenance(position_id: str, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Where every material number came from."""
    org_id = _org_id(ctx)
    position = _position(db, org_id, position_id)
    contracts = _contracts(db, org_id, position.id)
    computation = compute_position(position, contracts)
    visible, _ = apply_display_policy(computation.payload, None, position)
    metadata = position.metadata_json if isinstance(position.metadata_json, dict) else {}
    observations = (
        db.query(MarketObservation)
        .filter(MarketObservation.organization_id == org_id, MarketObservation.position_id == position.id)
        .order_by(MarketObservation.observed_at.desc())
        .limit(60)
        .all()
    )

    def source(row: MarketObservation) -> dict[str, Any]:
        licensing = row.licensing_json or {}
        meta = row.metadata_json or {}
        display = licensing.get("display_allowed") is not False
        return {
            "evidence_id": row.evidence_id,
            "observation_type": row.observation_type,
            "provider": row.provider,
            "source_name": row.source_name,
            "state": row.source_status,
            "value": str(row.value) if display and row.value is not None else None,
            "redacted": not display,
            "unit": row.unit,
            "currency": row.currency,
            "observed_at": _iso(row.observed_at),
            "retrieved_at": _iso(row.retrieved_at),
            "market_name": meta.get("market_name"),
            "price_basis": meta.get("price_basis"),
            "normalized_value": meta.get("normalized_value") if display else None,
            "normalization_trace": meta.get("normalization_trace") or {},
            "automated": bool(meta.get("automated")),
            "attribution": licensing.get("attribution"),
            "license_id": licensing.get("license_id"),
        }

    sources = [source(row) for row in observations]
    price_source = next((s for s in sources if s["observation_type"] in {"physical_price", "cash_price", "realizable_price"}), None)
    fx_sources = [s for s in sources if s["observation_type"] in {"fx_rate", "fx"}][:3]
    payload = visible
    numbers = {
        "current_realizable_price": {
            "value": payload.get("current_realizable_price"),
            "origin": "governed_shared_evidence" if str(metadata.get("price_source") or "").startswith("data_plane:") else ("customer" if position.current_realizable_price is not None else "missing"),
            "state": metadata.get("price_state") or (price_source or {}).get("state"),
            "evidence": price_source,
        },
        "fx_rate_to_reporting": {
            "value": str(position.fx_rate_to_reporting) if position.fx_rate_to_reporting is not None else None,
            "origin": "governed_shared_evidence" if str(metadata.get("fx_source") or "").startswith("data_plane:") else ("customer" if position.fx_rate_to_reporting is not None else "not_required_or_missing"),
            "method": str(metadata.get("fx_source") or "").removeprefix("data_plane:") or None,
            "state": metadata.get("fx_state"),
            "evidence": fx_sources,
        },
        "expected_production": {"value": payload.get("expected_production"), "origin": metadata.get("production_basis") or "customer",
                                "unit": position.quantity_unit},
        "inventory_quantity": {"value": payload.get("inventory_quantity"), "origin": "customer"},
        "production_cost_per_unit": {"value": payload.get("production_cost_per_unit"), "origin": "customer" if position.production_cost_per_unit is not None else "missing"},
        "contracts": {"count": len(contracts), "origin": "customer", "contracted_quantity": payload.get("contracted_quantity")},
        "derived": {
            key: {"value": payload.get(key), "origin": "deterministic_calculation", "calculation_version": CALCULATION_VERSION}
            for key in ("locked_revenue", "exposed_revenue", "projected_revenue", "projected_cost", "projected_margin", "break_even_price")
        },
    }
    unselected = plane.resolve_physical_price(db, position, ignore_selection=True)
    return {
        "position_id": position.id,
        "pack_id": resolve_pack(position.country_code, position.commodity).pack_id,
        "numbers": numbers,
        "sources": sources,
        # Commercially different governed quotes the customer can choose from.
        "price_selection": {
            "required": metadata.get("price_state") == "SELECTION_REQUIRED",
            "selected_series_key": metadata.get("price_series_key"),
            "candidates": unselected.trace.get("candidates") or [],
        },
    }


class PriceSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    series_key: str | None = Field(default=None, max_length=400)


@router.put("/positions/{position_id}/price-source")
async def select_price_source(position_id: str, payload: PriceSourceRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Choose which governed quote applies when several commercially different ones exist."""
    _require_write(ctx)
    org_id = _org_id(ctx)
    position = _position(db, org_id, position_id)
    metadata = dict(position.metadata_json) if isinstance(position.metadata_json, dict) else {}
    if payload.series_key is None:
        metadata.pop("price_series_key", None)
    else:
        resolution = plane.resolve_physical_price(db, position, ignore_selection=True)
        allowed = {item["series_key"] for item in resolution.trace.get("candidates") or []}
        allowed |= {item.get("series_key") for item in resolution.evidence if item.get("series_key")}
        if payload.series_key not in allowed:
            raise HTTPException(status_code=422, detail={"code": "price_source_not_a_candidate", "message": "Choose one of the listed market prices."})
        metadata["price_series_key"] = payload.series_key
    metadata["price_policy"] = "automatic"
    position.metadata_json = metadata
    db.commit()
    refresh = await refresh_position_market_data(db, position, ingest_missing=False)
    evaluate_position(db, position)
    db.commit()
    return {"position_id": position.id, "price": refresh["price"], "position": _position_payload(db, org_id, position)}


@router.get("/positions/{position_id}/risk")
def position_risk_context(
    position_id: str,
    horizon_periods: int = Query(default=4, ge=1, le=26),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(ctx)
    position = _position(db, org_id, position_id)
    return position_risk(db, position, horizon_periods=horizon_periods)


class ScenarioLevers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(default="Scenario", min_length=1, max_length=120)
    price_pct: Decimal = Decimal("0")
    basis_per_unit_delta: Decimal = Decimal("0")
    yield_pct: Decimal = Decimal("0")
    inventory_pct: Decimal = Decimal("0")
    fx_pct: Decimal = Decimal("0")
    production_cost_pct: Decimal = Decimal("0")
    freight_per_unit_delta: Decimal = Decimal("0")
    storage_per_unit_delta: Decimal = Decimal("0")
    carry_months: Decimal = Field(default=Decimal("0"), ge=0, le=60)
    carry_cost_per_unit_month: Decimal = Field(default=Decimal("0"), ge=0)
    contracted_volume_pct: Decimal = Decimal("0")
    sell_pct_now: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    sell_price_per_unit: Decimal | None = Field(default=None, ge=0)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_id: str = Field(min_length=1, max_length=120)
    scenarios: list[ScenarioLevers] = Field(min_length=1, max_length=6)


@router.post("/scenarios/compare")
def compare_scenarios(payload: CompareRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Deterministic side-by-side scenarios (e.g. commit another 10/25/40%). Not persisted."""
    org_id = _org_id(ctx)
    position = _position(db, org_id, payload.position_id)
    contracts = _contracts(db, org_id, position.id)
    results = []
    for levers in payload.scenarios:
        assumptions = levers.model_dump(exclude={"label"}, mode="json", exclude_none=True)
        try:
            outcome = redact_scenario(scenario_position(position, contracts, assumptions), position)
            results.append({"label": levers.label, "status": "ok", **outcome})
        except MarketCalculationError as exc:
            results.append({"label": levers.label, "status": "invalid", "message": str(exc)})
    return {"position_id": position.id, "calculation_version": CALCULATION_VERSION, "not_a_forecast": True, "scenarios": results, "policy": POLICY}


# ---------------------------------------------------------------------------
# Material changes / alerts
# ---------------------------------------------------------------------------


@router.get("/alerts")
def list_alerts(
    status_filter: Literal["open", "acknowledged", "all"] = Query(default="open", alias="status"),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(ctx)
    query = db.query(MarketMaterialityEvent).filter(MarketMaterialityEvent.organization_id == org_id)
    if status_filter != "all":
        query = query.filter(MarketMaterialityEvent.status == status_filter)
    rows = query.order_by(MarketMaterialityEvent.created_at.desc()).limit(100).all()
    names = {p.id: p.name for p in db.query(MarketPosition).filter(MarketPosition.organization_id == org_id, MarketPosition.id.in_({r.position_id for r in rows}))}
    return {"alerts": [event_payload(row) | {"position_name": names.get(row.position_id)} for row in rows], "methodology_version": METHODOLOGY_VERSION}


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_write(ctx)
    org_id = _org_id(ctx)
    row = db.query(MarketMaterialityEvent).filter(MarketMaterialityEvent.id == alert_id, MarketMaterialityEvent.organization_id == org_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if row.status != "acknowledged":
        row.status = "acknowledged"
        row.acknowledged_at = datetime.utcnow()
        row.acknowledged_by_user_id = ctx.user.id if ctx.user else None
        db.commit()
    return event_payload(row)


@router.get("/changes")
def what_changed(
    position_id: str = Query(min_length=1, max_length=120),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Deterministic comparison with the position's reference ("since yesterday") snapshot."""
    from app.services.market_materiality import evaluate, record_snapshot, reference_snapshot, thresholds_for

    org_id = _org_id(ctx)
    position = _position(db, org_id, position_id)
    current, _ = record_snapshot(db, position, _contracts(db, org_id, position.id))
    reference = reference_snapshot(db, position)
    db.commit()
    if reference is None or reference.id == current.id:
        return {"position_id": position.id, "status": "no_reference_yet", "current_snapshot_id": current.id}
    thresholds, minimum = thresholds_for(position)
    results = evaluate(reference, current, thresholds=thresholds, min_absolute_impact=minimum)
    return {
        "position_id": position.id,
        "status": "compared",
        "reference": {"snapshot_id": reference.id, "computed_at": _iso(reference.computed_at)},
        "current": {"snapshot_id": current.id, "computed_at": _iso(current.computed_at)},
        "changes": [
            {"kind": r.kind, "level": r.level, "would_alert": r.emit and r.level != "LOW", "suppressed_reason": r.suppressed_reason,
             "reasons": redact_reasons(r.reasons, position), "impact": r.impact}
            for r in results
        ],
        "methodology_version": METHODOLOGY_VERSION,
    }


# ---------------------------------------------------------------------------
# Field-to-commercial linkage
# ---------------------------------------------------------------------------


@router.get("/fields")
def available_fields(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    org_id = _org_id(ctx)
    rows = (
        db.query(ManagedEntity)
        .filter(ManagedEntity.organization_id == org_id, ManagedEntity.entity_type.in_(FIELD_ENTITY_TYPES), ManagedEntity.status == "active")
        .order_by(ManagedEntity.display_name.asc())
        .limit(500)
        .all()
    )
    result = []
    for row in rows:
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        result.append({
            "id": row.id,
            "name": row.display_name,
            "crop": metadata.get("crop"),
            "area_hectares": metadata.get("area_hectares"),
            "operational": _field_operational(row),
        })
    return {"fields": result}


class FieldLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_ids: list[str] = Field(default_factory=list, max_length=200)


def _linked_area_hectares(db: Session, org_id: str, position_id: str) -> tuple[Decimal, list[dict[str, Any]]]:
    links = (
        db.query(MarketPositionFieldLink, ManagedEntity)
        .join(ManagedEntity, ManagedEntity.id == MarketPositionFieldLink.field_entity_id)
        .filter(MarketPositionFieldLink.organization_id == org_id, MarketPositionFieldLink.position_id == position_id,
                ManagedEntity.organization_id == org_id)
        .all()
    )
    total = Decimal(0)
    detail = []
    for _link, field in links:
        metadata = field.metadata_json if isinstance(field.metadata_json, dict) else {}
        area = _dec(metadata.get("area_hectares"))
        # Archived/inactive fields stay linked for history but never add area.
        active = str(field.status or "").lower() == "active"
        usable = area is not None and area > 0 and active and _field_operational(field)
        if usable:
            total += area
        reason = None if usable else ("inactive" if not active else "synthetic_or_demo" if not _field_operational(field) else "missing_area")
        detail.append({"field_id": field.id, "name": field.display_name, "area_hectares": str(area) if area is not None else None,
                       "counted": usable, "reason": reason})
    return total, detail


@router.put("/positions/{position_id}/fields")
def link_fields(position_id: str, payload: FieldLinkRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_write(ctx)
    org_id = _org_id(ctx)
    position = _position(db, org_id, position_id)
    fields = _org_fields(db, org_id, payload.field_ids)
    db.query(MarketPositionFieldLink).filter(MarketPositionFieldLink.organization_id == org_id, MarketPositionFieldLink.position_id == position.id).delete(synchronize_session=False)
    for field in fields:
        db.add(MarketPositionFieldLink(organization_id=org_id, position_id=position.id, field_entity_id=field.id,
                                       created_by_user_id=ctx.user.id if ctx.user else None))
    db.commit()
    area, detail = _linked_area_hectares(db, org_id, position.id)
    return {"position_id": position.id, "linked_area_hectares": format(area, "f"), "fields": detail}


class YieldEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    yield_per_area: Decimal = Field(gt=0)
    quantity_unit: str = Field(min_length=1, max_length=40)
    area_unit: Literal["hectare", "acre"] = "hectare"
    source: Literal["customer", "field_intelligence", "crop_intelligence", "connector"] = "customer"
    observed_at: datetime | None = None
    note: str | None = Field(default=None, max_length=1000)
    apply_to_production: bool = True


@router.post("/positions/{position_id}/yield-estimates", status_code=status.HTTP_201_CREATED)
def record_yield_estimate(position_id: str, payload: YieldEstimateRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Operational yield -> expected production -> commercial exposure.

    When the position has linked fields with known area, expected production
    becomes linked area x yield (unit-converted) and materiality is evaluated
    immediately so a large yield revision surfaces as a commercial change.
    """
    _require_write(ctx)
    org_id = _org_id(ctx)
    position = _position(db, org_id, position_id)
    unit = canonical_unit(payload.quantity_unit)
    if unit is None:
        raise HTTPException(status_code=422, detail={"code": "unit_not_supported"})
    per_hectare = payload.yield_per_area / ACRE_IN_HECTARES if payload.area_unit == "acre" else payload.yield_per_area
    observed = (payload.observed_at.replace(tzinfo=None) if payload.observed_at and payload.observed_at.tzinfo else payload.observed_at) or datetime.utcnow()
    row = MarketObservation(
        organization_id=org_id, position_id=position.id, evidence_id=f"{position.id}:yield:{uuid.uuid4().hex}",
        observation_type="yield_estimate", provider=payload.source, source_name=f"Yield estimate ({payload.source})",
        source_status="MANUAL", value=per_hectare, unit=f"{unit}/hectare", currency=None, observed_at=observed,
        retrieved_at=datetime.utcnow(), quality_json={"freshness_max_age_minutes": 60 * 24 * 45},
        licensing_json={"display_allowed": True},
        metadata_json={"input_source": payload.source, "note": payload.note, "author_user_id": ctx.user.id if ctx.user else None,
                       "submitted_value": str(payload.yield_per_area), "submitted_area_unit": payload.area_unit},
    )
    db.add(row)
    area, detail = _linked_area_hectares(db, org_id, position.id)
    applied = False
    previous = position.expected_production
    if payload.apply_to_production and area > 0:
        try:
            production = convert_quantity(area * per_hectare, unit, position.quantity_unit, position.commodity)
        except MarketCalculationError as exc:
            raise HTTPException(status_code=422, detail={"code": "unit_not_convertible", "message": str(exc)}) from exc
        position.expected_production = production.quantize(Decimal("0.00000001"))
        metadata = dict(position.metadata_json or {})
        metadata.update({"production_basis": "linked_fields_x_yield_estimate", "yield_estimate_evidence_id": row.evidence_id,
                         "linked_area_hectares": format(area, "f")})
        position.metadata_json = metadata
        applied = True
    db.commit()
    materiality = evaluate_position(db, position) if applied else None
    db.commit()
    return {
        "position_id": position.id,
        "evidence_id": row.evidence_id,
        "yield_per_hectare": format(per_hectare.quantize(Decimal("0.0001")), "f"),
        "linked_area_hectares": format(area, "f"),
        "fields": detail,
        "applied_to_expected_production": applied,
        "previous_expected_production": format(previous, "f") if previous is not None else None,
        "expected_production": format(position.expected_production, "f"),
        "materiality": materiality,
        "reason": None if applied else ("no_linked_area" if area <= 0 else "not_requested"),
    }


# ---------------------------------------------------------------------------
# Decision Journal v2
# ---------------------------------------------------------------------------


class JournalOutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_taken: str | None = Field(default=None, max_length=4000)
    outcome: dict[str, Any] = Field(default_factory=dict)


@router.patch("/decision-journal/{entry_id}")
def record_journal_outcome(entry_id: str, payload: JournalOutcomeRequest, ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Record what was actually done and what happened versus the modelled result."""
    _require_write(ctx)
    org_id = _org_id(ctx)
    row = db.query(MarketDecisionJournalEntry).filter(MarketDecisionJournalEntry.id == entry_id, MarketDecisionJournalEntry.organization_id == org_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    if payload.action_taken is not None:
        row.action_taken = payload.action_taken.strip()
    if payload.outcome:
        modelled = ((row.evidence_snapshot_json or {}).get("position") or {})
        actual_margin = _dec(payload.outcome.get("actual_margin"))
        modelled_margin = _dec(modelled.get("projected_margin"))
        comparison = None
        if actual_margin is not None and modelled_margin is not None:
            comparison = {"modelled_margin": format(modelled_margin, "f"), "actual_margin": format(actual_margin, "f"),
                          "difference": format(actual_margin - modelled_margin, "f")}
        row.outcome_json = {**(row.outcome_json or {}), **payload.outcome, "comparison": comparison}
        row.outcome_recorded_at = datetime.utcnow()
        row.outcome_recorded_by_user_id = ctx.user.id if ctx.user else None
    db.commit()
    return {"id": row.id, "action_taken": row.action_taken, "outcome": row.outcome_json, "outcome_recorded_at": _iso(row.outcome_recorded_at)}


# ---------------------------------------------------------------------------
# Coverage (Data Health / admin)
# ---------------------------------------------------------------------------


@router.get("/coverage")
def coverage(ctx: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Exact provider coverage, configuration and freshness. No tenant data."""
    org_id = _org_id(ctx)
    role = str(ctx.membership.role if ctx.membership else "viewer").lower()
    health = plane.provider_health(db)
    if role not in ADMIN_ROLES | WRITE_ROLES:
        health = {pid: {k: v for k, v in item.items() if k not in {"last_run", "credential_env"}} for pid, item in health.items()}
    return {"organization_id": org_id, "providers": health, "packs": pack_catalog(), "data_plane_version": plane.DATA_PLANE_VERSION}
