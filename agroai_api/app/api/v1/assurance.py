"""Assurance Passport API routes."""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.assurance.repository import AssuranceRepository
from app.api.deps import get_current_user, require_workspace_access
from app.assurance.rule_packs import CUSTOMER_RULE_PACK_IDS, DEFAULT_RULE_PACKS
from app.db.base import get_db
from app.models.saas import Organization, User, Workspace
from app.services.assurance_rollout import assurance_access
from app.services.assurance_artifacts import assurance_artifact_content
from app.services.api_key_service import APIKeyService
from app.services.commercial_control import require_feature
from app.services.quota import commit_reservation, release_reservation, reserve_quota

router = APIRouter(prefix="/assurance", tags=["assurance"])
portal_router = APIRouter(tags=["assurance-portal"])


class AssuranceContext:
    def __init__(self, repo: AssuranceRepository):
        self.repo = repo


def _reject_org_mismatch(header_value: str | None, tenant_id: str) -> None:
    if header_value and header_value != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="X-Organization-Id does not match authenticated assurance tenant")


def _context(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
) -> AssuranceContext:
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assurance requires a verified server-side API key")
    api_key = APIKeyService.verify_api_key(db, x_api_key)
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid assurance API key")
    _reject_org_mismatch(x_organization_id, str(api_key.tenant_id))
    repo = AssuranceRepository(db, str(api_key.tenant_id))
    repo.ensure_rule_packs()
    return AssuranceContext(repo)


class PassportIn(BaseModel):
    farm_name: str
    farm_location: str | None = None
    crop: str | None = None
    season: str | None = None
    reporting_period: str | None = None
    jurisdiction_id: str | None = None
    parcel_ids: list[str] = Field(default_factory=list)
    rule_pack_ids: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    entity_type: str = "farm"
    entity_id: str | None = None


class EvidenceIn(BaseModel):
    evidence_type: str
    proof_domain: str | None = None
    file_ref: str
    filename: str | None = None
    content_type: str | None = None
    checksum: str | None = None
    truth_label: str = "reported"
    review_status: str = "pending_review"
    source_system: str = "uploaded"
    compliance_evidence_id: str | None = None
    workbench_artifact_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("truth_label")
    @classmethod
    def _truth_label(cls, value: str) -> str:
        if value not in {"measured", "reported", "estimated", "calculated", "AI-inferred"}:
            raise ValueError("unsupported truth_label")
        return value


class InputApplicationIn(BaseModel):
    application_type: Literal["input", "pesticide", "fertilizer"] = "input"
    applied_at: str | None = None
    block_id: str | None = None
    parcel_id: str | None = None
    product_name: str
    quantity: float | None = None
    unit: str | None = None
    operator: str | None = None
    truth_label: str = "reported"
    evidence_artifact_id: str | None = None
    active_ingredient: str | None = None
    target_pest: str | None = None
    reentry_interval_hours: float | None = None
    preharvest_interval_days: float | None = None
    label_reference: str | None = None
    nutrient_profile: dict[str, Any] = Field(default_factory=dict)
    nitrogen_kg: float | None = None
    phosphorus_kg: float | None = None
    potassium_kg: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HarvestLotIn(BaseModel):
    lot_code: str
    crop: str | None = None
    variety: str | None = None
    harvested_at: str | None = None
    block_id: str | None = None
    parcel_id: str | None = None
    quantity: float | None = None
    unit: str | None = None
    destination: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceabilityEventIn(BaseModel):
    harvest_lot_id: str | None = None
    event_type: str
    occurred_at: str | None = None
    location: str | None = None
    actor: str | None = None
    evidence_artifact_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ExportIn(BaseModel):
    export_type: Literal["pdf"] = "pdf"


class EvidenceMappingIn(BaseModel):
    source_kind: Literal["canonical_evidence", "field_observation"]
    source_id: str
    evidence_type: str | None = None
    proof_domain: str | None = None
    truth_label: str | None = None
    reporting_period: str | None = None
    stale_after: str | None = None
    unresolved_issue: str | None = None
    mapping_note: str | None = None
    requirement_keys: list[str] = Field(default_factory=list)


class ReviewIn(BaseModel):
    action: Literal[
        "accept_mapping",
        "reject_mapping",
        "correct_metadata",
        "request_additional_proof",
        "mark_not_applicable",
        "reopen",
    ]
    evidence_mapping_id: str | None = None
    checklist_item_id: str | None = None
    reason: str | None = None
    actor_label: str | None = None
    corrections: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PackageIn(BaseModel):
    package_type: Literal[
        "assurance_passport",
        "water_evidence_pack",
        "buyer_proof_pack",
        "input_application_record_pack",
        "operational_execution_pack",
    ] = "assurance_passport"
    export_type: Literal["pdf"] = "pdf"
    idempotency_key: str | None = Field(default=None, max_length=120)


class AgentRunIn(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=120)


class FieldTaskIn(BaseModel):
    requirement_key: str
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    assignee: str | None = Field(default=None, max_length=200)
    due_at: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=64)


class PortalAssuranceContext:
    def __init__(self, repo: AssuranceRepository, workspace: Workspace, organization: Organization):
        self.repo = repo
        self.workspace = workspace
        self.organization = organization


def _portal_context(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortalAssuranceContext:
    workspace, membership = require_workspace_access(workspace_id, user, db)
    if membership.status != "active":
        raise HTTPException(status_code=404, detail="Workspace not found")
    organization = workspace.organization
    allowed, release_state, cohort = assurance_access(db, organization, user_email=user.email)
    if not allowed:
        raise HTTPException(
            status_code=404,
            detail={"code": "assurance_not_available", "release_state": release_state, "cohort": cohort},
        )
    repo = AssuranceRepository.for_workspace(
        db,
        organization_id=str(organization.id),
        workspace_id=str(workspace.id),
        actor_user_id=str(user.id),
    )
    repo.ensure_rule_packs()
    return PortalAssuranceContext(repo, workspace, organization)


def _feature(context: PortalAssuranceContext, feature_key: str, *, allow_preview: bool = False) -> None:
    require_feature(
        context.repo.db,
        context.organization,
        feature_key,
        recommended_plan="professional" if feature_key != "assurance.review" else "team",
        allow_preview=allow_preview,
    )


OperationResult = TypeVar("OperationResult")


def _quota_request_id(
    context: PortalAssuranceContext,
    *,
    operation: str,
    passport_id: str,
    client_key: str | None,
) -> str:
    logical_key = client_key or uuid.uuid4().hex
    source = (
        f"{context.organization.id}|{context.workspace.id}|{passport_id}|"
        f"{operation}|{logical_key}"
    )
    return f"assurance:{operation}:{hashlib.sha256(source.encode()).hexdigest()}"


def _metered_operation(
    context: PortalAssuranceContext,
    *,
    metric: Literal["agent_run", "report_export"],
    request_id: str,
    passport_id: str,
    operation: Callable[[], OperationResult],
) -> OperationResult:
    """Execute the product mutation and usage commit in one outer transaction.

    The reservation stays outside the nested operation savepoint. A failed
    product mutation can therefore roll back all partial rows, persist a
    released reservation, and leave both committed usage and quota snapshots
    truthful. Successful idempotent replays reuse the canonical reservation
    and UsageEvent rather than charging twice.
    """

    db = context.repo.db
    reservation = reserve_quota(
        db,
        context.organization,
        metric,
        workspace_id=str(context.workspace.id),
        user_id=context.repo.actor_user_id,
        request_id=request_id,
        metadata={
            "product": "assurance_intelligence_v2",
            "passport_id": passport_id,
            "operation": metric,
        },
    )
    try:
        with db.begin_nested():
            result = operation()
            commit_reservation(
                db,
                reservation,
                event_type=metric,
                metadata={"passport_id": passport_id},
            )
        db.commit()
        return result
    except Exception:
        # A healthy outer transaction still contains the reservation while the
        # nested operation has been rolled back. If the database invalidated
        # the entire transaction, rollback removes the uncommitted reservation
        # and therefore cannot leave capacity stranded.
        if db.is_active:
            try:
                release_reservation(db, reservation, reason="assurance_operation_failed")
                db.commit()
            except Exception:  # noqa: BLE001 - preserve the original operation error
                db.rollback()
        else:
            db.rollback()
        raise


@router.get("/rule-packs")
def rule_packs(_: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    return {"rule_packs": DEFAULT_RULE_PACKS}


@router.post("/passports", status_code=201)
def create_passport(payload: PassportIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.create_passport(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/passports/{passport_id}")
def get_passport(passport_id: str, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.get_passport(passport_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@router.post("/passports/{passport_id}/evidence", status_code=201)
def add_evidence(passport_id: str, payload: EvidenceIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.add_evidence(passport_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/passports/{passport_id}/input-applications", status_code=201)
def add_input_application(passport_id: str, payload: InputApplicationIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.add_input_application(passport_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/passports/{passport_id}/harvest-lots", status_code=201)
def add_harvest_lot(passport_id: str, payload: HarvestLotIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.add_harvest_lot(passport_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@router.post("/passports/{passport_id}/traceability-events", status_code=201)
def add_traceability_event(passport_id: str, payload: TraceabilityEventIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.add_traceability_event(passport_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/passports/{passport_id}/readiness")
def readiness(passport_id: str, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    try:
        return context.repo.readiness(passport_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@router.post("/passports/{passport_id}/exports", status_code=201)
def create_export(passport_id: str, payload: ExportIn, context: AssuranceContext = Depends(_context)) -> dict[str, Any]:
    if payload.export_type != "pdf":
        raise HTTPException(status_code=422, detail="Only PDF Assurance Passport export is available in this MVP")
    try:
        return context.repo.export_pdf(passport_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@portal_router.get("/workspaces/{workspace_id}/assurance/rule-packs")
def portal_rule_packs(context: PortalAssuranceContext = Depends(_portal_context)) -> dict[str, Any]:
    _feature(context, "assurance.readiness", allow_preview=True)
    return {"rule_packs": {key: DEFAULT_RULE_PACKS[key] for key in CUSTOMER_RULE_PACK_IDS}}


@portal_router.get("/workspaces/{workspace_id}/assurance/passports")
def portal_list_passports(context: PortalAssuranceContext = Depends(_portal_context)) -> dict[str, Any]:
    _feature(context, "assurance.readiness", allow_preview=True)
    return {"passports": context.repo.list_passports()}


@portal_router.post("/workspaces/{workspace_id}/assurance/passports", status_code=201)
def portal_create_passport(
    payload: PassportIn,
    context: PortalAssuranceContext = Depends(_portal_context),
) -> dict[str, Any]:
    _feature(context, "assurance.readiness", allow_preview=True)
    try:
        return context.repo.create_passport(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@portal_router.get("/workspaces/{workspace_id}/assurance/passports/{passport_id}")
def portal_get_passport(
    passport_id: str,
    context: PortalAssuranceContext = Depends(_portal_context),
) -> dict[str, Any]:
    _feature(context, "assurance.readiness", allow_preview=True)
    try:
        return context.repo.get_passport(passport_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@portal_router.get("/workspaces/{workspace_id}/assurance/evidence-candidates")
def portal_evidence_candidates(context: PortalAssuranceContext = Depends(_portal_context)) -> dict[str, Any]:
    _feature(context, "assurance.evidence_mapping")
    return context.repo.evidence_candidates()


@portal_router.post("/workspaces/{workspace_id}/assurance/passports/{passport_id}/evidence-mappings", status_code=201)
def portal_map_evidence(
    passport_id: str,
    payload: EvidenceMappingIn,
    context: PortalAssuranceContext = Depends(_portal_context),
) -> dict[str, Any]:
    _feature(context, "assurance.evidence_mapping")
    try:
        return context.repo.map_evidence(passport_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport or evidence source not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@portal_router.get("/workspaces/{workspace_id}/assurance/passports/{passport_id}/readiness")
def portal_readiness(
    passport_id: str,
    context: PortalAssuranceContext = Depends(_portal_context),
) -> dict[str, Any]:
    _feature(context, "assurance.readiness", allow_preview=True)
    try:
        return context.repo.readiness(passport_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@portal_router.get("/workspaces/{workspace_id}/assurance/passports/{passport_id}/review-queue")
def portal_review_queue(
    passport_id: str,
    context: PortalAssuranceContext = Depends(_portal_context),
) -> dict[str, Any]:
    _feature(context, "assurance.review")
    try:
        return {"review_queue": context.repo.review_queue(passport_id), "events": context.repo.list_review_events(passport_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@portal_router.post("/workspaces/{workspace_id}/assurance/passports/{passport_id}/reviews", status_code=201)
def portal_review(
    passport_id: str,
    payload: ReviewIn,
    context: PortalAssuranceContext = Depends(_portal_context),
) -> dict[str, Any]:
    _feature(context, "assurance.review")
    try:
        return context.repo.review(passport_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport, mapping, or requirement not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@portal_router.get("/workspaces/{workspace_id}/assurance/passports/{passport_id}/packages")
def portal_list_packages(
    passport_id: str,
    context: PortalAssuranceContext = Depends(_portal_context),
) -> dict[str, Any]:
    _feature(context, "assurance.exports")
    try:
        return {"packages": context.repo.list_exports(passport_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@portal_router.post("/workspaces/{workspace_id}/assurance/passports/{passport_id}/packages", status_code=201)
def portal_create_package(
    passport_id: str,
    payload: PackageIn,
    context: PortalAssuranceContext = Depends(_portal_context),
) -> dict[str, Any]:
    _feature(context, "assurance.exports")
    request_id = _quota_request_id(
        context,
        operation="package",
        passport_id=passport_id,
        client_key=payload.idempotency_key,
    )
    try:
        result = _metered_operation(
            context,
            metric="report_export",
            request_id=request_id,
            passport_id=passport_id,
            operation=lambda: context.repo.create_package(
                passport_id,
                payload.model_dump(),
                commit=False,
            ),
        )
        context.repo.promote_staged_artifacts()
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@portal_router.get(
    "/workspaces/{workspace_id}/assurance/passports/{passport_id}/packages/{package_id}/download"
)
def portal_download_package(
    passport_id: str,
    package_id: str,
    context: PortalAssuranceContext = Depends(_portal_context),
) -> Response:
    _feature(context, "assurance.exports")
    try:
        package, artifact = context.repo.package_artifact(passport_id, package_id)
        content, size_bytes, filename = assurance_artifact_content(
            artifact,
            organization_id=str(context.organization.id),
            workspace_id=str(context.workspace.id),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Proof package not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_filename}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "ETag": f'"{package.checksum}"',
    }
    if size_bytes > 0:
        headers["Content-Length"] = str(size_bytes)
    if isinstance(content, bytes):
        return Response(content=content, media_type="application/pdf", headers=headers)
    return StreamingResponse(content, media_type="application/pdf", headers=headers)


@portal_router.get("/workspaces/{workspace_id}/assurance/passports/{passport_id}/agent/runs")
def portal_list_agent_runs(
    passport_id: str,
    context: PortalAssuranceContext = Depends(_portal_context),
) -> dict[str, Any]:
    _feature(context, "assurance.agent")
    try:
        return {"runs": context.repo.list_agent_runs(passport_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc


@portal_router.post(
    "/workspaces/{workspace_id}/assurance/passports/{passport_id}/agent/runs",
    status_code=201,
)
def portal_run_agent(
    passport_id: str,
    payload: AgentRunIn | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=120),
    context: PortalAssuranceContext = Depends(_portal_context),
) -> dict[str, Any]:
    _feature(context, "assurance.agent")
    body_key = payload.idempotency_key if payload else None
    if body_key and idempotency_key and body_key != idempotency_key:
        raise HTTPException(status_code=422, detail="Body and Idempotency-Key header must match")
    request_id = _quota_request_id(
        context,
        operation="agent",
        passport_id=passport_id,
        client_key=idempotency_key or body_key,
    )
    try:
        return _metered_operation(
            context,
            metric="agent_run",
            request_id=request_id,
            passport_id=passport_id,
            operation=lambda: context.repo.run_agent(
                passport_id,
                request_id=request_id,
                commit=False,
            ),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@portal_router.post("/workspaces/{workspace_id}/assurance/passports/{passport_id}/actions", status_code=201)
def portal_create_field_task(
    passport_id: str,
    payload: FieldTaskIn,
    context: PortalAssuranceContext = Depends(_portal_context),
) -> dict[str, Any]:
    _feature(context, "assurance.agent")
    try:
        return context.repo.create_field_task(passport_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Passport or requirement not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
