"""HTTP surface of AGRO-AI Intelligence Platform v1.

Machine routes authenticate with the same restricted LIVE advisory key as
``POST /v1/intelligence`` (scope ``intelligence:run``). Every resource is
owned by (organization, API project); foreign ids are 404, never 403, so the
API does not confirm another tenant's resources exist.
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1 import commercial_intelligence as legacy
from app.api.v1 import commercial_intelligence_hardened as hardened
from app.api.v1.commercial_intelligence_input_guard import reject_credentials, text_contains_credential
from app.db.base import get_db
from app.intelligence_platform import files as platform_files
from app.intelligence_platform import jobs as platform_jobs
from app.intelligence_platform import knowledge as platform_knowledge
from app.intelligence_platform import runtime as platform_runtime
from app.intelligence_platform import schemas as platform_schemas
from app.intelligence_platform import sessions as platform_sessions
from app.intelligence_platform import tools as platform_tools
from app.intelligence_platform.contract import ToolCall
from app.intelligence_platform.ownership import owned
from app.models.intelligence_commerce import CommercialIntelligenceRun
from app.platform_api.principal import PlatformPrincipal


logger = logging.getLogger("agroai.intelligence.platform")
router = APIRouter(tags=["intelligence-platform"])
API_VERSION = "2026-10-03"
_BACKGROUND: set[asyncio.Task] = set()


def _key(route_id: str, cost: int | None = None):
    def dependency(request: Request, response: Response, db: Session = Depends(get_db)) -> PlatformPrincipal:
        principal = legacy._advisory_key_principal(request, response, db, route_id=route_id, cost=cost)
        response.headers["AGROAI-API-Version"] = API_VERSION
        return principal

    return dependency


def _log(event: str, principal: PlatformPrincipal, **fields: Any) -> None:
    logger.info(
        json.dumps(
            {
                "event": event,
                "request_id": principal.request_id,
                "organization": (principal.organization_id or "")[:8],
                "project": (principal.api_project_id or "")[:8],
                **fields,
            },
            default=str,
        )
    )


# --------------------------------------------------------------------------- #
# Discovery (public, unauthenticated, cacheable).


@router.get("/intelligence/capabilities")
def capabilities(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "object": "agroai.intelligence.capabilities",
        "model": legacy.PUBLIC_MODEL,
        "api_version": API_VERSION,
        "tasks": [{"id": task_id, "name": item["label"], "price_cents": int(item["price_cents"])} for task_id, item in legacy.TASK_CATALOG.items()],
        "price_components_cents": platform_runtime.PRICE_COMPONENTS_CENTS,
        "modalities": {
            "text": True,
            "structured_context": True,
            "images": {"content_types": ["image/jpeg", "image/png", "image/webp"], "max_bytes": platform_files.IMAGE_MAX_BYTES},
            "documents": {"content_types": ["application/pdf"], "max_bytes": platform_files.PDF_MAX_BYTES, "max_pages": platform_files.MAX_PDF_PAGES},
            "text_files": {"content_types": ["text/plain", "text/csv", "text/markdown", "application/json"], "max_bytes": platform_files.TEXT_MAX_BYTES},
            "audio": False,
            "remote_urls": False,
        },
        "structured_output": {
            "builtin_schemas": [{"name": name, "description": platform_schemas.BUILTIN_DESCRIPTIONS[name]} for name in platform_schemas.BUILTIN_SCHEMAS],
            "custom_json_schema": {"draft": "2020-12", "max_bytes": platform_schemas.MAX_SCHEMA_BYTES, "unsupported_keywords": sorted(platform_schemas._FORBIDDEN_KEYWORDS)},
        },
        "tools": [tool.name for tool in platform_tools.REGISTRY.all()],
        "sessions": {"history_turns": platform_sessions.HISTORY_TURNS, "max_stored_turns": platform_sessions.MAX_STORED_TURNS, "retention_days": {"default": 30, "max": 90}},
        "knowledge": {"retrieval": "lexical_full_text", "max_document_chars": platform_knowledge.MAX_DOCUMENT_CHARS, "max_bytes_per_project": platform_knowledge.MAX_BYTES_PER_PROJECT},
        "jobs": {"max_attempts": hardened.JOB_MAX_ATTEMPTS, "result_retention_days": platform_jobs.RESULT_RETENTION_DAYS, "webhooks": False},
        "streaming": {"protocol": "server-sent-events", "granularity": "stage_events", "token_streaming": False},
        "physical_execution": False,
    }


@router.get("/intelligence/schemas/{name}")
def builtin_schema(name: str, response: Response) -> dict[str, Any]:
    schema = platform_schemas.BUILTIN_SCHEMAS.get(name)
    if schema is None:
        raise HTTPException(status_code=404, detail={"code": "schema_not_found"})
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"name": name, "description": platform_schemas.BUILTIN_DESCRIPTIONS[name], "schema": schema}


@router.get("/intelligence/tools")
def list_tools(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"object": "list", "data": [tool.public() for tool in platform_tools.REGISTRY.all()]}


class ToolExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.post("/intelligence/tools/execute")
def execute_tool(
    payload: ToolExecuteRequest,
    principal: PlatformPrincipal = Depends(_key("intelligence.tools.execute")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run one deterministic, side-effect-free tool directly. Not billed."""
    call = ToolCall(name=payload.name, arguments=payload.arguments)

    reject_credentials(SimpleNamespace(question="", input={}, context=None, tools=[call], metadata={}, response_format=None))
    platform_tools.validate_calls([call])
    result = platform_tools.execute(platform_tools.ToolContext(db=db, principal=principal), [call])[0]
    db.rollback()  # tools are read-only; never persist incidental state
    _log("intelligence.tool.executed", principal, tool=result["name"], status=result["status"], duration_ms=result["duration_ms"])
    return {"object": "agroai.tool_result", "request_id": principal.request_id, **result}


# --------------------------------------------------------------------------- #
# Synchronous run with optional SSE streaming (replaces the legacy route; the
# non-streaming contract is unchanged).


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, separators=(',', ':'))}\n\n"


@router.post("/intelligence")
async def intelligence_api(
    payload: legacy.IntelligenceRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(legacy.require_advisory_intelligence_key),
    db: Session = Depends(get_db),
):
    if not payload.stream:
        result = await legacy._execute_paid_intelligence(
            payload=payload,
            idempotency_key=idempotency_key,
            principal=principal,
            db=db,
        )
        _log("intelligence.run", principal, run_id=result.get("id"), status=result.get("status"), task=payload.task,
             charged_cents=(result.get("billing") or {}).get("charged_cents"), latency_ms=(result.get("usage") or {}).get("latency_ms"))
        return result

    # Admission (auth, references, quote, balance, idempotency) happens before
    # the stream opens so every rejection keeps its real HTTP status.
    reject_credentials(payload)
    outcome = hardened._admit_paid_run(payload=payload, idempotency_key=idempotency_key, principal=principal, db=db)
    bind = db.get_bind()
    headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Request-Id": principal.request_id or "", "AGROAI-API-Version": API_VERSION}

    if outcome.replay is not None:
        replay = outcome.replay

        async def replayed():
            yield _sse("run.completed" if replay.get("status") == "completed" else f"run.{replay.get('status') or 'completed'}", {**replay, "replayed": True})

        return StreamingResponse(replayed(), media_type="text/event-stream", headers=headers)

    admitted = outcome.admitted
    assert admitted is not None
    run_id = admitted.run_id
    queue: asyncio.Queue = asyncio.Queue()

    async def progress(event: str, data: dict[str, Any]) -> None:
        await queue.put((event, data))

    async def execute() -> None:
        # The run is owned by the server, not the connection: a client that
        # disconnects can fetch the result from GET /v1/intelligence/runs/{id}.
        # Billing is identical to a non-streamed run (charged only on completion).
        worker_db = sessionmaker(bind=bind, autocommit=False, autoflush=False)()
        try:
            run = worker_db.get(CommercialIntelligenceRun, run_id)
            try:
                fresh = hardened._readmit_paid_run(payload=payload, principal=principal, db=worker_db, run=run)
            except HTTPException as exc:
                code = exc.detail.get("code") if isinstance(exc.detail, dict) else "intelligence_reference_invalid"
                hardened._fail_unstarted_run(worker_db, run_id=run_id, code=str(code))
                raise
            result = await hardened._complete_paid_run(payload=payload, principal=principal, db=worker_db, admitted=fresh, progress=progress)
            await queue.put((f"run.{result.get('status') or 'completed'}", result))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": "intelligence_error"}
            await queue.put(("error", {"status": exc.status_code, **detail, "run_id": run_id}))
        except Exception:  # noqa: BLE001
            logger.exception("intelligence_stream_execution_failed run_id=%s", run_id)
            await queue.put(("error", {"status": 503, "code": "intelligence_temporarily_unavailable", "run_id": run_id}))
        finally:
            worker_db.close()
            await queue.put(None)

    task = asyncio.create_task(execute())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)

    async def events():
        yield _sse("run.created", {"id": run_id, "object": "agroai.intelligence", "model": legacy.PUBLIC_MODEL, "price_cents": admitted.price_cents, "request_id": principal.request_id})
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=10)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                break
            event, data = item
            yield _sse(event, data)

    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


# --------------------------------------------------------------------------- #
# Runs (sync and async) — retrieval and observability.


def _run_summary(run: CommercialIntelligenceRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "object": "agroai.intelligence.run",
        "execution": run.execution or "sync",
        "task": run.task,
        "status": platform_jobs.public_status(run),
        "price_cents": int(run.charge_cents or 0),
        "charged": run.status == "completed",
        "error_code": run.error_code,
        "latency_ms": run.latency_ms,
        "session_id": run.session_id,
        "request_id": run.request_id,
        "metadata": dict(run.metadata_json or {}),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.get("/intelligence/runs/{run_id}")
def get_run(
    run_id: str,
    principal: PlatformPrincipal = Depends(_key("intelligence.runs.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run = platform_jobs.owned_run(db, principal, run_id)
    summary = _run_summary(run)
    summary["result"] = dict(run.response_json) if run.response_json is not None else None
    return summary


@router.get("/intelligence/runs")
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    before: datetime | None = Query(default=None),
    execution: Literal["sync", "async"] | None = Query(default=None),
    principal: PlatformPrincipal = Depends(_key("intelligence.runs.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = db.query(CommercialIntelligenceRun).filter(
        CommercialIntelligenceRun.organization_id == principal.organization_id,
        CommercialIntelligenceRun.api_project_id == principal.api_project_id,
    )
    if principal.workspace_id:
        query = query.filter(CommercialIntelligenceRun.workspace_id == principal.workspace_id)
    if execution:
        query = query.filter(CommercialIntelligenceRun.execution == execution)
    if before:
        query = query.filter(CommercialIntelligenceRun.created_at < before.replace(tzinfo=None))
    rows = query.order_by(CommercialIntelligenceRun.created_at.desc()).limit(limit + 1).all()
    data = [_run_summary(row) for row in rows[:limit]]
    return {"object": "list", "data": data, "has_more": len(rows) > limit, "next_before": data[-1]["created_at"] if len(rows) > limit else None}


@router.get("/intelligence/usage")
def usage(
    days: int = Query(default=30, ge=1, le=90),
    principal: PlatformPrincipal = Depends(_key("intelligence.usage.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _usage(db, organization_id=principal.organization_id, api_project_id=principal.api_project_id, days=days, workspace_id=principal.workspace_id)


def _usage(db: Session, *, organization_id: str, api_project_id: str | None, days: int, workspace_id: str | None = None) -> dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=days)
    query = db.query(
        CommercialIntelligenceRun.task,
        CommercialIntelligenceRun.status,
        func.count(CommercialIntelligenceRun.id),
        func.coalesce(func.sum(CommercialIntelligenceRun.charge_cents), 0),
        func.avg(CommercialIntelligenceRun.latency_ms),
    ).filter(
        CommercialIntelligenceRun.organization_id == organization_id,
        CommercialIntelligenceRun.created_at >= since,
    )
    if api_project_id:
        query = query.filter(CommercialIntelligenceRun.api_project_id == api_project_id)
    if workspace_id:
        query = query.filter(CommercialIntelligenceRun.workspace_id == workspace_id)
    rows = query.group_by(CommercialIntelligenceRun.task, CommercialIntelligenceRun.status).all()
    by_task: dict[str, dict[str, Any]] = {}
    totals = {"runs": 0, "completed": 0, "charged_cents": 0, "not_charged": 0}
    for task, run_status, count, cents, avg_latency in rows:
        item = by_task.setdefault(task, {"task": task, "runs": 0, "completed": 0, "charged_cents": 0, "by_status": {}, "avg_latency_ms": None})
        public = "running" if run_status == "processing" else run_status
        item["runs"] += int(count)
        item["by_status"][public] = item["by_status"].get(public, 0) + int(count)
        totals["runs"] += int(count)
        if run_status == "completed":
            item["completed"] += int(count)
            item["charged_cents"] += int(cents)
            totals["completed"] += int(count)
            totals["charged_cents"] += int(cents)
            item["avg_latency_ms"] = int(avg_latency) if avg_latency is not None else None
        else:
            totals["not_charged"] += int(count)
    return {"object": "agroai.intelligence.usage", "period_days": days, "since": since.isoformat(), "totals": totals, "by_task": sorted(by_task.values(), key=lambda item: item["task"])}


# --------------------------------------------------------------------------- #
# Async jobs.


@router.post("/intelligence/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(
    payload: legacy.IntelligenceRequest,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255),
    principal: PlatformPrincipal = Depends(_key("intelligence.jobs.create")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if payload.stream:
        raise HTTPException(status_code=422, detail={"code": "stream_not_supported_for_jobs"})
    reject_credentials(payload)
    outcome = hardened._admit_paid_run(
        payload=payload, idempotency_key=idempotency_key, principal=principal, db=db, execution="async"
    )
    run = (
        db.query(CommercialIntelligenceRun)
        .filter(
            CommercialIntelligenceRun.organization_id == principal.organization_id,
            CommercialIntelligenceRun.api_project_id == principal.api_project_id,
            CommercialIntelligenceRun.idempotency_key == idempotency_key,
        )
        .one()
    )
    if outcome.admitted is not None:
        platform_jobs.dispatch(run.id, run.organization_id)
        _log("intelligence.job.created", principal, run_id=run.id, task=payload.task, price_cents=outcome.admitted.price_cents)
    else:
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = f"/v1/intelligence/jobs/{run.id}"
    return platform_jobs.job_public(run)


@router.get("/intelligence/jobs/{job_id}")
def get_job(
    job_id: str,
    principal: PlatformPrincipal = Depends(_key("intelligence.jobs.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return platform_jobs.job_public(platform_jobs.owned_run(db, principal, job_id, execution="async"))


@router.get("/intelligence/jobs")
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    job_status: Literal["queued", "running", "completed", "degraded", "failed", "canceled", "timeout"] | None = Query(default=None, alias="status"),
    principal: PlatformPrincipal = Depends(_key("intelligence.jobs.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = db.query(CommercialIntelligenceRun).filter(
        CommercialIntelligenceRun.organization_id == principal.organization_id,
        CommercialIntelligenceRun.api_project_id == principal.api_project_id,
        CommercialIntelligenceRun.execution == "async",
    )
    if principal.workspace_id:
        query = query.filter(CommercialIntelligenceRun.workspace_id == principal.workspace_id)
    if job_status:
        query = query.filter(CommercialIntelligenceRun.status == ("processing" if job_status == "running" else job_status))
    rows = query.order_by(CommercialIntelligenceRun.created_at.desc()).limit(limit).all()
    return {"object": "list", "data": [platform_jobs.job_public(row) | {"result": None} for row in rows]}


@router.post("/intelligence/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    principal: PlatformPrincipal = Depends(_key("intelligence.jobs.cancel")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run = platform_jobs.cancel(db, principal, job_id)
    _log("intelligence.job.cancel", principal, run_id=run.id, status=run.status)
    return platform_jobs.job_public(run)


# --------------------------------------------------------------------------- #
# Sessions.


@router.post("/intelligence/sessions", status_code=status.HTTP_201_CREATED)
def create_session(
    payload: platform_sessions.SessionCreate,
    principal: PlatformPrincipal = Depends(_key("intelligence.sessions.write")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    reject_credentials(SimpleNamespace(question="", input={}, context=payload.context, tools=[], metadata=payload.metadata, response_format=None))
    row = platform_sessions.create_session(db, principal, payload)
    return platform_sessions.public_session(row)


@router.get("/intelligence/sessions")
def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    principal: PlatformPrincipal = Depends(_key("intelligence.sessions.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.models.intelligence_platform import IntelligenceSession

    rows = (
        owned(db.query(IntelligenceSession), IntelligenceSession, principal)
        .filter(
            IntelligenceSession.status == "active",
            IntelligenceSession.expires_at > datetime.utcnow(),
        )
        .order_by(IntelligenceSession.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"object": "list", "data": [platform_sessions.public_session(row) for row in rows]}


@router.get("/intelligence/sessions/{session_id}")
def get_session(
    session_id: str,
    principal: PlatformPrincipal = Depends(_key("intelligence.sessions.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return platform_sessions.public_session(platform_sessions.owned_session(db, principal, session_id))


@router.patch("/intelligence/sessions/{session_id}")
def update_session(
    session_id: str,
    payload: platform_sessions.SessionUpdate,
    principal: PlatformPrincipal = Depends(_key("intelligence.sessions.write")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    reject_credentials(SimpleNamespace(question="", input={}, context=payload.context, tools=[], metadata=payload.metadata or {}, response_format=None))
    return platform_sessions.public_session(platform_sessions.update_session(db, principal, session_id, payload))


@router.get("/intelligence/sessions/{session_id}/turns")
def session_turns(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    principal: PlatformPrincipal = Depends(_key("intelligence.sessions.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"object": "list", "data": platform_sessions.turns(db, principal, session_id, limit=limit)}


@router.delete("/intelligence/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    principal: PlatformPrincipal = Depends(_key("intelligence.sessions.write")),
    db: Session = Depends(get_db),
) -> Response:
    platform_sessions.delete_session(db, principal, session_id)
    _log("intelligence.session.deleted", principal, session_id=session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Files.


@router.post("/intelligence/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    purpose: Literal["attachment", "knowledge"] = Form(default="attachment"),
    principal: PlatformPrincipal = Depends(_key("intelligence.files.upload", cost=5)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = await platform_files.accept_upload(db, principal, file, purpose=purpose)
    if row.extracted_text and text_contains_credential(row.extracted_text):
        platform_files.delete_file(db, principal, row.id)
        raise HTTPException(
            status_code=422,
            detail={"code": "credential_like_input_rejected", "message": "The file appears to contain a credential or private key. Remove it and upload again."},
        )
    _log("intelligence.file.uploaded", principal, file_id=row.id, kind=row.kind, size_bytes=row.size_bytes)
    return platform_files.public_file(row)


@router.get("/intelligence/files")
def list_files(
    limit: int = Query(default=50, ge=1, le=200),
    principal: PlatformPrincipal = Depends(_key("intelligence.files.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.models.intelligence_platform import IntelligenceFile

    rows = (
        owned(db.query(IntelligenceFile), IntelligenceFile, principal)
        .filter(
            IntelligenceFile.status == "available",
            IntelligenceFile.expires_at > datetime.utcnow(),
        )
        .order_by(IntelligenceFile.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"object": "list", "data": [platform_files.public_file(row) for row in rows]}


@router.get("/intelligence/files/{file_id}")
def get_file(
    file_id: str,
    principal: PlatformPrincipal = Depends(_key("intelligence.files.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return platform_files.public_file(platform_files.owned_file(db, principal, file_id))


@router.delete("/intelligence/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    file_id: str,
    principal: PlatformPrincipal = Depends(_key("intelligence.files.write")),
    db: Session = Depends(get_db),
) -> Response:
    platform_files.delete_file(db, principal, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Knowledge.


@router.post("/intelligence/knowledge/documents", status_code=status.HTTP_201_CREATED)
def create_document(
    payload: platform_knowledge.KnowledgeDocumentCreate,
    response: Response,
    principal: PlatformPrincipal = Depends(_key("intelligence.knowledge.write", cost=5)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if payload.text and text_contains_credential(payload.text):
        raise HTTPException(status_code=422, detail={"code": "credential_like_input_rejected"})
    document, changed = platform_knowledge.ingest(db, principal, payload)
    if not changed:
        response.status_code = status.HTTP_200_OK
    _log("intelligence.knowledge.ingested", principal, document_id=document.id, chunks=document.chunk_count, changed=changed)
    return platform_knowledge.public_document(document)


@router.get("/intelligence/knowledge/documents")
def list_documents(
    collection: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    principal: PlatformPrincipal = Depends(_key("intelligence.knowledge.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.models.intelligence_platform import KnowledgeDocument

    query = owned(db.query(KnowledgeDocument), KnowledgeDocument, principal)
    if collection:
        query = query.filter(KnowledgeDocument.collection == collection)
    rows = query.order_by(KnowledgeDocument.created_at.desc()).limit(limit).all()
    return {"object": "list", "data": [platform_knowledge.public_document(row) for row in rows]}


@router.get("/intelligence/knowledge/collections")
def list_collections(
    principal: PlatformPrincipal = Depends(_key("intelligence.knowledge.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"object": "list", "data": platform_knowledge.known_collections(db, principal)}


@router.get("/intelligence/knowledge/documents/{document_id}")
def get_document(
    document_id: str,
    principal: PlatformPrincipal = Depends(_key("intelligence.knowledge.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return platform_knowledge.public_document(platform_knowledge.owned_document(db, principal, document_id))


@router.delete("/intelligence/knowledge/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    principal: PlatformPrincipal = Depends(_key("intelligence.knowledge.write")),
    db: Session = Depends(get_db),
) -> Response:
    platform_knowledge.delete_document(db, principal, document_id)
    _log("intelligence.knowledge.deleted", principal, document_id=document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/intelligence/knowledge/search")
def search_knowledge(
    payload: platform_knowledge.KnowledgeSearchRequest,
    principal: PlatformPrincipal = Depends(_key("intelligence.knowledge.search")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    hits = platform_knowledge.search(db, principal, collections=payload.collections, query=payload.query, max_results=payload.max_results)
    return {"object": "list", "query": payload.query, "data": hits}


# --------------------------------------------------------------------------- #
# Developer console (verified browser session; same project as self-serve keys).


def _console_dependency():
    from app.api.v1.commercial_intelligence_selfserve import require_commercial_intelligence_browser

    return require_commercial_intelligence_browser


@router.get("/platform/developer/intelligence/usage")
def console_usage(
    days: int = Query(default=30, ge=1, le=90),
    ctx=Depends(_console_dependency()),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _usage(db, organization_id=ctx.organization.id, api_project_id=None, days=days)


@router.get("/platform/developer/intelligence/runs")
def console_runs(
    limit: int = Query(default=20, ge=1, le=50),
    ctx=Depends(_console_dependency()),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        db.query(CommercialIntelligenceRun)
        .filter(CommercialIntelligenceRun.organization_id == ctx.organization.id)
        .order_by(CommercialIntelligenceRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"object": "list", "data": [_run_summary(row) for row in rows]}
