"""Functional connector, evidence, Ask AGRO-AI, report, and artifact endpoints.

This router intentionally does not fake live WiseConn/Talgil/OpenET sync. It makes
export/manual upload useful immediately while keeping live API claims honest.
"""
from __future__ import annotations

import csv
import io
import os
import json
import hashlib
import re
import urllib.parse
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import inspect, text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_current_tenant_id
from app.db.base import Base, get_db
from app.models.block import Block
from app.models.operational_records import (
    ConnectorConnection,
    DataSource,
    EvidenceRecord,
    GeneratedArtifact,
    IngestionJob,
    IntelligenceRun,
)
from app.models.saas import Workspace


router = APIRouter(tags=["operational-intelligence"])

ProviderId = Literal[
    "wiseconn",
    "talgil",
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
        "used_by": ["Decisions", "Evidence", "Reports", "Assurance"],
        "promise": "Upload WiseConn exports now; enable live sync later when credentials are configured.",
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
        "used_by": ["Decisions", "Evidence", "Reports", "Assurance"],
        "promise": "Upload Talgil/controller exports now; enable live sync later when credentials are configured.",
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
    {
        "id": "gmail",
        "name": "Gmail",
        "category": "Email evidence",
        "status": "coming_soon",
        "required_plan": "pro",
        "connection_methods": ["oauth"],
        "upload_supported": False,
        "imports": ["attachments", "operator emails", "reports", "vendor records"],
        "used_by": ["Evidence", "Reports"],
        "promise": "OAuth email evidence ingestion is prepared but not enabled yet.",
    },
    {
        "id": "outlook",
        "name": "Outlook",
        "category": "Email evidence",
        "status": "coming_soon",
        "required_plan": "pro",
        "connection_methods": ["oauth"],
        "upload_supported": False,
        "imports": ["attachments", "operator emails", "reports", "vendor records"],
        "used_by": ["Evidence", "Reports"],
        "promise": "OAuth email evidence ingestion is prepared but not enabled yet.",
    },
    {
        "id": "google_drive",
        "name": "Google Drive",
        "category": "Document evidence",
        "status": "coming_soon",
        "required_plan": "pro",
        "connection_methods": ["oauth"],
        "upload_supported": False,
        "imports": ["folders", "PDFs", "spreadsheets", "reports"],
        "used_by": ["Evidence", "Reports"],
        "promise": "Drive sync is prepared but not enabled yet.",
    },
    {
        "id": "dropbox",
        "name": "Dropbox",
        "category": "Document evidence",
        "status": "not_configured",
        "required_plan": "pro",
        "connection_methods": ["oauth"],
        "upload_supported": False,
        "imports": ["folders", "files", "PDFs", "spreadsheets", "image metadata"],
        "used_by": ["Evidence", "Reports", "Assurance"],
        "promise": "OAuth Dropbox folder evidence ingestion is ready when the Dropbox client ID is configured.",
        "required_env": ["DROPBOX_OAUTH_CLIENT_ID"],
    },
    {
        "id": "box",
        "name": "Box",
        "category": "Document evidence",
        "status": "not_configured",
        "required_plan": "pro",
        "connection_methods": ["oauth"],
        "upload_supported": False,
        "imports": ["folders", "files", "PDFs", "spreadsheets", "enterprise records"],
        "used_by": ["Evidence", "Reports", "Assurance"],
        "promise": "OAuth Box folder evidence ingestion is ready when the Box client ID is configured.",
        "required_env": ["BOX_OAUTH_CLIENT_ID"],
    },
    {
        "id": "slack",
        "name": "Slack",
        "category": "Operations context",
        "status": "not_configured",
        "required_plan": "pro",
        "connection_methods": ["oauth"],
        "upload_supported": False,
        "imports": ["channels", "messages", "files", "operator handoffs"],
        "used_by": ["Evidence", "Ask AGRO-AI", "Reports"],
        "promise": "OAuth Slack context ingestion is ready when the Slack client ID is configured.",
        "required_env": ["SLACK_OAUTH_CLIENT_ID"],
    },
    {
        "id": "salesforce",
        "name": "Salesforce",
        "category": "Customer operations",
        "status": "not_configured",
        "required_plan": "enterprise",
        "connection_methods": ["oauth"],
        "upload_supported": False,
        "imports": ["accounts", "contacts", "cases", "opportunities", "customer notes"],
        "used_by": ["Reports", "Assurance", "Customer success"],
        "promise": "OAuth Salesforce context is ready when the Salesforce client ID is configured.",
        "required_env": ["SALESFORCE_OAUTH_CLIENT_ID"],
    },
    {
        "id": "google_earth_engine",
        "name": "Google Earth Engine",
        "category": "Geospatial intelligence",
        "status": "not_configured",
        "required_plan": "enterprise",
        "connection_methods": ["service_account"],
        "upload_supported": False,
        "imports": ["field imagery", "ET/geospatial layers", "remote sensing context", "project assets"],
        "used_by": ["Decisions", "Reports", "Assurance"],
        "promise": "Google Earth Engine is ready when project and service-account env vars are configured.",
        "required_env": ["GOOGLE_EARTH_ENGINE_PROJECT_ID", "GOOGLE_EARTH_ENGINE_SERVICE_ACCOUNT_JSON"],
    },
    {
        "id": "custom_api",
        "name": "Custom API",
        "category": "Enterprise systems",
        "status": "enterprise",
        "required_plan": "enterprise",
        "connection_methods": ["custom_api"],
        "upload_supported": False,
        "imports": ["ERP records", "district records", "sensor APIs", "custom telemetry"],
        "used_by": ["Enterprise deployments"],
        "promise": "Connect district, agribusiness, or enterprise systems through a contract-specific API.",
    },
]

TABLES = [
    ConnectorConnection.__table__,
    DataSource.__table__,
    IngestionJob.__table__,
    EvidenceRecord.__table__,
    IntelligenceRun.__table__,
    GeneratedArtifact.__table__,
]

CANONICAL_FIELDS = {
    "timestamp": ["timestamp", "datetime", "date", "time", "start", "end", "occurred"],
    "field": ["field", "ranch", "farm", "parcel"],
    "block": ["block", "zone", "station", "plot", "sector"],
    "crop": ["crop", "variety"],
    "soil": ["soil"],
    "flow_rate": ["flow", "gpm", "lps", "rate"],
    "water_volume": ["gallon", "acre_feet", "acre-foot", "volume", "water", "inches", "mm", "m3"],
    "duration": ["duration", "minutes", "hours", "runtime", "run_time"],
    "valve_state": ["valve", "state", "status"],
    "pressure": ["pressure", "psi", "bar"],
    "et": ["et", "eto", "etc", "evapotranspiration"],
    "rainfall": ["rain", "precip", "precipitation"],
    "temperature": ["temp", "temperature"],
    "humidity": ["humidity", "rh"],
    "note": ["note", "comment", "description", "memo"],
}

CUSTOMER_MODE_LABELS = {
    "farmer": "Farmer",
    "farmland_manager": "Farmland Manager",
    "water_agency": "Water Agency",
    "lender": "Lender / Insurer",
    "insurer": "Lender / Insurer",
    "government": "Government Program",
    "consultant": "Consultant",
}


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


class AskRequest(BaseModel):
    question: str
    workspace_id: str | None = None
    block_id: str | None = None
    customer_mode: str = "farmland_manager"
    output_format: str = "answer"


class ReportGenerateRequest(BaseModel):
    report_type: str = "evidence_summary"
    workspace_id: str | None = None
    block_id: str | None = None
    format: Literal["markdown", "pdf"] = "markdown"


def ensure_schema(db: Session) -> None:
    """Create connector tables and gently add missing columns in deployed DBs.

    SQLAlchemy create_all() creates missing tables but does not alter existing
    tables. The production API may already have older connector tables, so file
    upload can 500 when DataSource/EvidenceRecord columns are missing. This keeps
    the connector hub self-healing until we formalize this into Alembic.
    """
    bind = db.get_bind()
    Base.metadata.create_all(bind=bind, tables=TABLES)

    inspector = inspect(bind)
    dialect = bind.dialect.name

    def ddl_type(column) -> str:
        name = column.type.__class__.__name__.lower()
        if "json" in name:
            return "JSONB" if dialect == "postgresql" else "JSON"
        if "datetime" in name:
            return "TIMESTAMP"
        if "float" in name:
            return "DOUBLE PRECISION" if dialect == "postgresql" else "FLOAT"
        return "TEXT"

    for table in TABLES:
        try:
            existing = {column["name"] for column in inspector.get_columns(table.name)}
        except Exception:
            continue

        for column in table.columns:
            if column.name in existing:
                continue

            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type(column)}'
            try:
                db.execute(sql_text(ddl))
                db.commit()
            except Exception:
                db.rollback()



SECRET_FIELD_HINTS = ("secret", "token", "password", "api_key", "apikey", "credential", "private_key")


def sanitize_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Never persist raw customer secrets in connector config JSON."""
    safe: dict[str, Any] = {}
    for key, value in (config or {}).items():
        lowered = key.lower()
        if any(hint in lowered for hint in SECRET_FIELD_HINTS):
            if value:
                digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
                safe[key] = f"submitted:{digest}"
            else:
                safe[key] = ""
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


def safe_filename(name: str | None) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "upload").strip("._")
    return base[:160] or "upload"


def save_upload_bytes(tenant_id: str, connection_id: str, filename: str | None, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()[:16]
    safe_name = safe_filename(filename)
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")

    roots = [
        Path(settings.CONNECTOR_UPLOAD_DIR),
        Path("/tmp/agroai_uploads"),
    ]

    for root in roots:
        try:
            target_dir = root / safe_filename(tenant_id) / safe_filename(connection_id)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{stamp}-{digest}-{safe_name}"
            target.write_bytes(data)
            return str(target)
        except OSError:
            continue

    # Last-resort: do not fail ingestion only because disk storage is unavailable.
    # Raw text and parsed rows are still stored in DataSource.metadata_json/raw_text.
    return f"inline://sha256/{digest}/{safe_name}"


def oauth_url(provider: str, state: str, redirect_url: str) -> tuple[str | None, str | None]:
    if provider in {"gmail", "google_drive"}:
        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "Missing GOOGLE_OAUTH_CLIENT_ID. Gmail/Drive OAuth cannot start yet."
        scopes = [
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/gmail.readonly" if provider == "gmail" else "https://www.googleapis.com/auth/drive.readonly",
        ]
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_url,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params), None

    if provider == "outlook":
        client_id = os.getenv("MICROSOFT_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "Missing MICROSOFT_OAUTH_CLIENT_ID. Outlook OAuth cannot start yet."
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_url,
            "response_type": "code",
            "scope": "offline_access openid profile email Mail.Read",
            "state": state,
        }
        return "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?" + urllib.parse.urlencode(params), None

    if provider == "dropbox":
        client_id = os.getenv("DROPBOX_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "Missing DROPBOX_OAUTH_CLIENT_ID. Dropbox OAuth cannot start yet."
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_url,
            "response_type": "code",
            "token_access_type": "offline",
            "state": state,
        }
        return "https://www.dropbox.com/oauth2/authorize?" + urllib.parse.urlencode(params), None

    if provider == "box":
        client_id = os.getenv("BOX_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "Missing BOX_OAUTH_CLIENT_ID. Box OAuth cannot start yet."
        params = {"client_id": client_id, "redirect_uri": redirect_url, "response_type": "code", "state": state}
        return "https://account.box.com/api/oauth2/authorize?" + urllib.parse.urlencode(params), None

    if provider == "slack":
        client_id = os.getenv("SLACK_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "Missing SLACK_OAUTH_CLIENT_ID. Slack OAuth cannot start yet."
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_url,
            "scope": "channels:read,files:read,users:read",
            "state": state,
        }
        return "https://slack.com/oauth/v2/authorize?" + urllib.parse.urlencode(params), None

    if provider == "salesforce":
        client_id = os.getenv("SALESFORCE_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return None, "Missing SALESFORCE_OAUTH_CLIENT_ID. Salesforce OAuth cannot start yet."
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_url,
            "response_type": "code",
            "scope": "api refresh_token",
            "state": state,
        }
        return "https://login.salesforce.com/services/oauth2/authorize?" + urllib.parse.urlencode(params), None

    return None, "Unsupported OAuth provider."



def catalog_item(provider: str) -> dict[str, Any] | None:
    return next((item for item in CATALOG if item["id"] == provider), None)


def connector_readiness(item: dict[str, Any]) -> dict[str, Any]:
    required = list(item.get("required_env") or [])
    missing = [name for name in required if not os.getenv(name, "").strip()]
    configured_env = [name for name in required if name not in missing]
    configured = not missing
    status = item.get("status", "available")
    if required:
        status = "service_account_ready" if configured and "service_account" in item.get("connection_methods", []) else "ready_to_authorize" if configured else "not_configured"
    return {
        **item,
        "configured": configured,
        "configured_env": configured_env,
        "missing_env": missing,
        "status": status,
    }


def row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def public_connection(row: ConnectorConnection) -> dict[str, Any]:
    data = row_to_dict(row)
    item = catalog_item(row.provider) or {}
    data.update(
        {
            "name": item.get("name", row.display_name),
            "category": item.get("category"),
            "connection_methods": item.get("connection_methods", []),
            "imports": item.get("imports", []),
            "upload_supported": item.get("upload_supported", False),
            "live_sync_enabled": row.status in {"synced", "syncing"} and bool(row.credentials_ref),
        }
    )
    return data


def evidence_public(row: EvidenceRecord) -> dict[str, Any]:
    data = row_to_dict(row)
    data["name"] = row.title
    data["source"] = row.citation_label
    data["domain"] = row.evidence_type
    data["status"] = row.quality_status
    return data


def create_or_get_connection(
    db: Session,
    *,
    tenant_id: str,
    provider: str,
    workspace_id: str | None = None,
    mode: str | None = None,
    display_name: str | None = None,
    config: dict[str, Any] | None = None,
) -> ConnectorConnection:
    ensure_schema(db)
    item = catalog_item(provider)
    if item is None:
        raise HTTPException(status_code=400, detail="Unsupported connector provider")
    query = db.query(ConnectorConnection).filter(
        ConnectorConnection.tenant_id == tenant_id,
        ConnectorConnection.provider == provider,
    )
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
    return {
        "status": "setup_started",
        "connection": public_connection(connection),
        "connector": item,
        "live_sync_enabled": False,
        "credential_storage": "secure_vault_required_before_live_sync",
        "steps": [
            "Choose upload or credential mode",
            "Upload export or save credential reference",
            "Test connection readiness",
            "Map fields",
            "Ingest evidence",
            "Ask AGRO-AI or generate report",
        ],
        "warning": "Live API sync is disabled until provider credentials and API contract are configured. Export upload works now.",
    }


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


def first_value(row: dict[str, Any], mapping: dict[str, str], canonical: str) -> Any:
    for source, target in mapping.items():
        if target == canonical and row.get(source) not in (None, ""):
            return row.get(source)
    for key, value in row.items():
        if key.lower() == canonical and value not in (None, ""):
            return value
    return None


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def infer_source_type(filename: str, content_type: str | None, provider: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf") or content_type == "application/pdf":
        return "pdf"
    if lower.endswith((".xls", ".xlsx")):
        return "spreadsheet"
    if lower.endswith((".json", ".geojson")):
        return "custom_api_payload"
    if lower.endswith((".txt", ".md")):
        return "text_document"
    if lower.endswith(".kml"):
        return "geospatial_file"
    if lower.endswith(".zip"):
        return "archive"
    if provider in {"wiseconn", "talgil"}:
        return "controller_export"
    return "telemetry_csv"


def infer_evidence_type(mapping: dict[str, str], provider: str, row: dict[str, Any]) -> str:
    targets = set(mapping.values())
    if provider in {"wiseconn", "talgil"} or "valve_state" in targets:
        return "irrigation_event"
    if "et" in targets:
        return "et_estimate"
    if {"rainfall", "temperature", "humidity"}.intersection(targets):
        return "weather_observation"
    if "flow_rate" in targets:
        return "flow_reading"
    if "water_volume" in targets or "duration" in targets:
        return "irrigation_event"
    if "document_text" in row:
        return "uploaded_document_fact"
    return "field_note"


def make_evidence(
    *,
    tenant_id: str,
    workspace_id: str | None,
    connection: ConnectorConnection,
    source: DataSource,
    row: dict[str, Any],
    index: int,
    mapping: dict[str, str],
) -> EvidenceRecord:
    occurred_at = parse_datetime(first_value(row, mapping, "timestamp"))
    field = first_value(row, mapping, "field")
    block = first_value(row, mapping, "block")
    crop = first_value(row, mapping, "crop")
    note = first_value(row, mapping, "note") or row.get("document_text") or row.get("note")
    evidence_type = infer_evidence_type(mapping, connection.provider, row)
    missing = []
    if not occurred_at:
        missing.append("timestamp")
    if evidence_type in {"irrigation_event", "flow_reading", "et_estimate"} and not (field or block):
        missing.append("field/block")
    values = {target: first_value(row, mapping, target) for target in set(mapping.values())}
    values = {k: v for k, v in values.items() if v not in (None, "")}
    if not values:
        values = {k: v for k, v in row.items() if v not in (None, "")}
    title_bits = [connection.provider.upper(), evidence_type.replace("_", " ")]
    if block or field:
        title_bits.append(str(block or field))
    summary = f"{evidence_type.replace('_', ' ').title()} from {connection.provider}"
    if block or field:
        summary += f" for {block or field}"
    if occurred_at:
        summary += f" on {occurred_at.date().isoformat()}"
    if note and evidence_type in {"field_note", "uploaded_document_fact"}:
        summary += f": {str(note)[:180]}"
    return EvidenceRecord(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data_source_id=source.id,
        connector_connection_id=connection.id,
        evidence_type=evidence_type,
        field_id=str(field) if field else None,
        block_id=str(block) if block else None,
        occurred_at=occurred_at,
        title=" · ".join(title_bits)[:250],
        summary=summary,
        value_json=values,
        units=str(values.get("units") or values.get("unit") or "") or None,
        confidence=0.58 if missing else 0.78,
        quality_status="incomplete" if missing else "usable",
        citation_label=f"{source.filename or connection.provider} row {index + 1}",
        source_excerpt=json.dumps(row, default=str)[:1000],
        metadata_json={"provider": connection.provider, "row_index": index, "crop": crop, "missing": missing},
    )


def get_evidence_rows(db: Session, tenant_id: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ensure_schema(db)
    query = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == tenant_id)
    filters = filters or {}
    for key, column in {
        "evidence_type": EvidenceRecord.evidence_type,
        "quality_status": EvidenceRecord.quality_status,
        "connector_connection_id": EvidenceRecord.connector_connection_id,
        "data_source_id": EvidenceRecord.data_source_id,
        "field_id": EvidenceRecord.field_id,
        "block_id": EvidenceRecord.block_id,
    }.items():
        if filters.get(key):
            query = query.filter(column == filters[key])
    return [evidence_public(row) for row in query.order_by(EvidenceRecord.created_at.desc()).limit(250).all()]


def get_evidence_summary(db: Session, tenant_id: str) -> dict[str, Any]:
    ensure_schema(db)
    records = db.query(EvidenceRecord).filter(EvidenceRecord.tenant_id == tenant_id).all()
    sources = db.query(DataSource).filter(DataSource.tenant_id == tenant_id).all()
    connections = db.query(ConnectorConnection).filter(ConnectorConnection.tenant_id == tenant_id).all()
    by_type = Counter(row.evidence_type for row in records)
    by_quality = Counter(row.quality_status for row in records)
    by_provider = Counter(source.provider for source in sources)
    missing = []
    if not records:
        missing.append("No uploaded/imported evidence yet")
    if not any(row.evidence_type in {"irrigation_event", "flow_reading"} for row in records):
        missing.append("Recent irrigation/controller evidence")
    if not any(row.evidence_type in {"weather_observation", "forecast", "et_estimate"} for row in records):
        missing.append("Weather or ET evidence")
    if not connections:
        missing.append("At least one configured connector")
    readiness = max(0, min(100, 20 + len(records) * 4 + len(connections) * 10 - len(missing) * 8))
    return {
        "status": "ok",
        "evidence_count": len(records),
        "source_count": len(sources),
        "connector_count": len(connections),
        "readiness_score": readiness,
        "by_type": dict(by_type),
        "by_quality": dict(by_quality),
        "by_provider": dict(by_provider),
        "newest_evidence_at": max((row.created_at for row in records), default=None),
        "oldest_evidence_at": min((row.created_at for row in records), default=None),
        "missing_data": missing,
        "connector_readiness": [public_connection(row) for row in connections],
    }


def context_for(db: Session, tenant_id: str, workspace_id: str | None = None, block_id: str | None = None) -> dict[str, Any]:
    workspace = db.get(Workspace, workspace_id) if workspace_id else None
    if not workspace:
        workspace = db.query(Workspace).filter(Workspace.organization_id == tenant_id).order_by(Workspace.created_at.asc()).first()
    block = db.query(Block).filter(Block.id == block_id, Block.tenant_id == tenant_id).first() if block_id else None
    if not block:
        block = db.query(Block).filter(Block.tenant_id == tenant_id).first()
    evidence = get_evidence_rows(db, tenant_id, {"block_id": block_id} if block_id else {})[:25]
    summary = get_evidence_summary(db, tenant_id)
    connections = db.query(ConnectorConnection).filter(ConnectorConnection.tenant_id == tenant_id).all()
    risks: list[str] = []
    if summary["evidence_count"] == 0:
        risks.append("No imported evidence exists yet. Answers are onboarding guidance, not operational decisions.")
    if summary["by_quality"].get("incomplete"):
        risks.append("Some evidence is incomplete and needs timestamp/field/block cleanup.")
    if not any(c.provider in {"wiseconn", "talgil"} for c in connections):
        risks.append("No controller connector is configured. Upload WiseConn/Talgil exports to improve decisions.")
    return {
        "workspace": row_to_dict(workspace) if workspace else None,
        "field_state": row_to_dict(block) if block else None,
        "evidence_summary": summary,
        "latest_evidence": evidence,
        "connector_status": [public_connection(row) for row in connections],
        "missing_data": summary["missing_data"],
        "risks": risks,
        "citations": [
            {
                "source_type": item.get("evidence_type"),
                "source_id": item.get("id"),
                "title": item.get("title") or item.get("name"),
                "citation_label": item.get("citation_label"),
            }
            for item in evidence[:10]
        ],
        "mode": "manual_upload" if summary["evidence_count"] else "demo",
    }


def deterministic_answer(question: str, context: dict[str, Any], customer_mode: str, output_format: str) -> dict[str, Any]:
    summary = context["evidence_summary"]
    evidence = context["latest_evidence"]
    label = CUSTOMER_MODE_LABELS.get(customer_mode, "Farmland Manager")
    used = [item.get("summary") or item.get("title") for item in evidence[:8]]
    if evidence:
        answer = (
            f"For a {label}, AGRO-AI found {summary['evidence_count']} imported evidence records from "
            f"{summary['source_count']} source file(s). Readiness is {summary['readiness_score']}%. "
            "Use this as a grounded operating brief, then close the missing-data gaps before treating it as a final field decision."
        )
    else:
        answer = (
            f"For a {label}, AGRO-AI cannot make a real operational decision yet because no customer evidence has been imported. "
            "Upload a WiseConn/Talgil/controller export, ET/weather file, or field log, then ask again."
        )
    if "overwatering" in question.lower() and evidence:
        answer += " I cannot confirm overwatering unless water volume/duration, crop stage, ET, and block context are present."
    if output_format == "checklist":
        answer += " Checklist: connect source, upload export, map fields, ingest evidence, ask AGRO-AI, generate report."
    next_actions = [
        "Upload or connect the most recent controller/irrigation export.",
        "Confirm field/block mapping and timestamps for imported rows.",
        "Add ET/weather evidence before treating recommendations as operational.",
        "Generate an evidence summary report for review.",
    ]
    return {
        "status": "ok",
        "answer": answer,
        "confidence": "medium" if evidence and not context.get("missing_data") else "low",
        "what_i_used": used,
        "what_is_missing": context.get("missing_data") or [],
        "missing_data": context.get("missing_data") or [],
        "risks": context.get("risks") or [],
        "next_actions": next_actions,
        "citations": context.get("citations") or [],
        "mode": context.get("mode"),
        "evidence_summary": summary,
    }


def save_run(db: Session, tenant_id: str, workspace_id: str | None, run_type: str, question: str | None, context: dict[str, Any], output: dict[str, Any]) -> IntelligenceRun:
    row = IntelligenceRun(
        tenant_id=tenant_id,
        workspace_id=workspace_id or (context.get("workspace") or {}).get("id"),
        run_type=run_type,
        question=question,
        input_context_json=context,
        output_json=output,
        citations_json=output.get("citations") or [],
        status="completed",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def report_markdown(report_type: str, context: dict[str, Any], answer: dict[str, Any]) -> str:
    summary = context["evidence_summary"]
    lines = [
        f"# AGRO-AI {report_type.replace('_', ' ').title()}",
        "",
        f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z",
        f"Mode: {context.get('mode', 'demo')}",
        "",
        "## Executive Summary",
        answer.get("answer", "No answer generated."),
        "",
        "## Evidence Summary",
        f"- Evidence records: {summary['evidence_count']}",
        f"- Source files: {summary['source_count']}",
        f"- Connector records: {summary['connector_count']}",
        f"- Readiness score: {summary['readiness_score']}%",
        "",
        "## Evidence Used",
    ]
    lines.extend([f"- {item}" for item in answer.get("what_i_used") or []] or ["- No imported evidence yet."])
    lines.extend(["", "## Missing Data"])
    lines.extend([f"- {item}" for item in answer.get("what_is_missing") or []] or ["- No missing data flagged."])
    lines.extend(["", "## Risks / Uncertainty"])
    lines.extend([f"- {item}" for item in answer.get("risks") or []] or ["- No risk flags returned."])
    lines.extend(["", "## Next Actions"])
    lines.extend([f"- {item}" for item in answer.get("next_actions") or []])
    lines.extend(["", "## Citations"])
    lines.extend([f"- {item.get('title') or item.get('citation_label') or item}" for item in answer.get("citations") or []] or ["- No citations available yet."])
    return "\n".join(lines) + "\n"


def pdf_bytes(title: str, body: str) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 54
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(54, y, title[:80])
    y -= 26
    pdf.setFont("Helvetica", 9)
    for line in body.splitlines():
        if y < 54:
            pdf.showPage()
            pdf.setFont("Helvetica", 9)
            y = height - 54
        clean = line.replace("#", "").strip()
        for chunk in [clean[i:i + 105] for i in range(0, len(clean), 105)] or [""]:
            pdf.drawString(54, y, chunk)
            y -= 13
    pdf.save()
    return buffer.getvalue()


@router.get("/connectors/catalog")
async def connector_catalog(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    connections = db.query(ConnectorConnection).filter(ConnectorConnection.tenant_id == tenant_id).all()
    by_provider = {row.provider: public_connection(row) for row in connections}
    connectors = []
    for item in CATALOG:
        ready = connector_readiness(item)
        live = by_provider.get(item["id"])
        connectors.append({**ready, "connection": live, "status": live.get("status", ready["status"]) if live else ready["status"]})
    return {"status": "ok", "tenant_id": tenant_id, "connectors": connectors, "principles": ["No fake live connections.", "Export upload works now.", "Every imported source becomes citation-ready evidence."]}


@router.get("/connectors/connections")
async def list_connections(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    rows = db.query(ConnectorConnection).filter(ConnectorConnection.tenant_id == tenant_id).order_by(ConnectorConnection.created_at.desc()).all()
    return {"status": "ok", "connections": [public_connection(row) for row in rows]}


@router.post("/connectors/connections")
async def create_connection(payload: ConnectorCreateRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode=payload.mode, display_name=payload.display_name, config=payload.config)
    return {"status": "ok", "connection": public_connection(row)}


@router.get("/connectors/connections/{connection_id}")
async def get_connection(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    row = db.get(ConnectorConnection, connection_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    return {"status": "ok", "connection": public_connection(row)}


@router.patch("/connectors/connections/{connection_id}")
async def patch_connection(connection_id: str, payload: ConnectorPatchRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    row = db.get(ConnectorConnection, connection_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    if payload.status:
        row.status = payload.status
    if payload.mode:
        row.mode = payload.mode
    if payload.display_name:
        row.display_name = payload.display_name
    if payload.credentials_ref is not None:
        row.credentials_ref = safe_credential_ref(payload.credentials_ref)
    if payload.config is not None:
        merged = dict(row.config_json or {})
        merged.update(sanitize_config(payload.config))
        row.config_json = merged
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return {"status": "ok", "connection": public_connection(row)}


@router.delete("/connectors/connections/{connection_id}")
async def delete_connection(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    row = db.get(ConnectorConnection, connection_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}


@router.post("/connectors/start")
async def start_connector_setup(payload: ConnectorStartRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    row = create_or_get_connection(db, tenant_id=tenant_id, provider=payload.provider, workspace_id=payload.workspace_id, mode=payload.method, config=payload.metadata)
    return setup_payload(row)


@router.post("/connectors/connections/{connection_id}/test")
async def test_connector(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    row = db.get(ConnectorConnection, connection_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    if row.mode in {"manual_upload", "export_upload"}:
        row.status = "ready"
        row.last_error = None
        message = "Upload mode is ready. Add a controller export, CSV, JSON, TXT, or PDF text file."
    elif not row.credentials_ref:
        row.status = "needs_credentials"
        row.last_error = "Credentials are required before live sync."
        message = "Credentials are required before live sync. No fake live connection was claimed."
    else:
        row.status = "test_passed"
        row.last_error = None
        message = "Credential reference exists. Provider-specific validation is next."
    row.last_test_at = datetime.utcnow()
    db.add(IngestionJob(tenant_id=tenant_id, workspace_id=row.workspace_id, connector_connection_id=row.id, job_type="api_test", status="completed" if not row.last_error else "completed_with_warnings", input_json={"provider": row.provider, "mode": row.mode}, output_json={"message": message, "live_sync_enabled": False}, completed_at=datetime.utcnow()))
    db.commit()
    db.refresh(row)
    return {"status": row.status, "message": message, "connection": public_connection(row)}


@router.post("/connectors/connections/{connection_id}/upload")
async def upload_connector_file(connection_id: str, file: UploadFile = File(...), tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    connection = db.get(ConnectorConnection, connection_id)
    if not connection or connection.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    item = catalog_item(connection.provider) or {}
    if not item.get("upload_supported"):
        raise HTTPException(status_code=400, detail="This connector does not support manual upload yet")
    data = await file.read()
    raw_text, rows, columns, warnings = parse_rows(file.filename or "upload", file.content_type, data)
    storage_path = save_upload_bytes(tenant_id, connection.id, file.filename or "upload", data)
    mapping = suggest_mapping(columns)
    source = DataSource(tenant_id=tenant_id, workspace_id=connection.workspace_id, connector_connection_id=connection.id, source_type=infer_source_type(file.filename or "upload", file.content_type, connection.provider), provider=connection.provider, filename=file.filename, content_type=file.content_type, storage_path=storage_path, raw_text=raw_text[:200000], metadata_json={"columns": columns, "parsed_rows": rows[:500], "mapping_suggestions": mapping}, status="parsed_with_warnings" if warnings else "parsed")
    db.add(source)
    db.flush()
    records = []
    for index, row in enumerate(rows[:500]):
        record = make_evidence(tenant_id=tenant_id, workspace_id=connection.workspace_id, connection=connection, source=source, row=row, index=index, mapping=mapping)
        db.add(record)
        records.append(record)
    connection.status = "synced" if records else "mapping_required"
    connection.last_sync_at = datetime.utcnow()
    job = IngestionJob(tenant_id=tenant_id, workspace_id=connection.workspace_id, connector_connection_id=connection.id, data_source_id=source.id, job_type="upload_parse", status="completed_with_warnings" if warnings else "completed", input_json={"filename": file.filename, "content_type": file.content_type}, output_json={"rows_parsed": len(rows), "columns": columns, "mapping_suggestions": mapping, "evidence_records_created": len(records), "warnings": warnings}, completed_at=datetime.utcnow())
    db.add(job)
    db.commit()
    return {"status": source.status, "connection": public_connection(connection), "data_source": row_to_dict(source), "job": row_to_dict(job), "rows_parsed": len(rows), "columns": columns, "mapping_suggestions": mapping, "evidence_records_created": len(records), "warnings": warnings, "evidence_preview": [evidence_public(record) for record in records[:5]]}


@router.get("/connectors/connections/{connection_id}/mapping/suggestions")
async def mapping_suggestions(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    row = db.get(ConnectorConnection, connection_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    source = db.query(DataSource).filter(DataSource.connector_connection_id == row.id).order_by(DataSource.created_at.desc()).first()
    columns = ((source.metadata_json or {}).get("columns") if source else []) or []
    return {"status": "ok", "connection_id": connection_id, "columns": columns, "mapping_suggestions": suggest_mapping(columns)}


@router.post("/connectors/connections/{connection_id}/mapping")
async def save_mapping(connection_id: str, payload: MappingRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    row = db.get(ConnectorConnection, connection_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    config = dict(row.config_json or {})
    config["field_mapping"] = payload.mapping
    row.config_json = config
    row.status = "ready"
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "connection": public_connection(row), "mapping": payload.mapping}


@router.post("/connectors/connections/{connection_id}/sync")
async def sync_connection(connection_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    row = db.get(ConnectorConnection, connection_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Connection not found")
    if row.mode in {"api_credentials", "oauth", "custom_api"} and not row.credentials_ref:
        row.status = "needs_credentials"
        row.last_error = "Credentials are required before live sync."
        db.commit()
        return {"status": "needs_credentials", "message": "No live sync performed. Add credential reference or use export upload.", "connection": public_connection(row)}
    source_count = db.query(DataSource).filter(DataSource.connector_connection_id == row.id).count()
    evidence_count = db.query(EvidenceRecord).filter(EvidenceRecord.connector_connection_id == row.id).count()
    row.status = "synced" if evidence_count else "mapping_required"
    row.last_sync_at = datetime.utcnow()
    db.commit()
    return {"status": row.status, "source_count": source_count, "evidence_records": evidence_count, "connection": public_connection(row)}


@router.get("/evidence")
async def list_evidence(provider: str | None = None, evidence_type: str | None = None, quality_status: str | None = None, connector_connection_id: str | None = None, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    filters = {"evidence_type": evidence_type, "quality_status": quality_status, "connector_connection_id": connector_connection_id}
    rows = get_evidence_rows(db, tenant_id, filters)
    if provider:
        rows = [row for row in rows if (row.get("metadata_json") or {}).get("provider") == provider]
    return {"status": "ok", "records": rows, "evidence": rows, "summary": get_evidence_summary(db, tenant_id)}


@router.get("/evidence/summary")
async def evidence_summary_endpoint(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_evidence_summary(db, tenant_id)


@router.post("/intelligence/ask")
async def ask_agro_ai(payload: AskRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    context = context_for(db, tenant_id, payload.workspace_id, payload.block_id)
    output = deterministic_answer(payload.question, context, payload.customer_mode, payload.output_format)
    run = save_run(db, tenant_id, payload.workspace_id, "ask", payload.question, context, output)
    output["run_id"] = run.id
    return output


@router.post("/reports/generate")
async def generate_report(payload: ReportGenerateRequest, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    context = context_for(db, tenant_id, payload.workspace_id, payload.block_id)
    answer = deterministic_answer(f"Generate {payload.report_type}", context, "farmland_manager", "report")
    run = save_run(db, tenant_id, payload.workspace_id, "report_draft", f"Generate {payload.report_type}", context, answer)
    markdown = report_markdown(payload.report_type, context, answer)
    is_pdf = payload.format == "pdf"
    artifact = GeneratedArtifact(tenant_id=tenant_id, workspace_id=payload.workspace_id or (context.get("workspace") or {}).get("id"), intelligence_run_id=run.id, artifact_type="pdf_report" if is_pdf else "markdown_report", title=f"AGRO-AI {payload.report_type.replace('_', ' ').title()}", filename=f"agro-ai-{payload.report_type}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{'pdf' if is_pdf else 'md'}", content_type="application/pdf" if is_pdf else "text/markdown", body_text=markdown, metadata_json={"report_type": payload.report_type, "format": payload.format, "readiness_score": context["evidence_summary"]["readiness_score"]})
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return {"status": "ok", "artifact": row_to_dict(artifact), "preview": markdown[:4000], "answer": answer}


@router.get("/reports")
async def list_reports(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    rows = db.query(GeneratedArtifact).filter(GeneratedArtifact.tenant_id == tenant_id).order_by(GeneratedArtifact.created_at.desc()).limit(100).all()
    return {"status": "ok", "reports": [row_to_dict(row) for row in rows], "items": [row_to_dict(row) for row in rows]}


@router.post("/reports/export")
async def legacy_export(payload: dict[str, Any] | None = None, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    request = ReportGenerateRequest(report_type=(payload or {}).get("report_type", "evidence_summary"), workspace_id=(payload or {}).get("workspace_id"), format=(payload or {}).get("format", "pdf"))
    return await generate_report(request, tenant_id, db)


@router.get("/artifacts")
async def list_artifacts(tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    rows = db.query(GeneratedArtifact).filter(GeneratedArtifact.tenant_id == tenant_id).order_by(GeneratedArtifact.created_at.desc()).limit(100).all()
    return {"status": "ok", "artifacts": [row_to_dict(row) for row in rows]}


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    ensure_schema(db)
    row = db.get(GeneratedArtifact, artifact_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"status": "ok", "artifact": row_to_dict(row)}


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: str, tenant_id: str = Depends(require_current_tenant_id), db: Session = Depends(get_db)) -> Response:
    ensure_schema(db)
    row = db.get(GeneratedArtifact, artifact_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    body = row.body_text or ""
    if row.content_type == "application/pdf":
        content = pdf_bytes(row.title, body)
    else:
        content = body.encode("utf-8")
    return Response(content=content, media_type=row.content_type, headers={"Content-Disposition": f'attachment; filename="{row.filename}"'})



@router.post("/evidence/upload")
async def upload_evidence_file(
    provider: ProviderId = Query(default="manual_csv"),
    workspace_id: str | None = Query(default=None),
    file: UploadFile = File(...),
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """One-step upload for customers who do not want to configure a connector first."""
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=provider,
        workspace_id=workspace_id,
        mode="manual_upload" if provider in {"manual_csv", "chat_upload"} else "export_upload",
        display_name=(catalog_item(provider) or {}).get("name"),
        config={"created_from": "direct_evidence_upload"},
    )
    return await upload_connector_file(connection.id, file, tenant_id, db)


@router.post("/connectors/oauth/start")
async def start_oauth_connector(
    payload: OAuthStartRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start a real OAuth authorization URL when provider client IDs exist.

    This is intentionally honest: without Google/Microsoft app credentials, the
    API returns oauth_config_missing instead of pretending the account connected.
    """
    redirect_url = (
        payload.redirect_url
        or os.getenv("AGROAI_OAUTH_REDIRECT_URL", "").strip()
        or f"{settings.APP_URL.rstrip('/')}/integrations/oauth/callback"
    )
    connection = create_or_get_connection(
        db,
        tenant_id=tenant_id,
        provider=payload.provider,
        workspace_id=payload.workspace_id,
        mode="oauth",
        display_name=(catalog_item(payload.provider) or {}).get("name"),
        config={"oauth_requested": True, **sanitize_config(payload.metadata)},
    )
    state = hashlib.sha256(f"{tenant_id}:{connection.id}:{datetime.utcnow().isoformat()}".encode("utf-8")).hexdigest()
    auth_url, error = oauth_url(payload.provider, state, redirect_url)

    if error:
        connection.status = "oauth_config_missing"
        connection.last_error = error
        db.commit()
        return {
            "status": "oauth_config_missing",
            "message": error,
            "connection": public_connection(connection),
            "auth_url": None,
            "next_step": "Create a Google/Microsoft OAuth app, add client ID env vars, then retry.",
        }

    connection.status = "oauth_ready"
    connection.last_error = None
    connection.config_json = {
        **(connection.config_json or {}),
        "oauth_state": state,
        "redirect_url": redirect_url,
    }
    db.commit()
    return {
        "status": "oauth_ready",
        "message": "OAuth authorization URL created.",
        "connection": public_connection(connection),
        "auth_url": auth_url,
        "redirect_url": redirect_url,
    }
