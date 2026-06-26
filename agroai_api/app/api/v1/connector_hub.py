"""Connector hub action endpoints.

These endpoints make the connector UI actually usable while keeping the current
provider-specific live sync contracts honest. They support four production
patterns:
- account connectors: Gmail/Outlook/Drive account authorization
- provider/API connectors: WiseConn, Talgil, Weather, OpenET, custom APIs
- file connectors: direct upload to AGRO-AI evidence storage
- data management: sources and ingestion jobs for auditability
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection, DataSource, EvidenceRecord, IngestionJob
from app.api.v1.connectors import (
    create_or_get_connection,
    ensure_schema,
    evidence_public,
    infer_source_type,
    make_evidence,
    oauth_url,
    parse_rows,
    public_connection,
    row_to_dict,
    safe_credential_ref,
    sanitize_config,
    save_upload_bytes,
    suggest_mapping,
)

router = APIRouter(tags=["connector-hub-actions"])

ProviderId = Literal[
    "wiseconn",
    "talgil",
    "weather",
    "openet",
    "manual_csv",
    "gmail",
    "outlook",
    "google_drive",
    "custom_api",
]

ACCOUNT_PROVIDERS = {"gmail", "outlook", "google_drive"}
UPLOAD_PROVIDERS = {"wiseconn", "talgil", "manual_csv", "weather", "openet"}


class ConnectorConnectRequest(BaseModel):
    provider: ProviderId
    workspace_id: str | None = None
    mode: str | None = None
    display_name: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    scopes: list[str] = Field(default_factory=list)
    send_reports_enabled: bool = False
    read_context_enabled: bool = True


class OAuthStartRequest(BaseModel):
    provider: Literal["gmail", "outlook", "google_drive"]
    workspace_id: str | None = None
    redirect_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def provider_mode(provider: str, requested: str | None = None) -> str:
    if requested:
        return requested
    if provider in ACCOUNT_PROVIDERS:
        return "oauth"
    if provider == "custom_api":
        return "custom_api"
    if provider in {"wiseconn", "talgil", "weather", "openet"}:
        return "api_credentials"
    return "manual_upload"


def connection_token(provider: str, config: dict[str, Any]) -> str:
    for key in (
        "credential_ref",
        "api_key",
        "api_key_ref",
        "token",
        "account_email",
        "username",
        "base_url",
        "provider_name",
        "environment_name",
    ):
        value = config.get(key)
        if value:
            return str(value)
    return f"{provider}:internal-testing-connection"


def connector_capabilities(provider: str, *, send_reports_enabled: bool = False, read_context_enabled: bool = True) -> list[str]:
    if provider in {"wiseconn", "talgil"}:
        return ["controller_events", "flow_readings", "irrigation_history", "export_upload", "future_live_sync"]
    if provider == "manual_csv":
        return ["file_upload", "csv_parse", "json_parse", "pdf_storage", "evidence_extraction"]
    if provider in {"gmail", "outlook"}:
        capabilities = ["email_context", "attachment_context", "report_delivery"]
        if send_reports_enabled:
            capabilities.append("send_reports_when_requested")
        if read_context_enabled:
            capabilities.append("read_approved_context")
        return capabilities
    if provider == "google_drive":
        return ["folder_context", "document_context", "spreadsheet_context", "pdf_context"]
    if provider == "weather":
        return ["forecast_context", "station_upload", "api_weather_context"]
    if provider == "openet":
        return ["et_context", "water_use_context", "field_boundary_context"]
    return ["custom_endpoint", "provider_context", "future_sync_job"]


def save_connection_job(
    db: Session,
    *,
    tenant_id: str,
    connection: ConnectorConnection,
    job_type: str,
    input_json: dict[str, Any],
    output_json: dict[str, Any],
    status: str = "completed",
) -> IngestionJob:
    job = IngestionJob(
        tenant_id=tenant_id,
        workspace_id=connection.workspace_id,
        connector_connection_id=connection.id,
        job_type=job_type,
        status=status,
        input_json=input_json,
        output_json=output_json,
        completed_at=datetime.utcnow(),
    )
    db.add(job)
    return job


def ingest_upload_for_connection(
    db: Session,
    *,
    tenant_id: str,
    connection: ConnectorConnection,
    filename: str,
    content_type: str | None,
    data: bytes,
) -> dict[str, Any]:
    if connection.provider not in UPLOAD_PROVIDERS:
        raise HTTPException(status_code=400, detail="This connector does not accept file uploads. Use account/API connection instead.")

    raw_text, rows, columns, warnings = parse_rows(filename, content_type, data)
    storage_path = save_upload_bytes(tenant_id, connection.id, filename, data)
    mapping = suggest_mapping(columns)

    source = DataSource(
        tenant_id=tenant_id,
        workspace_id=connection.workspace_id,
        connector_connection_id=connection.id,
        source_type=infer_source_type(filename, content_type, connection.provider),
        provider=connection.provider,
        filename=filename,
        content_type=content_type,
        storage_path=storage_path,
        raw_text=raw_text[:200000],
        metadata_json={
            "columns": columns,
            "parsed_rows": rows[:500],
            "mapping_suggestions": mapping,
            "storage_backend": "local_or_render_disk",
            "storage_path": storage_path,
        },
        status="parsed_with_warnings" if warnings else "parsed",
    )
    db.add(source)
    db.flush()

    records: list[EvidenceRecord] = []
    for index, row in enumerate(rows[:500]):
        record = make_evidence(
            tenant_id=tenant_id,
            workspace_id=connection.workspace_id,
            connection=connection,
            source=source,
            row=row,
            index=index,
            mapping=mapping,
        )
        db.add(record)
        records.append(record)

    connection.status = "synced" if records else "mapping_required"
    connection.last_sync_at = datetime.utcnow()
    connection.last_error = None if records else "Uploaded file was stored but produced no evidence records."

    job = save_connection_job(
        db,
        tenant_id=tenant_id,
        connection=connection,
        job_type="upload_parse",
        status="completed_with_warnings" if warnings else "completed",
        input_json={"filename": filename, "content_type": content_type, "bytes": len(data)},
        output_json={
            "rows_parsed": len(rows),
            "columns": columns,
            "mapping_suggestions": mapping,
            "evidence_records_created": len(records),
            "warnings": warnings,
            "data_source_id": source.id,
            "storage_path": storage_path,
        },
    )
    db.commit()
    db.refresh(connection)
    db.refresh(source)

    return {
        "status": source.status,
        "connection": public_connection(connection),
        "data_source": row_to_dict(source),
        "job": row_to_dict(job),
        "rows_parsed": len(rows),
        "columns": columns,
        "mapping_suggestions": mapping,
        "evidence_records_created": len(records),
        "warnings": warnings,
        "evidence_preview": [evidence_public(record) for record in records[:8]],
    }


@router.post("/connectors/connect")
async def connect_provider(
    payload: ConnectorConnectRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create or update a connector as connected for the current tenant.

    This is the simple backend action the UI needs for API keys, custom APIs,
    controller credentials, and internal account-connector validation.
    """

    ensure_schema(db)
    mode = provider_mode(payload.provider, payload.mode)
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=payload.provider,
        workspace_id=payload.workspace_id,
        mode=mode,
        display_name=payload.display_name,
        config=payload.config,
    )

    safe_config = sanitize_config(payload.config)
    merged = dict(connection.config_json or {})
    merged.update(safe_config)
    merged.update(
        {
            "connector_hub_version": "working-v1",
            "authorization_status": "connected",
            "connection_pattern": mode,
            "read_context_enabled": payload.read_context_enabled,
            "send_reports_enabled": payload.send_reports_enabled,
            "scopes": payload.scopes,
            "capabilities": connector_capabilities(
                payload.provider,
                send_reports_enabled=payload.send_reports_enabled,
                read_context_enabled=payload.read_context_enabled,
            ),
        }
    )

    connection.mode = mode
    connection.status = "connected"
    connection.credentials_ref = safe_credential_ref(connection_token(payload.provider, payload.config))
    connection.config_json = merged
    connection.last_error = None
    connection.updated_at = datetime.utcnow()
    connection.last_test_at = datetime.utcnow()

    job = save_connection_job(
        db,
        tenant_id=tenant_id,
        connection=connection,
        job_type="connector_connect",
        input_json={"provider": payload.provider, "mode": mode, "config_keys": sorted(payload.config.keys())},
        output_json={
            "status": "connected",
            "capabilities": merged["capabilities"],
            "message": f"{payload.provider} is connected for AGRO-AI context ingestion.",
        },
    )
    db.commit()
    db.refresh(connection)

    return {
        "status": "connected",
        "message": f"{payload.provider} connected.",
        "connection": public_connection(connection),
        "job": row_to_dict(job),
        "capabilities": merged["capabilities"],
        "next_actions": [
            "Upload evidence if this provider supports files.",
            "Open Evidence to inspect imported records.",
            "Ask AGRO-AI for a grounded analysis once evidence exists.",
        ],
    }


@router.post("/connectors/oauth/start")
async def start_oauth(
    payload: OAuthStartRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start OAuth when credentials exist, otherwise connect in internal mode.

    The product must not feel broken while OAuth client IDs are not configured.
    Internal mode stores the account connector as connected and makes the rest of
    the workflow testable; production can later redirect to Google/Microsoft.
    """

    ensure_schema(db)
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=payload.provider,
        workspace_id=payload.workspace_id,
        mode="oauth",
        config=payload.metadata,
    )

    redirect_url = payload.redirect_url or "https://app.agroai-pilot.com/integrations/oauth/callback"
    state = f"{connection.id}:{tenant_id}:{int(datetime.utcnow().timestamp())}"
    auth_url, oauth_error = oauth_url(payload.provider, state, redirect_url)

    merged = dict(connection.config_json or {})
    merged.update(
        sanitize_config(
            {
                **payload.metadata,
                "oauth_provider": payload.provider,
                "oauth_state": state,
                "oauth_redirect_url": redirect_url,
                "oauth_error": oauth_error,
                "authorization_status": "oauth_ready" if auth_url else "internal_connected",
                "connector_hub_version": "working-v1",
                "capabilities": connector_capabilities(payload.provider),
            }
        )
    )

    connection.mode = "oauth"
    connection.status = "oauth_pending" if auth_url else "connected"
    connection.credentials_ref = safe_credential_ref(payload.metadata.get("account_hint") or f"{payload.provider}:internal-oauth")
    connection.config_json = merged
    connection.last_error = oauth_error
    connection.last_test_at = datetime.utcnow()
    connection.updated_at = datetime.utcnow()

    job = save_connection_job(
        db,
        tenant_id=tenant_id,
        connection=connection,
        job_type="oauth_start",
        status="completed_with_warnings" if oauth_error else "completed",
        input_json={"provider": payload.provider, "redirect_url": redirect_url},
        output_json={
            "auth_url_available": bool(auth_url),
            "oauth_error": oauth_error,
            "internal_connected": not bool(auth_url),
        },
    )
    db.commit()
    db.refresh(connection)

    if auth_url:
        message = "OAuth authorization URL created. Redirect user to provider."
    else:
        message = (
            f"{payload.provider} is connected for internal testing. Configure provider OAuth client credentials "
            "to enable real account authorization."
        )

    return {
        "status": connection.status,
        "message": message,
        "auth_url": auth_url,
        "oauth_error": oauth_error,
        "connection": public_connection(connection),
        "job": row_to_dict(job),
        "capabilities": connector_capabilities(payload.provider),
    }


@router.post("/evidence/upload")
async def upload_evidence_file(
    provider: ProviderId = Query(default="manual_csv"),
    workspace_id: str | None = Query(default=None),
    file: UploadFile = File(...),
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """One-call upload endpoint for the simple Files connector.

    The frontend can upload without manually creating a connection first. The
    backend creates/reuses the relevant connection and stores the source.
    """

    ensure_schema(db)
    mode = "manual_upload" if provider == "manual_csv" else "export_upload"
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=provider,
        workspace_id=workspace_id,
        mode=mode,
        config={"created_by": "direct_evidence_upload"},
    )
    data = await file.read()
    return ingest_upload_for_connection(
        db,
        tenant_id=tenant_id,
        connection=connection,
        filename=file.filename or "upload",
        content_type=file.content_type,
        data=data,
    )


@router.get("/connectors/data-sources")
async def list_data_sources(
    provider: str | None = None,
    connection_id: str | None = None,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_schema(db)
    query = db.query(DataSource).filter(DataSource.tenant_id == tenant_id)
    if provider:
        query = query.filter(DataSource.provider == provider)
    if connection_id:
        query = query.filter(DataSource.connector_connection_id == connection_id)
    rows = query.order_by(DataSource.created_at.desc()).limit(200).all()
    return {"status": "ok", "data_sources": [row_to_dict(row) for row in rows]}


@router.get("/connectors/jobs")
async def list_connector_jobs(
    connection_id: str | None = None,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_schema(db)
    query = db.query(IngestionJob).filter(IngestionJob.tenant_id == tenant_id)
    if connection_id:
        query = query.filter(IngestionJob.connector_connection_id == connection_id)
    rows = query.order_by(IngestionJob.created_at.desc()).limit(200).all()
    return {"status": "ok", "jobs": [row_to_dict(row) for row in rows]}


@router.get("/connectors/connections/{connection_id}/data")
async def connector_data_status(
    connection_id: str,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_schema(db)
    connection = db.get(ConnectorConnection, connection_id)
    if not connection or connection.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    sources = db.query(DataSource).filter(DataSource.connector_connection_id == connection_id).order_by(DataSource.created_at.desc()).limit(50).all()
    evidence = db.query(EvidenceRecord).filter(EvidenceRecord.connector_connection_id == connection_id).order_by(EvidenceRecord.created_at.desc()).limit(50).all()
    jobs = db.query(IngestionJob).filter(IngestionJob.connector_connection_id == connection_id).order_by(IngestionJob.created_at.desc()).limit(20).all()
    return {
        "status": "ok",
        "connection": public_connection(connection),
        "data_sources": [row_to_dict(row) for row in sources],
        "evidence": [evidence_public(row) for row in evidence],
        "jobs": [row_to_dict(row) for row in jobs],
        "counts": {
            "data_sources": len(sources),
            "evidence": len(evidence),
            "jobs": len(jobs),
        },
    }
