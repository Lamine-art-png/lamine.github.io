"""Connector Hub action endpoints."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.connectors import (
    _create_evidence_rows,
    _job,
    _job_public,
    create_or_get_connection,
    evidence_public,
    parse_rows,
    public_connection,
    row_to_dict,
    safe_credential_ref,
    sanitize_config,
    save_upload_bytes,
    suggest_mapping,
    verify_connector_schema,
)
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection, DataSource, EvidenceRecord, IngestionJob
from app.services.ingestion_stream import read_spooled_bytes, stream_upload_to_spool
from app.services.oauth_state import sign_oauth_state
from app.services.oauth_urls import oauth_url
import app.services.connector_commercial_guard as _connector_commercial_guard  # noqa: F401,E402

router = APIRouter(tags=["connector-hub-actions"])
ProviderId = Literal["wiseconn", "talgil", "universal_controller", "weather", "openet", "manual_csv", "chat_upload", "gmail", "outlook", "google_drive", "dropbox", "box", "slack", "salesforce", "john_deere", "google_earth_engine", "custom_api"]
ACCOUNT_PROVIDERS = {"gmail", "outlook", "google_drive", "dropbox", "box", "slack", "salesforce", "john_deere"}
UPLOAD_PROVIDERS = {"wiseconn", "talgil", "universal_controller", "manual_csv", "chat_upload", "weather", "openet"}


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
    provider: Literal["gmail", "outlook", "google_drive", "dropbox", "box", "slack", "salesforce", "john_deere"]
    workspace_id: str | None = None
    redirect_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def connector_mode(provider: str, requested: str | None = None) -> str:
    if requested:
        return requested
    if provider in ACCOUNT_PROVIDERS:
        return "oauth"
    if provider == "custom_api":
        return "custom_api"
    if provider in {"wiseconn", "talgil", "weather", "openet"}:
        return "api_credentials"
    if provider == "universal_controller":
        return "export_upload"
    return "manual_upload"


def credential_seed(provider: str, config: dict[str, Any]) -> str:
    for key in ("credential_ref", "api_key", "token", "account_email", "username", "base_url", "provider_name", "environment_name", "account_hint"):
        if config.get(key):
            return str(config[key])
    return f"{provider}:internal-testing-connection"


def capabilities(provider: str) -> list[str]:
    if provider in {"wiseconn", "talgil"}:
        return ["controller_events", "flow_readings", "irrigation_history", "export_upload", "future_live_sync"]
    if provider == "universal_controller":
        return ["controller_export_upload", "normalized_contract_mapping", "controller_readiness", "approval_only_execution"]
    if provider in {"manual_csv", "chat_upload"}:
        return ["file_upload", "csv_parse", "json_parse", "pdf_storage", "evidence_extraction"]
    if provider in {"gmail", "outlook"}:
        return ["email_context", "attachment_context", "report_delivery", "read_approved_context"]
    if provider == "google_drive":
        return ["folder_context", "document_context", "spreadsheet_context", "pdf_context"]
    if provider in {"dropbox", "box"}:
        return ["folder_context", "file_context", "document_context", "pdf_context"]
    if provider == "slack":
        return ["channel_context", "message_context", "file_context", "handoff_context"]
    if provider == "salesforce":
        return ["account_context", "case_context", "contact_context", "customer_success_context"]
    if provider == "john_deere":
        return ["organizations", "clients", "farms", "fields", "boundaries", "field_operations", "equipment_reference", "crop_types", "guidance_lines", "organization_settings", "read_only_sync"]
    if provider == "google_earth_engine":
        return ["project_readiness", "remote_sensing_context", "geospatial_asset_context"]
    if provider == "weather":
        return ["forecast_context", "station_upload", "api_weather_context"]
    if provider == "openet":
        return ["et_context", "water_use_context", "field_boundary_context"]
    return ["custom_endpoint", "provider_context", "future_sync_job"]


def _source_type(filename: str, content_type: str | None, provider: str) -> str:
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xls")):
        return "spreadsheet"
    if lower.endswith(".json") or (content_type or "").endswith("/json"):
        return "custom_api_payload"
    if lower.endswith(".pdf") or content_type == "application/pdf":
        return "pdf_document"
    if provider in {"wiseconn", "talgil", "universal_controller"}:
        return "controller_export"
    return "telemetry_csv"


def _get_connection(db: Session, tenant_id: str, connection_id: str) -> ConnectorConnection:
    row = db.get(ConnectorConnection, connection_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    return row


def _save_job(db: Session, *, tenant_id: str, connection: ConnectorConnection, job_type: str, output_json: dict[str, Any], status_value: str = "completed") -> IngestionJob:
    row = IngestionJob(tenant_id=tenant_id, workspace_id=connection.workspace_id, connector_connection_id=connection.id, job_type=job_type, status=status_value, input_json={"provider": connection.provider, "mode": connection.mode}, output_json=output_json, completed_at=datetime.utcnow())
    db.add(row)
    return row


def ingest_upload(db: Session, *, tenant_id: str, connection: ConnectorConnection, filename: str, content_type: str | None, data: bytes) -> dict[str, Any]:
    if connection.provider not in UPLOAD_PROVIDERS:
        raise HTTPException(status_code=400, detail="This connector does not accept file uploads. Use account/API connection instead.")
    raw_text, rows, columns, warnings = parse_rows(filename, content_type, data)
    storage_path = save_upload_bytes(tenant_id, connection.id, filename, data)
    mapping = suggest_mapping(columns)
    source = DataSource(tenant_id=tenant_id, workspace_id=connection.workspace_id, connector_connection_id=connection.id, source_type=_source_type(filename, content_type, connection.provider), provider=connection.provider, filename=filename, content_type=content_type, storage_path=storage_path, raw_text=raw_text[:200000], metadata_json={"columns": columns, "rows_parsed": len(rows), "parsed_rows": rows[:500], "mapping_suggestions": mapping, "storage_path": storage_path, "normalized_gateway": connection.provider == "universal_controller", "warnings": warnings}, status="parsed_with_warnings" if warnings else "parsed")
    db.add(source)
    db.commit()
    db.refresh(source)
    records = _create_evidence_rows(db, tenant_id=tenant_id, workspace_id=connection.workspace_id, connection_id=connection.id, data_source_id=source.id, provider=connection.provider, filename=filename, rows=rows, columns=columns)
    connection.status = "synced" if records else "mapping_required"
    connection.last_sync_at = datetime.utcnow()
    connection.last_error = None if records else "Uploaded file stored but produced no evidence records."
    job = _job(db, tenant_id=tenant_id, workspace_id=connection.workspace_id, connection_id=connection.id, data_source_id=source.id, job_type="connector_hub_upload_parse", input_json={"provider": connection.provider, "filename": filename}, output_json={"rows_parsed": len(rows), "columns": columns, "mapping_suggestions": mapping, "evidence_records_created": len(records), "warnings": warnings, "data_source_id": source.id, "storage_path": storage_path}, status_value="completed_with_warnings" if warnings else "completed")
    db.commit()
    db.refresh(connection)
    return {"status": source.status, "connection": public_connection(connection), "data_source": row_to_dict(source), "job": _job_public(job), "rows_parsed": len(rows), "columns": columns, "mapping_suggestions": mapping, "evidence_records_created": len(records), "warnings": warnings, "evidence_preview": [evidence_public(record) for record in records[:8]]}


@router.post("/connectors/connect")
async def connect_provider(payload: ConnectorConnectRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    mode = connector_mode(payload.provider, payload.mode)
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode=mode, display_name=payload.display_name, config=payload.config)
    caps = capabilities(payload.provider)
    merged = dict(connection.config_json or {})
    merged.update(sanitize_config(payload.config))
    merged.update({"authorization_status": "connected", "connector_hub_version": "working-v2", "connection_pattern": mode, "read_context_enabled": payload.read_context_enabled, "send_reports_enabled": payload.send_reports_enabled, "scopes": payload.scopes, "capabilities": caps})
    connection.mode = mode
    connection.status = "connected"
    connection.credentials_ref = safe_credential_ref(credential_seed(payload.provider, payload.config))
    connection.config_json = merged
    connection.last_error = None
    connection.last_test_at = datetime.utcnow()
    connection.updated_at = datetime.utcnow()
    job = _save_job(db, tenant_id=tenant_id, connection=connection, job_type="connector_connect", output_json={"status": "connected", "capabilities": caps})
    db.commit()
    db.refresh(connection)
    return {"status": "connected", "message": f"{payload.provider} connected.", "connection": public_connection(connection), "job": row_to_dict(job), "capabilities": caps}


@router.post("/connectors/oauth/start")
async def start_oauth(payload: OAuthStartRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode="oauth", config=payload.metadata)
    redirect_url = payload.redirect_url or "https://api.agroai-pilot.com/v1/connectors/oauth/callback"
    state = sign_oauth_state(connection.id)
    auth_url, oauth_error = oauth_url(payload.provider, state, redirect_url)
    caps = capabilities(payload.provider)
    merged = dict(connection.config_json or {})
    merged.update(sanitize_config({**payload.metadata, "oauth_state": state, "oauth_redirect_url": redirect_url, "oauth_error": oauth_error, "authorization_status": "oauth_ready" if auth_url else "internal_connected", "capabilities": caps}))
    connection.mode = "oauth"
    connection.status = "oauth_pending" if auth_url else "connected"
    connection.credentials_ref = safe_credential_ref(payload.metadata.get("account_hint") or f"{payload.provider}:internal-oauth")
    connection.config_json = merged
    connection.last_error = oauth_error
    connection.last_test_at = datetime.utcnow()
    connection.updated_at = datetime.utcnow()
    job = _save_job(db, tenant_id=tenant_id, connection=connection, job_type="oauth_start", status_value="completed_with_warnings" if oauth_error else "completed", output_json={"auth_url_available": bool(auth_url), "oauth_error": oauth_error, "internal_connected": not bool(auth_url)})
    db.commit()
    db.refresh(connection)
    message = "OAuth authorization URL created." if auth_url else f"{payload.provider} connected for internal testing. Configure provider OAuth client credentials to enable real account authorization."
    return {"status": connection.status, "message": message, "auth_url": auth_url, "oauth_error": oauth_error, "connection": public_connection(connection), "job": row_to_dict(job), "capabilities": caps}


@router.post("/evidence/upload")
async def upload_hub_evidence_file(provider: ProviderId = Query(default="manual_csv"), workspace_id: str | None = Query(default=None), file: UploadFile = File(...), tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    mode = "manual_upload" if provider in {"manual_csv", "chat_upload"} else "export_upload"
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=provider, workspace_id=workspace_id, mode=mode, config={"created_by": "direct_evidence_upload"})
    receipt = await stream_upload_to_spool(file, tenant_id=tenant_id, connection_id=connection.id)
    try:
        data = read_spooled_bytes(receipt)
        return ingest_upload(db, tenant_id=tenant_id, connection=connection, filename=file.filename or "upload", content_type=file.content_type, data=data)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail={"error": "upload_ingestion_failed", "message": str(exc), "provider": provider, "filename": file.filename}) from exc
    finally:
        Path(receipt.path).unlink(missing_ok=True)


@router.get("/connectors/data-sources")
async def list_data_sources(provider: str | None = None, connection_id: str | None = None, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    query = db.query(DataSource).filter(DataSource.tenant_id == tenant_id)
    if provider:
        query = query.filter(DataSource.provider == provider)
    if connection_id:
        query = query.filter(DataSource.connector_connection_id == connection_id)
    rows = query.order_by(DataSource.created_at.desc()).limit(200).all()
    return {"status": "ok", "data_sources": [row_to_dict(row) for row in rows]}


@router.get("/connectors/jobs")
async def list_connector_jobs(connection_id: str | None = None, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    query = db.query(IngestionJob).filter(IngestionJob.tenant_id == tenant_id)
    if connection_id:
        query = query.filter(IngestionJob.connector_connection_id == connection_id)
    rows = query.order_by(IngestionJob.created_at.desc()).limit(200).all()
    return {"status": "ok", "jobs": [row_to_dict(row) for row in rows]}


@router.get("/connectors/connections/{connection_id}/data")
async def connector_data_status(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    _get_connection(db, tenant_id, connection_id)
    sources = db.query(DataSource).filter(DataSource.tenant_id == tenant_id, DataSource.connector_connection_id == connection_id).order_by(DataSource.created_at.desc()).limit(50).all()
    evidence = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == tenant_id, EvidenceRecord.connector_connection_id == connection_id).order_by(EvidenceRecord.created_at.desc()).limit(50).all()
    jobs = db.query(IngestionJob).filter(IngestionJob.tenant_id == tenant_id, IngestionJob.connector_connection_id == connection_id).order_by(IngestionJob.created_at.desc()).limit(20).all()
    return {"status": "ok", "data_sources": [row_to_dict(row) for row in sources], "evidence": [evidence_public(row) for row in evidence], "jobs": [row_to_dict(row) for row in jobs], "counts": {"data_sources": len(sources), "evidence": len(evidence), "jobs": len(jobs)}}


# Keep the v3 self-service agricultural lifecycle on the already-mounted
# Connector Hub router so there is one production route owner at runtime.
from app.api.v1.connector_unified_v3 import router as unified_v3_router  # noqa: E402
router.include_router(unified_v3_router)

# Mount the generic provider sync lifecycle (queue/sync/disconnect) on the same
# already-mounted Connector Hub router. This closes the runtime gap where the
# module existed but its endpoints were unreachable from the production app.
from app.api.v1.connector_provider_sync import router as provider_sync_router  # noqa: E402
router.include_router(provider_sync_router)
