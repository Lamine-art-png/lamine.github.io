"""Paid, tenant-safe analytical surfaces for specialist and counterfactual intelligence."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.intelligence_memory_api import _organization_and_role
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import User
from app.services.intelligence_context import build_intelligence_context
from app.services.intelligence_counterfactuals import (
    CounterfactualComparison,
    CounterfactualInput,
    CounterfactualInputError,
    CounterfactualScenario,
    compare_counterfactuals,
)
from app.services.intelligence_grounding import build_intelligence_grounding
from app.services.intelligence_hardening import enrich_grounding_packet
from app.services.intelligence_specialists import SpecialistDomain, run_specialists


router = APIRouter(prefix="/intelligence/analysis", tags=["intelligence-analysis"])


class SpecialistAnalysisRequest(BaseModel):
    workspace_id: str | None = None
    field_id: str | None = None
    audience: str | None = None
    domains: list[SpecialistDomain] | None = None


class CounterfactualRequest(BaseModel):
    tool_id: str = Field(min_length=1, max_length=160)
    baseline_inputs: dict[str, CounterfactualInput]
    scenarios: list[CounterfactualScenario] = Field(default_factory=list, max_length=12)


@router.post("/specialists")
def specialist_analysis(
    payload: SpecialistAnalysisRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _organization_and_role(db, tenant_id, user)
    bundle = build_intelligence_context(
        db=db,
        tenant_id=tenant_id,
        user=user,
        workspace_id=payload.workspace_id,
        field_id=payload.field_id,
        audience=payload.audience,
    )
    context = bundle["evidence_context"]
    try:
        packet = enrich_grounding_packet(
            build_intelligence_grounding(context, field_id=payload.field_id),
            context,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "specialist_grounding_unavailable",
                "message": "The evidence graph could not be constructed, so specialist analysis was withheld.",
            },
        ) from exc
    results = run_specialists(packet, payload.domains)
    return {
        "schema_version": "agroai-specialist-analysis/1.0.0",
        "organization_id": tenant_id,
        "workspace_id": packet.workspace_id,
        "field_id": packet.field_id,
        "grounding_confidence": packet.grounding_confidence,
        "specialists": [row.model_dump(mode="python") for row in results],
        "side_effect_free": True,
    }


@router.post("/counterfactuals", response_model=CounterfactualComparison)
def counterfactual_analysis(
    payload: CounterfactualRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CounterfactualComparison:
    _organization_and_role(db, tenant_id, user)
    try:
        return compare_counterfactuals(
            tool_id=payload.tool_id,
            baseline_inputs=payload.baseline_inputs,
            scenarios=payload.scenarios,
        )
    except (CounterfactualInputError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "counterfactual_not_computable", "message": str(exc)},
        ) from exc
