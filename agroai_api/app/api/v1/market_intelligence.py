"""Authenticated AGRO-AI Market Intelligence API.

This surface exposes commercial position, deterministic scenarios, source
health and grounded AI synthesis. All database reads are organization-scoped;
request bodies never select an organization.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.core.config import settings
from app.db.base import get_db
from app.models.market_intelligence import (
    MarketContractPosition,
    MarketDecisionJournalEntry,
    MarketObservation,
    MarketPosition,
    MarketScenario,
)
from app.services.market_intelligence import (
    CALCULATION_VERSION,
    MarketCalculationError,
    apply_display_policy,
    compute_position,
    data_health,
    redact_scenario,
    scenario_position,
)
from app.services.market_intelligence_ai import generate_market_brief
from app.services.market_intelligence_demo import seed_demo_markets
from app.services.market_intelligence_release import (
    configured_release_state,
    demo_fixtures_enabled,
    market_intelligence_access,
    organization_cohort,
)

WRITE_ROLES = {"owner", "admin", "operator", "analyst"}
ADMIN_ROLES = {"owner", "admin"}


def enforce_market_intelligence_release(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> None:
    allowed, release_state, cohort = market_intelligence_access(
        db,
        ctx.organization,
        user_email=ctx.user.email if ctx.user else None,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "market_intelligence_not_released",
                "release_state": release_state,
                "cohort": cohort,
                "message": "Market Intelligence is not enabled for this organization yet.",
            },
        )


router = APIRouter(
    prefix="/market-intelligence",
    tags=["market-intelligence"],
    dependencies=[Depends(enforce_market_intelligence_release)],
)


def _org_id(ctx: AuthContext) -> str:
    if ctx.organization is None or ctx.membership is None:
        raise HTTPException(status_code=403, detail="Organization membership required")
    return str(ctx.organization.id)


def _role(ctx: AuthContext) -> str:
    return str(ctx.membership.role if ctx.membership else "viewer").strip().lower()


def _require_write(ctx: AuthContext) -> None:
    if _role(ctx) not in WRITE_ROLES:
        raise HTTPException(
            status_code=403,
            detail={"code": "market_intelligence_read_only", "message": "This role has read-only Market Intelligence access."},
        )


def _require_admin(ctx: AuthContext) -> None:
    if _role(ctx) not in ADMIN_ROLES:
        raise HTTPException(
            status_code=403,
            detail={"code": "market_intelligence_admin_required", "message": "Organization administrator access required."},
        )


def _position(db: Session, org_id: str, position_id: str) -> MarketPosition:
    row = (
        db.query(MarketPosition)
        .filter(MarketPosition.id == position_id, MarketPosition.organization_id == org_id)
        .first()
    )
    if row is None:
        # Deliberately 404 rather than 403: do not disclose cross-tenant ids.
        raise HTTPException(status_code=404, detail="Market position not found")
    return row


def _contracts(db: Session, org_id: str, position_id: str) -> list[MarketContractPosition]:
    return (
        db.query(MarketContractPosition)
        .filter(
            MarketContractPosition.organization_id == org_id,
            MarketContractPosition.position_id == position_id,
        )
        .order_by(MarketContractPosition.created_at.asc())
        .all()
    )


def _observations(db: Session, org_id: str, position_id: str) -> list[MarketObservation]:
    return (
        db.query(MarketObservation)
        .filter(
            MarketObservation.organization_id == org_id,
            MarketObservation.position_id == position_id,
        )
        .order_by(MarketObservation.observed_at.desc())
        .limit(100)
        .all()
    )


def _position_payload(
    db: Session,
    org_id: str,
    row: MarketPosition,
    *,
    contracts: list[MarketContractPosition] | None = None,
    observations: list[MarketObservation] | None = None,
) -> dict[str, Any]:
    computation = compute_position(row, _contracts(db, org_id, row.id) if contracts is None else contracts)
    observations = _observations(db, org_id, row.id) if observations is None else observations
    payload, evidence = apply_display_policy(computation.payload, computation.evidence, row)
    return {
        **payload,
        "data_health": data_health(observations),
        "evidence": evidence,
    }


def _position_payloads(db: Session, org_id: str, rows: list[MarketPosition]) -> list[dict[str, Any]]:
    """Load portfolio dependencies in two queries rather than two queries per position."""
    if not rows:
        return []
    position_ids = [row.id for row in rows]
    contracts_by_position: dict[str, list[MarketContractPosition]] = defaultdict(list)
    for contract in (
        db.query(MarketContractPosition)
        .filter(MarketContractPosition.organization_id == org_id, MarketContractPosition.position_id.in_(position_ids))
        .order_by(MarketContractPosition.created_at.asc())
        .all()
    ):
        contracts_by_position[contract.position_id].append(contract)
    observations_by_position: dict[str, list[MarketObservation]] = defaultdict(list)
    # Data health only needs recent evidence; a bounded window keeps portfolio
    # reads fast as time series accumulate.
    window_start = datetime.utcnow() - timedelta(days=180)
    # The newest 100 observations *per position* (a window partitioned by
    # position), so one high-frequency position cannot crowd out the others.
    ranked = (
        db.query(
            MarketObservation.id.label("id"),
            func.row_number().over(
                partition_by=MarketObservation.position_id,
                order_by=(MarketObservation.observed_at.desc(), MarketObservation.id.desc()),
            ).label("rank"),
        )
        .filter(
            MarketObservation.organization_id == org_id,
            MarketObservation.position_id.in_(position_ids),
            MarketObservation.observed_at >= window_start,
        )
        .subquery()
    )
    for observation in (
        db.query(MarketObservation)
        .join(ranked, ranked.c.id == MarketObservation.id)
        .filter(ranked.c.rank <= 100, MarketObservation.organization_id == org_id)
        .order_by(MarketObservation.observed_at.desc())
        .all()
    ):
        observations_by_position[observation.position_id].append(observation)
    return [
        _position_payload(
            db,
            org_id,
            row,
            contracts=contracts_by_position[row.id],
            observations=observations_by_position[row.id],
        )
        for row in rows
    ]


def _contract_payload(row: MarketContractPosition) -> dict[str, Any]:
    return {
        "id": row.id,
        "position_id": row.position_id,
        "contract_code": row.contract_code,
        "buyer": row.buyer,
        "status": row.status,
        "quantity": str(row.quantity),
        "quantity_unit": row.quantity_unit,
        "price": str(row.price),
        "currency": row.currency,
        "fx_rate_to_reporting": str(row.fx_rate_to_reporting) if row.fx_rate_to_reporting is not None else None,
        "delivery_start": row.delivery_start.isoformat() + "Z" if row.delivery_start else None,
        "delivery_end": row.delivery_end.isoformat() + "Z" if row.delivery_end else None,
        "delivery_location": row.delivery_location,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    }


def _observation_payload(row: MarketObservation) -> dict[str, Any]:
    licensing = row.licensing_json or {}
    display_allowed = licensing.get("display_allowed") is not False
    return {
        "id": row.id,
        "position_id": row.position_id,
        "evidence_id": row.evidence_id,
        "observation_type": row.observation_type,
        "provider": row.provider,
        "source_name": row.source_name,
        "source_status": row.source_status,
        "value": str(row.value) if display_allowed and row.value is not None else None,
        "unit": row.unit,
        "currency": row.currency,
        "observed_at": row.observed_at.isoformat() + "Z" if row.observed_at else None,
        "retrieved_at": row.retrieved_at.isoformat() + "Z" if row.retrieved_at else None,
        "delay_minutes": str(row.delay_minutes) if row.delay_minutes is not None else None,
        "quality": row.quality_json or {},
        "licensing": licensing,
        "redacted": not display_allowed,
    }


def _attention(position: dict[str, Any]) -> list[dict[str, Any]]:
    # ``code``/``params`` are what the portal renders (in every locale); the
    # English title/summary remain for API consumers.
    findings: list[dict[str, Any]] = []
    if position.get("over_contracted"):
        findings.append({
            "importance": "high",
            "position_id": position.get("position_id"),
            "code": "over_contracted",
            "params": {},
            "title": "Contracted volume exceeds expected production",
            "summary": "Projected margin is suppressed until production or contract volume is reconciled.",
        })
    missing = list(position.get("missing_inputs") or [])
    if missing:
        findings.append({
            "importance": "high",
            "position_id": position.get("position_id"),
            "code": "missing_inputs",
            "params": {"inputs": missing[:3]},
            "title": "Commercial position has missing inputs",
            "summary": "Complete " + ", ".join(missing[:3]) + " before relying on margin calculations.",
        })
    try:
        exposed = Decimal(str(position.get("exposed_percent"))) if position.get("exposed_percent") is not None else Decimal("0")
    except Exception:
        exposed = Decimal("0")
    if exposed >= Decimal("60"):
        findings.append({
            "importance": "medium",
            "position_id": position.get("position_id"),
            "code": "exposure",
            "params": {"percent": str(position.get("exposed_percent"))},
            "title": "Most expected production remains commercially exposed",
            "summary": f"{position.get('exposed_percent')}% remains uncontracted under the current structured position.",
        })
    health = position.get("data_health") or {}
    if health.get("status") in {"degraded", "missing"}:
        findings.append({
            "importance": "high",
            "position_id": position.get("position_id"),
            "code": "data_health",
            "params": {},
            "title": "Market data health needs attention",
            "summary": "One or more source observations are stale, unavailable, not configured, or missing.",
        })
    return findings


def _aggregate_health(statuses: list[str]) -> str:
    if not statuses:
        return "missing"
    if any(item in {"degraded", "missing"} for item in statuses):
        return "degraded"
    if all(item == "demo" for item in statuses):
        return "demo"
    if any(item == "demo" for item in statuses):
        return "mixed"
    return "healthy"


def _demo_seed_allowed() -> bool:
    env = str(getattr(settings, "APP_ENV", "development") or "development").strip().lower()
    return env not in {"production", "staging"} or demo_fixtures_enabled()


@router.get("/capabilities")
def capabilities(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    role = _role(ctx)
    return {
        "module": "market_intelligence",
        "role": role,
        "can_write": role in WRITE_ROLES,
        "can_admin": role in ADMIN_ROLES,
        "can_seed_demo": role in ADMIN_ROLES and _demo_seed_allowed(),
        "release_state": configured_release_state(),
        "cohort": organization_cohort(db, ctx.organization),
        "policy": {
            "scope": "commercial_decision_support",
            "trade_execution": False,
            "personalized_derivatives_instructions": False,
        },
    }


@router.get("/overview")
def overview(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(ctx)
    rows = (
        db.query(MarketPosition)
        .filter(MarketPosition.organization_id == org_id, MarketPosition.status == "active")
        .order_by(MarketPosition.country_code.asc(), MarketPosition.commodity.asc(), MarketPosition.season.asc())
        .all()
    )
    positions = _position_payloads(db, org_id, rows)
    by_currency: dict[str, dict[str, Any]] = {}
    for item in positions:
        currency = str(item.get("reporting_currency") or "UNKNOWN")
        bucket = by_currency.setdefault(currency, {
            "currency": currency,
            "projected_revenue": Decimal("0"),
            "projected_margin": Decimal("0"),
            "locked_revenue": Decimal("0"),
            "exposed_revenue": Decimal("0"),
            "complete_positions": 0,
            "total_positions": 0,
        })
        bucket["total_positions"] += 1
        if item.get("projected_revenue") is not None and item.get("projected_margin") is not None:
            bucket["complete_positions"] += 1
            bucket["projected_revenue"] += Decimal(str(item["projected_revenue"]))
            bucket["projected_margin"] += Decimal(str(item["projected_margin"]))
        if item.get("locked_revenue") is not None:
            bucket["locked_revenue"] += Decimal(str(item["locked_revenue"]))
        if item.get("exposed_revenue") is not None:
            bucket["exposed_revenue"] += Decimal(str(item["exposed_revenue"]))
    portfolio = []
    for currency in sorted(by_currency):
        bucket = by_currency[currency]
        partial = bucket["complete_positions"] != bucket["total_positions"]
        portfolio.append({
            **{key: value for key, value in bucket.items() if not isinstance(value, Decimal)},
            "projected_revenue": None if partial else format(bucket["projected_revenue"], "f"),
            "projected_margin": None if partial else format(bucket["projected_margin"], "f"),
            "locked_revenue": format(bucket["locked_revenue"], "f"),
            "exposed_revenue": format(bucket["exposed_revenue"], "f"),
            "partial": partial,
        })
    attention = [finding for item in positions for finding in _attention(item)]
    importance_order = {"high": 0, "medium": 1, "low": 2}
    attention.sort(key=lambda item: importance_order.get(str(item.get("importance")), 9))
    statuses = [str((item.get("data_health") or {}).get("status") or "missing") for item in positions]
    return {
        "module": "market_intelligence",
        "calculation_version": CALCULATION_VERSION,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "position_count": len(positions),
        "portfolio_by_reporting_currency": portfolio,
        "attention": attention[:5],
        "positions": positions,
        "data_health": {
            "status": _aggregate_health(statuses),
            "position_statuses": statuses,
        },
        "policy": {
            "scope": "commercial_decision_support",
            "trade_execution": False,
            "personalized_derivatives_instructions": False,
        },
    }


@router.get("/positions")
def list_positions(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(ctx)
    rows = (
        db.query(MarketPosition)
        .filter(MarketPosition.organization_id == org_id)
        .order_by(MarketPosition.updated_at.desc())
        .all()
    )
    return {"positions": _position_payloads(db, org_id, rows)}


@router.get("/positions/{position_id}")
def get_position(
    position_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(ctx)
    return _position_payload(db, org_id, _position(db, org_id, position_id))


@router.get("/positions/{position_id}/contracts")
def list_contracts(
    position_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(ctx)
    _position(db, org_id, position_id)
    return {"contracts": [_contract_payload(row) for row in _contracts(db, org_id, position_id)]}


@router.get("/positions/{position_id}/observations")
def list_observations(
    position_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(ctx)
    _position(db, org_id, position_id)
    return {"observations": [_observation_payload(row) for row in _observations(db, org_id, position_id)]}


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_id: str = Field(min_length=1, max_length=120)
    name: str = Field(default="Scenario", min_length=1, max_length=160)
    price_pct: Decimal = Decimal("0")
    yield_pct: Decimal = Decimal("0")
    fx_pct: Decimal = Decimal("0")
    production_cost_pct: Decimal = Decimal("0")
    freight_per_unit_delta: Decimal = Decimal("0")
    storage_per_unit_delta: Decimal = Decimal("0")
    sell_pct_now: Decimal = Field(default=Decimal("0"), ge=0, le=100)


@router.post("/scenarios", status_code=201)
def create_scenario(
    payload: ScenarioRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_write(ctx)
    org_id = _org_id(ctx)
    position = _position(db, org_id, payload.position_id)
    assumptions = payload.model_dump(exclude={"position_id", "name"}, mode="json")
    try:
        result = redact_scenario(scenario_position(position, _contracts(db, org_id, position.id), assumptions), position)
    except MarketCalculationError as exc:
        raise HTTPException(status_code=422, detail={"code": "scenario_invalid", "message": str(exc)}) from exc
    scenario = MarketScenario(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        position_id=position.id,
        created_by_user_id=ctx.user.id if ctx.user else None,
        name=payload.name.strip(),
        assumptions_json=result["assumptions"],
        baseline_json=result["baseline"],
        result_json={"result": result["result"], "delta": result["delta"], "zero_change_invariant": result["zero_change_invariant"]},
        calculation_version=CALCULATION_VERSION,
    )
    db.add(scenario)
    db.commit()
    return {
        "id": scenario.id,
        "name": scenario.name,
        "position_id": position.id,
        **result,
        "created_at": scenario.created_at.isoformat() + "Z" if scenario.created_at else None,
    }


@router.get("/scenarios")
def list_scenarios(
    position_id: str | None = Query(default=None, max_length=120),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(ctx)
    query = db.query(MarketScenario).filter(MarketScenario.organization_id == org_id)
    if position_id:
        _position(db, org_id, position_id)
        query = query.filter(MarketScenario.position_id == position_id)
    rows = query.order_by(MarketScenario.created_at.desc()).limit(100).all()
    return {"scenarios": [{
        "id": row.id,
        "position_id": row.position_id,
        "name": row.name,
        "assumptions": row.assumptions_json,
        "baseline": row.baseline_json,
        "result": row.result_json,
        "calculation_version": row.calculation_version,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    } for row in rows]}


@router.get("/scenarios/{scenario_id}")
def get_scenario(
    scenario_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(ctx)
    row = (
        db.query(MarketScenario)
        .filter(MarketScenario.id == scenario_id, MarketScenario.organization_id == org_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {
        "id": row.id,
        "position_id": row.position_id,
        "name": row.name,
        "assumptions": row.assumptions_json,
        "baseline": row.baseline_json,
        "result": row.result_json,
        "calculation_version": row.calculation_version,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    }


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_id: str | None = Field(default=None, min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=1600)
    language: str = Field(default="en", min_length=2, max_length=16)


_LEVEL_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _focus_position(db: Session, org_id: str) -> MarketPosition | None:
    """The position that most deserves attention: worst open material change,
    otherwise the largest exposed revenue (deterministic)."""
    from app.models.market_intelligence import MarketMaterialityEvent

    events = (
        db.query(MarketMaterialityEvent)
        .filter(MarketMaterialityEvent.organization_id == org_id, MarketMaterialityEvent.status == "open")
        .all()
    )
    if events:
        worst = min(events, key=lambda e: (_LEVEL_RANK.get(e.level, 9), -(e.created_at.timestamp() if e.created_at else 0)))
        row = db.query(MarketPosition).filter(MarketPosition.id == worst.position_id, MarketPosition.organization_id == org_id, MarketPosition.status == "active").first()
        if row is not None:
            return row
    rows = db.query(MarketPosition).filter(MarketPosition.organization_id == org_id, MarketPosition.status == "active").all()
    best: tuple[Decimal, MarketPosition] | None = None
    for row in rows:
        try:
            exposed = compute_position(row, _contracts(db, org_id, row.id)).payload.get("exposed_revenue")
        except MarketCalculationError:
            continue
        value = Decimal(str(exposed)) if exposed is not None else Decimal("-1")
        if best is None or value > best[0]:
            best = (value, row)
    return best[1] if best else None


def _ask_context(db: Session, org_id: str, position: MarketPosition, contracts: list[MarketContractPosition], payload: dict[str, Any], question: str) -> tuple[dict[str, Any], dict[str, str]]:
    from app.models.market_intelligence import MarketMaterialityEvent
    from app.services.market_intelligence_ask import parse_scenario_intents, scenario_evidence
    from app.services.market_materiality import evidence_states

    metadata = position.metadata_json if isinstance(position.metadata_json, dict) else {}
    intents = parse_scenario_intents(question, {**payload, "price_currency": position.price_currency})
    scenarios, scenario_ids = scenario_evidence(position, contracts, intents)
    price_row = (
        db.query(MarketObservation)
        .filter(
            MarketObservation.organization_id == org_id,
            MarketObservation.position_id == position.id,
            MarketObservation.observation_type.in_(("physical_price", "cash_price", "realizable_price")),
        )
        .order_by(MarketObservation.observed_at.desc())
        .first()
    )
    price_source = None
    if price_row is not None:
        display = (price_row.licensing_json or {}).get("display_allowed") is not False
        price_source = {
            "source_name": price_row.source_name,
            "provider": price_row.provider,
            "state": price_row.source_status,
            "observed_at": price_row.observed_at.isoformat() + "Z" if price_row.observed_at else None,
            "market_name": (price_row.metadata_json or {}).get("market_name"),
            "value": str(price_row.value) if display and price_row.value is not None else None,
            "unit": price_row.unit,
            "currency": price_row.currency,
        }
    events = (
        db.query(MarketMaterialityEvent)
        .filter(MarketMaterialityEvent.organization_id == org_id, MarketMaterialityEvent.position_id == position.id, MarketMaterialityEvent.status == "open")
        .order_by(MarketMaterialityEvent.created_at.desc())
        .limit(5)
        .all()
    )
    saved = (
        db.query(MarketScenario)
        .filter(MarketScenario.organization_id == org_id, MarketScenario.position_id == position.id)
        .order_by(MarketScenario.created_at.desc())
        .limit(5)
        .all()
    )
    saved_scenarios = [{
        "name": row.name,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "assumptions": row.assumptions_json,
        "projected_margin": ((row.result_json or {}).get("result") or {}).get("projected_margin"),
        "exposed_revenue": ((row.result_json or {}).get("result") or {}).get("exposed_revenue"),
    } for row in saved]
    extra_evidence = dict(scenario_ids)
    for index, item in enumerate(saved_scenarios, start=1):
        for key in ("projected_margin", "exposed_revenue"):
            if item.get(key) is not None:
                extra_evidence[f"saved_scenario_{index}.{key}"] = str(item[key])
    context = {
        "reporting_currency": payload.get("reporting_currency"),
        "scenarios": scenarios,
        "data_states": [
            {"evidence": key, "state": state}
            for key, state in {
                **evidence_states(db, position, contracts),
                "price": metadata.get("price_state") or (price_row.source_status if price_row else "UNAVAILABLE"),
            }.items()
        ],
        "price_source": price_source,
        "material_changes": [{"level": e.level, "kind": e.kind, "position_name": position.name, "reasons": e.reasons_json,
                              "impact": e.impact_json, "created_at": e.created_at.isoformat() + "Z" if e.created_at else None} for e in events],
        "saved_scenarios": saved_scenarios,
    }
    return context, extra_evidence


@router.post("/ask")
async def ask_market_intelligence(
    payload: AskRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.services.market_intelligence_ask import requested_language, scenario_parse_status

    org_id = _org_id(ctx)
    if payload.position_id:
        position = _position(db, org_id, payload.position_id)
        scope = "position"
    else:
        position = _focus_position(db, org_id)
        scope = "portfolio_focus"
        if position is None:
            raise HTTPException(status_code=404, detail={"code": "no_commercial_positions", "message": "Add a commercial position first."})
    contracts = _contracts(db, org_id, position.id)
    computation = compute_position(position, contracts)
    visible_payload, visible_evidence = apply_display_policy(computation.payload, computation.evidence, position)
    context, extra_evidence = _ask_context(db, org_id, position, contracts, computation.payload, payload.question)
    evidence = {**visible_evidence, **extra_evidence}
    language = requested_language(payload.question) or payload.language
    result = await generate_market_brief(
        visible_payload,
        evidence,
        question=payload.question,
        language=language,
        context=context,
    )
    return {
        "position_id": position.id,
        "scope": scope,
        "position": visible_payload,
        "evidence": evidence,
        "scenarios": context["scenarios"],
        "scenario_parse": scenario_parse_status(payload.question, payload.language, context["scenarios"]),
        "data_states": context["data_states"],
        "intelligence": result,
        "notice": "Commercial decision support only. No trade execution or personalized derivatives instruction is provided.",
    }


class JournalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_id: str = Field(min_length=1, max_length=120)
    scenario_id: str | None = Field(default=None, max_length=120)
    decision: str = Field(min_length=1, max_length=4000)
    rationale: str | None = Field(default=None, max_length=8000)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    action_taken: str | None = Field(default=None, max_length=4000)


@router.post("/decision-journal", status_code=201)
def create_journal_entry(
    payload: JournalRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_write(ctx)
    org_id = _org_id(ctx)
    position = _position(db, org_id, payload.position_id)
    scenario = None
    if payload.scenario_id:
        scenario = (
            db.query(MarketScenario)
            .filter(MarketScenario.id == payload.scenario_id, MarketScenario.organization_id == org_id)
            .first()
        )
        if scenario is None or scenario.position_id != position.id:
            raise HTTPException(status_code=404, detail="Scenario not found")
    # Institutional memory: freeze what was known when the decision was taken.
    contracts = _contracts(db, org_id, position.id)
    snapshot_payload = _position_payload(db, org_id, position, contracts=contracts)
    evidence_snapshot = {
        "captured_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "calculation_version": CALCULATION_VERSION,
        "position": {k: snapshot_payload.get(k) for k in (
            "expected_production", "inventory_quantity", "marketable_supply", "contracted_quantity", "uncontracted_quantity",
            "contracted_percent", "exposed_percent", "current_realizable_price", "locked_revenue", "exposed_revenue",
            "projected_revenue", "projected_cost", "projected_margin", "projected_margin_percent", "break_even_price",
            "reporting_currency", "quantity_unit", "data_complete", "missing_inputs", "warnings",
        )},
        "data_health": {
            "status": (snapshot_payload.get("data_health") or {}).get("status"),
            "sources": [
                {k: src.get(k) for k in ("provider", "source_name", "status", "observed_at", "observation_type")}
                for src in ((snapshot_payload.get("data_health") or {}).get("sources") or [])[:10]
            ],
        },
        "scenario": {
            "id": scenario.id, "name": scenario.name, "assumptions": scenario.assumptions_json,
            "result": (scenario.result_json or {}).get("result"), "delta": (scenario.result_json or {}).get("delta"),
        } if scenario is not None else None,
    }
    row = MarketDecisionJournalEntry(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        position_id=position.id,
        scenario_id=payload.scenario_id,
        created_by_user_id=ctx.user.id if ctx.user else None,
        decision=payload.decision.strip(),
        rationale=payload.rationale.strip() if payload.rationale else None,
        assumptions_json=payload.assumptions,
        evidence_snapshot_json=evidence_snapshot,
        action_taken=payload.action_taken.strip() if payload.action_taken else None,
    )
    db.add(row)
    db.commit()
    return {
        "id": row.id,
        "position_id": row.position_id,
        "scenario_id": row.scenario_id,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    }


@router.get("/decision-journal")
def list_journal_entries(
    position_id: str | None = Query(default=None, max_length=120),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _org_id(ctx)
    query = db.query(MarketDecisionJournalEntry).filter(MarketDecisionJournalEntry.organization_id == org_id)
    if position_id:
        _position(db, org_id, position_id)
        query = query.filter(MarketDecisionJournalEntry.position_id == position_id)
    rows = query.order_by(MarketDecisionJournalEntry.created_at.desc()).limit(100).all()
    return {"entries": [{
        "id": row.id,
        "position_id": row.position_id,
        "scenario_id": row.scenario_id,
        "decision": row.decision,
        "rationale": row.rationale,
        "assumptions": row.assumptions_json,
        "outcome": row.outcome_json,
        "action_taken": row.action_taken,
        "evidence_snapshot": row.evidence_snapshot_json,
        "outcome_recorded_at": row.outcome_recorded_at.isoformat() + "Z" if row.outcome_recorded_at else None,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    } for row in rows]}


@router.post("/demo/seed")
def seed_demo(
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(ctx)
    if not _demo_seed_allowed():
        raise HTTPException(
            status_code=403,
            detail={
                "code": "demo_fixtures_disabled",
                "message": "Market Intelligence demo fixtures are disabled in this environment.",
            },
        )
    return seed_demo_markets(db, _org_id(ctx))
