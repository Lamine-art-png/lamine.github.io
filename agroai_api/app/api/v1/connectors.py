"""Connector, evidence, and controller-agnostic onboarding endpoints.

This router makes fragmented data useful immediately while keeping live API and
physical execution claims honest. It supports native controllers such as WiseConn
and Talgil, plus a Universal Controller Gateway for any other irrigation/control
system through export upload, API credentials, provider-assisted onboarding, or a
custom enterprise API contract.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.operational_records import ConnectorConnection, DataSource, EvidenceRecord, GeneratedArtifact, IngestionJob, IntelligenceRun
from app.services.ingestion_stream import read_spooled_bytes, stream_upload_to_spool
from app.services.oauth_state import sign_oauth_state
from app.services.oauth_urls import oauth_url

router = APIRouter(tags=["operational-intelligence"])

ProviderId = Literal[
    "wiseconn",
    "talgil",
    "universal_controller",
    "weather",
    "openet",
    "manual_csv",
    "chat_upload",
    "gmail",
    "outlook",
    "google_drive",
    "dropbox",
    "box",
    "slack",
    "salesforce",
    "google_earth_engine",
    "custom_api",
]

CATALOG: list[dict[str, Any]] = [
    {
        "id": "wiseconn",
        "name": "WiseConn",
        "category": "Irrigation controllers",
        "status": "needs_credentials",
        "required_plan": "pilot",
        "connection_methods": ["export_upload", "api_credentials"],
        "upload_supported": True,
        "imports": ["zones", "controller events", "flow", "irrigation history", "valve state"],
        "normalized_objects": ["farm", "field", "zone", "valve", "flow_meter", "schedule", "irrigation_event"],
        "used_by": ["Decisions", "Evidence", "Reports", "Assurance", "Agentic actions", "Controller readiness"],
        "promise": "Upload WiseConn exports now; enable live sync and approval-gated schedule execution when credentials and mapping are verified.",
    },
    {
        "id": "talgil",
        "name": "Talgil",
        "category": "Irrigation controllers",
        "status": "needs_credentials",
        "required_plan": "pilot",
        "connection_methods": ["export_upload", "api_credentials"],
        "upload_supported": True,
        "imports": ["targets", "program state", "valve state", "flow", "irrigation events"],
        "normalized_objects": ["target", "field", "zone", "valve", "program", "irrigation_event"],
        "used_by": ["Decisions", "Evidence", "Reports", "Assurance", "Agentic actions", "Controller readiness"],
        "promise": "Upload Talgil/controller exports now; enable live read sync when credentials are configured. Physical write execution requires a verified provider write contract.",
    },
    {
        "id": "universal_controller",
        "name": "Universal Controller / Custom Irrigation System",
        "category": "Irrigation controllers",
        "status": "controller_agnostic_gateway",
        "required_plan": "enterprise",
        "connection_methods": ["export_upload", "api_credentials", "provider_assisted", "custom_api"],
        "upload_supported": True,
        "imports": ["farms", "fields", "blocks", "zones", "valves", "pumps", "flow", "pressure", "irrigation events", "program schedules", "operator notes"],
        "normalized_objects": ["farm", "field", "block", "zone", "valve", "pump", "meter", "sensor", "schedule", "event", "operator_note"],
        "used_by": ["Ask AGRO-AI", "Decisions", "Evidence", "Reports", "Assurance", "Agentic actions", "Controller readiness"],
        "promise": "Bring any controller system into AGRO-AI through exports, API credentials, or provider-assisted onboarding. AGRO-AI normalizes the data into one operating model before any physical execution is considered.",
    },
    {
        "id": "manual_csv",
        "name": "CSV / PDF / Spreadsheet upload",
        "category": "Manual evidence",
        "status": "upload_ready",
        "required_plan": "free",
        "connection_methods": ["manual_upload", "export_upload"],
        "upload_supported": True,
        "imports": ["CSV", "JSON", "TXT", "PDF text", "operator notes", "field logs"],
        "used_by": ["Evidence", "Reports", "Ask AGRO-AI", "Decisions"],
        "promise": "Upload fragmented evidence and convert it into citation-ready operational context.",
    },
    {
        "id": "chat_upload",
        "name": "Chat file import",
        "category": "Manual evidence",
        "status": "upload_ready",
        "required_plan": "free",
        "connection_methods": ["manual_upload"],
        "upload_supported": True,
        "imports": ["CSV", "spreadsheets", "PDF metadata", "text documents", "JSON", "geospatial files", "archives"],
        "used_by": ["Ask AGRO-AI", "Evidence", "Reports"],
        "promise": "Import files into the current chat and attach their metadata to the next AGRO-AI request.",
    },
    {
        "id": "weather",
        "name": "Weather / Forecast",
        "category": "Environmental data",
        "status": "not_configured",
        "required_plan": "pilot",
        "connection_methods": ["manual_upload", "api_credentials"],
        "upload_supported": True,
        "imports": ["temperature", "rainfall", "humidity", "forecast"],
        "used_by": ["Decisions", "Reports"],
        "promise": "Bring weather context into irrigation recommendations and risk flags.",
    },
    {
        "id": "openet",
        "name": "OpenET / ET data",
        "category": "Water intelligence",
        "status": "not_configured",
        "required_plan": "pro",
        "connection_methods": ["manual_upload", "api_credentials"],
        "upload_supported": True,
        "imports": ["ET", "ET0", "field water use estimates"],
        "used_by": ["Decisions", "Assurance", "Reports"],
        "promise": "Add ET context to field-level water accounting.",
    },
    {"id": "gmail", "name": "Gmail", "category": "Email evidence", "status": "coming_soon", "required_plan": "pro", "connection_methods": ["oauth"], "upload_supported": False, "imports": ["attachments", "operator emails", "reports", "vendor records"], "used_by": ["Evidence", "Reports"], "promise": "OAuth email evidence ingestion is prepared but not enabled yet."},
    {"id": "outlook", "name": "Outlook", "category": "Email evidence", "status": "coming_soon", "required_plan": "pro", "connection_methods": ["oauth"], "upload_supported": False, "imports": ["attachments", "operator emails", "reports", "vendor records"], "used_by": ["Evidence", "Reports"], "promise": "OAuth email evidence ingestion is prepared but not enabled yet."},
    {"id": "google_drive", "name": "Google Drive", "category": "Document evidence", "status": "coming_soon", "required_plan": "pro", "connection_methods": ["oauth"], "upload_supported": False, "imports": ["folders", "PDFs", "spreadsheets", "reports"], "used_by": ["Evidence", "Reports"], "promise": "Drive sync is prepared but not enabled yet."},
    {"id": "dropbox", "name": "Dropbox", "category": "Document evidence", "status": "not_configured", "required_plan": "pro", "connection_methods": ["oauth"], "upload_supported": False, "imports": ["folders", "files", "PDFs", "spreadsheets", "image metadata"], "used_by": ["Evidence", "Reports", "Assurance"], "promise": "OAuth Dropbox folder evidence ingestion is ready when the Dropbox client ID is configured.", "required_env": ["DROPBOX_OAUTH_CLIENT_ID"]},
    {"id": "box", "name": "Box", "category": "Document evidence", "status": "not_configured", "required_plan": "pro", "connection_methods": ["oauth"], "upload_supported": False, "imports": ["folders", "files", "PDFs", "spreadsheets", "enterprise records"], "used_by": ["Evidence", "Reports", "Assurance"], "promise": "OAuth Box folder evidence ingestion is ready when the Box client ID is configured.", "required_env": ["BOX_OAUTH_CLIENT_ID"]},
    {"id": "slack", "name": "Slack", "category": "Operations context", "status": "not_configured", "required_plan": "pro", "connection_methods": ["oauth"], "upload_supported": False, "imports": ["channels", "messages", "files", "operator handoffs"], "used_by": ["Evidence", "Ask AGRO-AI", "Reports"], "promise": "OAuth Slack context ingestion is ready when the Slack client ID is configured.", "required_env": ["SLACK_OAUTH_CLIENT_ID"]},
    {"id": "salesforce", "name": "Salesforce", "category": "Customer operations", "status": "not_configured", "required_plan": "enterprise", "connection_methods": ["oauth"], "upload_supported": False, "imports": ["accounts", "contacts", "cases", "opportunities", "customer notes"], "used_by": ["Reports", "Assurance", "Customer success"], "promise": "OAuth Salesforce context is ready when the Salesforce client ID is configured.", "required_env": ["SALESFORCE_OAUTH_CLIENT_ID"]},
    {"id": "google_earth_engine", "name": "Google Earth Engine", "category": "Geospatial intelligence", "status": "not_configured", "required_plan": "enterprise", "connection_methods": ["service_account"], "upload_supported": False, "imports": ["field imagery", "ET/geospatial layers", "remote sensing context", "project assets"], "used_by": ["Decisions", "Reports", "Assurance"], "promise": "Google Earth Engine is ready when project and service-account env vars are configured.", "required_env": ["GOOGLE_EARTH_ENGINE_PROJECT_ID", "GOOGLE_EARTH_ENGINE_SERVICE_ACCOUNT_JSON"]},
    {"id": "custom_api", "name": "Custom API", "category": "Enterprise systems", "status": "enterprise", "required_plan": "enterprise", "connection_methods": ["custom_api"], "upload_supported": False, "imports": ["ERP records", "district records", "sensor APIs", "custom telemetry"], "used_by": ["Enterprise deployments"], "promise": "Connect district, agribusiness, or enterprise systems through a contract-specific API."},
]

CANONICAL_FIELDS = {
    "timestamp": ["timestamp", "datetime", "date", "time", "start", "end", "occurred"],
    "field": ["field", "ranch", "farm", "parcel"],
    "block": ["block", "zone", "station", "plot", "sector"],
    "crop": ["crop", "variety"],
    "flow_rate": ["flow", "gpm", "lps", "rate"],
    "water_volume": ["gallon", "acre_feet", "acre-foot", "volume", "water", "inches", "mm", "m3"],
    "duration": ["duration", "minutes", "hours", "runtime", "run_time"],
    "valve_state": ["valve", "state", "status"],
    "pressure": ["pressure", "psi", "bar"],
    "et": ["et", "eto", "etc", "evapotranspiration"],
    "rainfall": ["rain", "precip", "precipitation"],
    "temperature": ["temp", "temperature"],
    "humidity": ["humidity", "rh"],
    "pump_state": ["pump"],
    "note": ["note", "comment", "description", "memo"],
}

TABLES = [ConnectorConnection.__table__, DataSource.__table__, IngestionJob.__table__, EvidenceRecord.__table__, IntelligenceRun.__table__, GeneratedArtifact.__table__]
SECRET_FIELD_HINTS = ("secret", "token", "password", "api_key", "apikey", "credential", "private_key")


class ConnectorStartRequest(BaseModel):
    provider: ProviderId
    method: str = Field(default="export_upload")
    workspace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OAuthStartRequest(BaseModel):
    provider: Literal["gmail", "outlook", "google_drive", "dropbox", "box", "slack", "salesforce"]
    workspace_id: str | None = None
    redirect_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorCreateRequest(BaseModel):
    provider: ProviderId
    mode: str = "export_upload"
    workspace_id: str | None = None
    display_name: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorPatchRequest(BaseModel):
    status: str | None = None
    mode: str | None = None
    display_name: str | None = None
    config: dict[str, Any] | None = None
    credentials_ref: str | None = None


class MappingRequest(BaseModel):
    mapping: dict[str, str]


class EvidenceCreateRequest(BaseModel):
    title: str = "Evidence record"
    summary: str = "Manual evidence record"
    evidence_type: str = "manual"
    workspace_id: str | None = None
    value_json: dict[str, Any] = Field(default_factory=dict)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


def verify_connector_schema(db: Session) -> None:
    """Verify Alembic-owned connector schema without mutating it."""
    bind = db.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    missing: dict[str, list[str]] = {}
    for table in TABLES:
        if table.name not in tables:
            missing[table.name] = sorted(column.name for column in table.columns)
            continue
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        missing_columns = {column.name for column in table.columns} - existing
        if missing_columns:
            missing[table.name] = sorted(missing_columns)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "connector_schema_not_ready", "missing": missing, "action": "run_alembic_upgrade_head"},
        )


def sanitize_config(config: dict[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in (config or {}).items():
        lowered = key.lower()
        if any(hint in lowered for hint in SECRET_FIELD_HINTS):
            safe[key] = f"submitted:{hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:12]}" if value else ""
        elif isinstance(value, dict):
            safe[key] = sanitize_config(value)
        else:
            safe[key] = value
    return safe


def safe_credential_ref(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    tail = text[-4:] if len(text) >= 4 else "set"
    return f"credential_ref:{digest}:last4:{tail}"


def catalog_item(provider: str) -> dict[str, Any] | None:
    return next((item for item in CATALOG if item["id"] == provider), None)


def connector_readiness(item: dict[str, Any]) -> dict[str, Any]:
    required = list(item.get("required_env") or [])
    missing = [name for name in required if not os.getenv(name, "").strip()]
    status_value = item.get("status", "available")
    if required:
        status_value = "ready_to_authorize" if not missing else "not_configured"
    return {**item, "configured": not missing, "configured_env": [name for name in required if name not in missing], "missing_env": missing, "status": status_value}


def row_to_dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns} if row is not None else {}


def public_connection(row: ConnectorConnection) -> dict[str, Any]:
    data = row_to_dict(row)
    item = catalog_item(row.provider) or {}
    data.update({
        "name": item.get("name", row.display_name),
        "category": item.get("category"),
        "connection_methods": item.get("connection_methods", []),
        "imports": item.get("imports", []),
        "normalized_objects": item.get("normalized_objects", []),
        "upload_supported": item.get("upload_supported", False),
        "live_sync_enabled": row.status in {"synced", "syncing", "connected"} and bool(row.credentials_ref),
    })
    return data


def evidence_public(row: EvidenceRecord) -> dict[str, Any]:
    data = row_to_dict(row)
    data["name"] = row.title
    data["source"] = row.citation_label
    data["domain"] = row.evidence_type
    data["status"] = row.quality_status
    return data


def create_or_get_connection(db: Session, *, tenant_id: str, provider: str, workspace_id: str | None = None, mode: str | None = None, display_name: str | None = None, config: dict[str, Any] | None = None) -> ConnectorConnection:
    verify_connector_schema(db)
    item = catalog_item(provider)
    if item is None:
        raise HTTPException(status_code=400, detail="Unsupported connector provider")
    query = db.query(ConnectorConnection).filter(ConnectorConnection.tenant_id == tenant_id, ConnectorConnection.provider == provider)
    if workspace_id:
        query = query.filter(ConnectorConnection.workspace_id == workspace_id)
    existing = query.order_by(ConnectorConnection.created_at.asc()).first()
    if existing:
        if mode:
            existing.mode = mode
        if display_name:
            existing.display_name = display_name
        if config:
            merged = dict(existing.config_json or {})
            merged.update(sanitize_config(config))
            existing.config_json = merged
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing
    selected_mode = mode or (item.get("connection_methods") or ["manual_upload"])[0]
    row = ConnectorConnection(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        provider=provider,
        display_name=display_name or item["name"],
        status="ready" if selected_mode in {"manual_upload", "export_upload"} else "needs_credentials",
        mode=selected_mode,
        required_plan=item.get("required_plan", "free"),
        config_json=sanitize_config(config or {}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def setup_payload(connection: ConnectorConnection) -> dict[str, Any]:
    item = catalog_item(connection.provider) or {}
    is_controller = connection.provider in {"wiseconn", "talgil", "universal_controller"}
    steps = ["Choose upload or credential mode", "Upload export or save credential reference", "Test connection readiness", "Map fields", "Ingest evidence", "Ask AGRO-AI or generate report"]
    if is_controller:
        steps += ["Normalize farms/fields/zones/valves/pumps", "Run controller execution readiness", "Keep physical execution dry-run + approval-gated until verified"]
    return {
        "status": "setup_started",
        "connection": public_connection(connection),
        "connector": item,
        "live_sync_enabled": False,
        "credential_storage": "secure_vault_required_before_live_sync",
        "controller_agnostic_gateway": is_controller,
        "steps": steps,
        "warning": "Live API sync and physical execution are disabled until credentials, provider contract, mapping, permissions, approval, and audit gates are verified.",
    }


def safe_filename(name: str | None) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "upload").strip("._")
    return base[:160] or "upload"


def decode_upload(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_rows(filename: str, content_type: str | None, data: bytes) -> tuple[str, list[dict[str, Any]], list[str], list[str]]:
    text = decode_upload(data)
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    lower = filename.lower()
    if lower.endswith(".json") or (content_type or "").endswith("/json"):
        try:
            loaded = json.loads(text)
            if isinstance(loaded, list):
                rows = [item if isinstance(item, dict) else {"value": item} for item in loaded]
            elif isinstance(loaded, dict):
                candidate = loaded.get("records") or loaded.get("rows") or loaded.get("data")
                rows = [item if isinstance(item, dict) else {"value": item} for item in candidate] if isinstance(candidate, list) else [loaded]
        except json.JSONDecodeError as exc:
            warnings.append(f"JSON parse failed: {exc}")
    elif lower.endswith(".pdf") or content_type == "application/pdf":
        rows = [{"document_text": text[:5000], "filename": filename}]
        warnings.append("PDF binary extraction is limited here. Prefer text/CSV exports for stronger evidence.")
    else:
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample) if any(token in sample for token in [",", "\t", ";"]) else csv.excel
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        rows = [dict(row) for row in reader]
        if not rows and text.strip():
            rows = [{"note": line.strip()} for line in text.splitlines() if line.strip()]
            warnings.append("File did not look like a table; ingested non-empty lines as field notes.")
    columns = sorted({str(key) for row in rows for key in row.keys()}) if rows else []
    if not rows:
        warnings.append("No parseable rows found.")
    return text, rows, columns, warnings


def suggest_mapping(columns: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for column in columns:
        normalized = re.sub(r"[^a-z0-9]+", "_", column.lower()).strip("_")
        for canonical, hints in CANONICAL_FIELDS.items():
            if any(hint in normalized for hint in hints):
                mapping[column] = canonical
                break
    return mapping


def save_upload_bytes(tenant_id: str, connection_id: str, filename: str | None, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()[:16]
    root = Path(getattr(settings, "CONNECTOR_UPLOAD_DIR", "/tmp/agroai_uploads"))
    try:
        target_dir = root / safe_filename(tenant_id) / safe_filename(connection_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{digest}-{safe_filename(filename)}"
        target.write_bytes(data)
        return str(target)
    except OSError:
        return f"inline://sha256/{digest}/{safe_filename(filename)}"


async def _bounded_upload_bytes(tenant_id: str, connection_id: str, file: UploadFile) -> bytes:
    receipt = await stream_upload_to_spool(file, tenant_id=tenant_id, connection_id=connection_id)
    try:
        return read_spooled_bytes(receipt)
    finally:
        Path(receipt.path).unlink(missing_ok=True)


def _job(db: Session, *, tenant_id: str, workspace_id: str | None, connection_id: str | None, data_source_id: str | None, job_type: str, input_json: dict[str, Any], output_json: dict[str, Any], status_value: str = "completed") -> IngestionJob:
    row = IngestionJob(tenant_id=tenant_id, workspace_id=workspace_id, connector_connection_id=connection_id, data_source_id=data_source_id, job_type=job_type, status=status_value, input_json=input_json, output_json=output_json, completed_at=datetime.utcnow())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _job_public(row: IngestionJob) -> dict[str, Any]:
    return row_to_dict(row)


def _create_evidence_rows(db: Session, *, tenant_id: str, workspace_id: str | None, connection_id: str | None, data_source_id: str, provider: str, filename: str, rows: list[dict[str, Any]], columns: list[str]) -> list[EvidenceRecord]:
    evidence: list[EvidenceRecord] = []
    mapping = suggest_mapping(columns)
    for index, row in enumerate(rows[:100]):
        label = row.get("field") or row.get("block") or row.get("zone") or row.get("station") or row.get("note") or filename
        record = EvidenceRecord(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            data_source_id=data_source_id,
            connector_connection_id=connection_id,
            evidence_type="controller_event" if provider in {"wiseconn", "talgil", "universal_controller"} else "uploaded_record",
            title=f"{provider} evidence: {str(label)[:80]}",
            summary=str(row)[:1200],
            value_json=row,
            confidence=0.72,
            quality_status="usable",
            citation_label=f"{provider}:{filename}:row-{index + 1}",
            source_excerpt=str(row)[:1600],
            metadata_json={"mapping": mapping, "row_index": index, "normalized_gateway": provider == "universal_controller"},
        )
        db.add(record)
        evidence.append(record)
    db.commit()
    return evidence


@router.get("/connectors/catalog")
def get_catalog() -> dict[str, Any]:
    connectors = [connector_readiness(item) for item in CATALOG]
    return {"status": "ok", "catalog": connectors, "connectors": connectors}


@router.post("/connectors/start")
def start_connector(payload: ConnectorStartRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode=payload.method, config=payload.metadata)
    return setup_payload(connection)


@router.post("/connectors/connect")
def connect_connector(payload: ConnectorCreateRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode=payload.mode, display_name=payload.display_name, config=payload.config)
    return setup_payload(connection)


@router.get("/connectors/connections")
def list_connections(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    rows = db.query(ConnectorConnection).filter(ConnectorConnection.tenant_id == tenant_id).order_by(ConnectorConnection.created_at.desc()).all()
    return {"status": "ok", "connections": [public_connection(row) for row in rows]}


@router.post("/connectors/connections", status_code=status.HTTP_201_CREATED)
def create_connection(payload: ConnectorCreateRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode=payload.mode, display_name=payload.display_name, config=payload.config)
    return {"status": "ok", "connection": public_connection(row), "setup": setup_payload(row)}


def _get_connection(db: Session, tenant_id: str, connection_id: str) -> ConnectorConnection:
    row = db.get(ConnectorConnection, connection_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    return row


@router.get("/connectors/connections/{connection_id}")
def get_connection(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"status": "ok", "connection": public_connection(_get_connection(db, tenant_id, connection_id))}


@router.patch("/connectors/connections/{connection_id}")
def patch_connection(connection_id: str, payload: ConnectorPatchRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_connection(db, tenant_id, connection_id)
    if payload.status is not None:
        row.status = payload.status
    if payload.mode is not None:
        row.mode = payload.mode
    if payload.display_name is not None:
        row.display_name = payload.display_name
    if payload.config is not None:
        merged = dict(row.config_json or {})
        merged.update(sanitize_config(payload.config))
        row.config_json = merged
    if payload.credentials_ref is not None:
        row.credentials_ref = safe_credential_ref(payload.credentials_ref)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return {"status": "ok", "connection": public_connection(row)}


@router.delete("/connectors/connections/{connection_id}")
def delete_connection(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_connection(db, tenant_id, connection_id)
    db.delete(row)
    db.commit()
    return {"status": "deleted", "connection_id": connection_id}


@router.post("/connectors/connections/{connection_id}/test")
def test_connection(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_connection(db, tenant_id, connection_id)
    item = catalog_item(row.provider) or {}
    ready = row.mode in {"manual_upload", "export_upload", "provider_assisted", "custom_api"} or bool(row.credentials_ref)
    row.last_test_at = datetime.utcnow()
    row.status = "ready" if ready else "needs_credentials"
    db.commit()
    return {"status": row.status, "connection": public_connection(row), "connector": item, "live_execution_enabled": False}


@router.post("/connectors/connections/{connection_id}/upload")
async def upload_connection_file(connection_id: str, file: UploadFile = File(...), tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_connection(db, tenant_id, connection_id)
    data = await _bounded_upload_bytes(tenant_id, connection_id, file)
    text, rows, columns, warnings = parse_rows(file.filename or "upload", file.content_type, data)
    storage_path = save_upload_bytes(tenant_id, connection_id, file.filename, data)
    source = DataSource(tenant_id=tenant_id, workspace_id=row.workspace_id, connector_connection_id=row.id, source_type=row.provider, provider=row.provider, filename=file.filename, content_type=file.content_type, storage_path=storage_path, raw_text=text[:50000], metadata_json={"columns": columns, "rows_parsed": len(rows), "warnings": warnings, "mapping": suggest_mapping(columns), "normalized_gateway": row.provider == "universal_controller"}, status="parsed")
    db.add(source)
    db.commit()
    db.refresh(source)
    evidence = _create_evidence_rows(db, tenant_id=tenant_id, workspace_id=row.workspace_id, connection_id=row.id, data_source_id=source.id, provider=row.provider, filename=file.filename or "upload", rows=rows, columns=columns)
    job = _job(db, tenant_id=tenant_id, workspace_id=row.workspace_id, connection_id=row.id, data_source_id=source.id, job_type="connector_upload_parse", input_json={"filename": file.filename, "provider": row.provider}, output_json={"rows_parsed": len(rows), "columns": columns, "warnings": warnings, "evidence_records": len(evidence)})
    row.status = "synced"
    row.last_sync_at = datetime.utcnow()
    db.commit()
    return {"status": "parsed", "connection": public_connection(row), "data_source": row_to_dict(source), "job": _job_public(job), "rows_parsed": len(rows), "columns": columns, "warnings": warnings, "evidence_preview": [evidence_public(item) for item in evidence[:5]]}


@router.get("/connectors/connections/{connection_id}/data")
def connection_data(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_connection(db, tenant_id, connection_id)
    sources = db.query(DataSource).filter(DataSource.tenant_id == tenant_id, DataSource.connector_connection_id == row.id).order_by(DataSource.created_at.desc()).limit(50).all()
    evidence = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == tenant_id, EvidenceRecord.connector_connection_id == row.id).order_by(EvidenceRecord.created_at.desc()).limit(100).all()
    return {"status": "ok", "data_sources": [row_to_dict(item) for item in sources], "evidence": [evidence_public(item) for item in evidence]}


@router.get("/connectors/connections/{connection_id}/mapping/suggestions")
def mapping_suggestions(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_connection(db, tenant_id, connection_id)
    source = db.query(DataSource).filter(DataSource.tenant_id == tenant_id, DataSource.connector_connection_id == row.id).order_by(DataSource.created_at.desc()).first()
    columns = (source.metadata_json or {}).get("columns", []) if source else []
    return {"status": "ok", "columns": columns, "suggested_mapping": suggest_mapping(columns), "normalized_objects": (catalog_item(row.provider) or {}).get("normalized_objects", [])}


@router.post("/connectors/connections/{connection_id}/mapping")
def save_mapping(connection_id: str, payload: MappingRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_connection(db, tenant_id, connection_id)
    config = dict(row.config_json or {})
    config["field_mapping"] = payload.mapping
    config["mapping_confirmed"] = True
    row.config_json = config
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return {"status": "ok", "connection": public_connection(row), "mapping": payload.mapping}


@router.post("/connectors/connections/{connection_id}/sync")
def sync_connection(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = _get_connection(db, tenant_id, connection_id)
    job = _job(db, tenant_id=tenant_id, workspace_id=row.workspace_id, connection_id=row.id, data_source_id=None, job_type="connector_sync_request", input_json={"provider": row.provider}, output_json={"live_sync_enabled": False, "message": "Upload/export sync works now. Live provider sync requires verified credentials and provider-specific contract."}, status_value="completed")
    return {"status": "queued" if row.credentials_ref else "manual_sync_ready", "connection": public_connection(row), "job": _job_public(job)}


@router.get("/connectors/data-sources")
def list_data_sources(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    rows = db.query(DataSource).filter(DataSource.tenant_id == tenant_id).order_by(DataSource.created_at.desc()).limit(100).all()
    return {"status": "ok", "data_sources": [row_to_dict(row) for row in rows]}


@router.get("/connectors/jobs")
def list_jobs(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    rows = db.query(IngestionJob).filter(IngestionJob.tenant_id == tenant_id).order_by(IngestionJob.created_at.desc()).limit(100).all()
    return {"status": "ok", "jobs": [_job_public(row) for row in rows]}


@router.post("/connectors/oauth/start")
def start_oauth(payload: OAuthStartRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode="oauth", config=payload.metadata)
    redirect_url = payload.redirect_url or f"{getattr(settings, 'APP_URL', 'https://app.agroai-pilot.com').rstrip('/')}/connectors/oauth/callback"
    state = sign_oauth_state(connection.id)
    merged = dict(connection.config_json or {})
    merged["oauth_state"] = state
    merged["oauth_redirect_url"] = redirect_url
    connection.config_json = sanitize_config(merged)
    connection.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(connection)
    url, error = oauth_url(payload.provider, state, redirect_url)
    return {"status": "oauth_ready" if url else "not_configured", "connection": public_connection(connection), "authorization_url": url, "error": error}


@router.get("/evidence")
def list_evidence(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    rows = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == tenant_id).order_by(EvidenceRecord.created_at.desc()).limit(150).all()
    return {"status": "ok", "evidence": [evidence_public(row) for row in rows]}


@router.post("/evidence")
def create_evidence(payload: EvidenceCreateRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    row = EvidenceRecord(tenant_id=tenant_id, workspace_id=payload.workspace_id, evidence_type=payload.evidence_type, title=payload.title, summary=payload.summary, value_json=payload.value_json, confidence=0.72, quality_status="usable", citation_label=f"manual:{datetime.utcnow().isoformat(timespec='seconds')}", metadata_json=payload.metadata_json)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"status": "ok", "evidence": evidence_public(row)}


@router.get("/evidence/summary")
def evidence_summary(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    rows = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == tenant_id).all()
    by_type: dict[str, int] = {}
    for row in rows:
        by_type[row.evidence_type] = by_type.get(row.evidence_type, 0) + 1
    return {"status": "ok", "total": len(rows), "by_type": by_type}


@router.post("/evidence/upload")
async def upload_evidence(provider: str = Query(default="manual_csv"), workspace_id: str | None = Query(default=None), file: UploadFile = File(...), tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    if not catalog_item(provider):
        provider = "manual_csv"
    connection = create_or_get_connection(db, tenant_id=tenant_id, provider=provider, workspace_id=workspace_id, mode="manual_upload" if provider == "chat_upload" else "export_upload")
    data = await _bounded_upload_bytes(tenant_id, connection.id, file)
    text, rows, columns, warnings = parse_rows(file.filename or "upload", file.content_type, data)
    storage_path = save_upload_bytes(tenant_id, connection.id, file.filename, data)
    source = DataSource(tenant_id=tenant_id, workspace_id=workspace_id, connector_connection_id=connection.id, source_type=provider, provider=provider, filename=file.filename, content_type=file.content_type, storage_path=storage_path, raw_text=text[:50000], metadata_json={"columns": columns, "rows_parsed": len(rows), "warnings": warnings, "mapping": suggest_mapping(columns), "normalized_gateway": provider == "universal_controller"}, status="parsed")
    db.add(source)
    db.commit()
    db.refresh(source)
    evidence = _create_evidence_rows(db, tenant_id=tenant_id, workspace_id=workspace_id, connection_id=connection.id, data_source_id=source.id, provider=provider, filename=file.filename or "upload", rows=rows, columns=columns)
    job = _job(db, tenant_id=tenant_id, workspace_id=workspace_id, connection_id=connection.id, data_source_id=source.id, job_type="evidence_upload_parse", input_json={"filename": file.filename, "provider": provider}, output_json={"rows_parsed": len(rows), "columns": columns, "warnings": warnings, "evidence_records": len(evidence)})
    return {"status": "parsed", "connection": public_connection(connection), "data_source": row_to_dict(source), "job": _job_public(job), "rows_parsed": len(rows), "columns": columns, "warnings": warnings, "evidence_preview": [evidence_public(item) for item in evidence[:5]]}


@router.post("/reports/generate")
def generate_report(payload: dict[str, Any] | None = None, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    payload = payload or {}
    run = IntelligenceRun(tenant_id=tenant_id, workspace_id=payload.get("workspace_id"), run_type="report_generate", question=str(payload), input_context_json=payload, output_json={"message": "Report generated from available evidence metadata."}, citations_json=[], status="completed")
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"status": "ok", "report": {"id": run.id, "summary": "Report generated from available evidence metadata.", "input": payload}}


@router.post("/reports/export")
def export_report(payload: dict[str, Any] | None = None, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    return generate_report(payload, tenant_id, db)


@router.get("/reports")
def list_reports(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    rows = db.query(IntelligenceRun).filter(IntelligenceRun.tenant_id == tenant_id, IntelligenceRun.run_type.like("%report%")).order_by(IntelligenceRun.created_at.desc()).limit(50).all()
    return {"status": "ok", "reports": [row_to_dict(row) for row in rows]}


@router.get("/artifacts")
def list_artifacts(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    verify_connector_schema(db)
    rows = db.query(GeneratedArtifact).filter(GeneratedArtifact.tenant_id == tenant_id).order_by(GeneratedArtifact.created_at.desc()).limit(50).all()
    return {"status": "ok", "artifacts": [row_to_dict(row) for row in rows]}
