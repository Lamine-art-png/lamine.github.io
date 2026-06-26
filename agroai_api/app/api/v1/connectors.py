"""AGRO-AI connector hub.

These endpoints expose the product connector catalog and start setup flows.
They do not store provider credentials yet. Live provider credentials must be
handled by a secure vault flow before operational sync is enabled.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.security import require_current_tenant_id


router = APIRouter(prefix="/connectors", tags=["connectors"])


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


class ConnectorStartRequest(BaseModel):
    provider: ProviderId
    method: str = Field(default="guided_setup")
    metadata: dict[str, Any] = Field(default_factory=dict)


CATALOG: list[dict[str, Any]] = [
    {
        "id": "wiseconn",
        "name": "WiseConn",
        "category": "Irrigation controllers",
        "status": "missing_credentials",
        "required_plan": "pilot",
        "connection_methods": ["api_credentials", "export_upload"],
        "imports": ["farms", "zones", "controller events", "flow", "irrigation history", "valve state"],
        "used_by": ["Decisions", "Evidence", "Reports", "Assurance"],
        "promise": "Turn WiseConn controller history into cited irrigation decisions and assurance records.",
    },
    {
        "id": "talgil",
        "name": "Talgil",
        "category": "Irrigation controllers",
        "status": "missing_credentials",
        "required_plan": "pilot",
        "connection_methods": ["api_credentials", "export_upload"],
        "imports": ["targets", "program state", "valve state", "flow", "irrigation events"],
        "used_by": ["Decisions", "Evidence", "Reports", "Assurance"],
        "promise": "Transform Talgil controller evidence into water operations intelligence.",
    },
    {
        "id": "weather",
        "name": "Weather / Forecast",
        "category": "Environmental data",
        "status": "not_configured",
        "required_plan": "pilot",
        "connection_methods": ["managed_provider", "api_credentials"],
        "imports": ["temperature", "precipitation", "humidity", "forecast"],
        "used_by": ["Decisions", "Reports"],
        "promise": "Bring weather context into irrigation recommendations and risk flags.",
    },
    {
        "id": "openet",
        "name": "OpenET / ET data",
        "category": "Water intelligence",
        "status": "not_configured",
        "required_plan": "pro",
        "connection_methods": ["managed_provider", "api_credentials"],
        "imports": ["ET", "ET0", "field water use estimates"],
        "used_by": ["Decisions", "Assurance", "Reports"],
        "promise": "Add satellite ET context to field-level water accounting.",
    },
    {
        "id": "manual_csv",
        "name": "CSV / PDF / Spreadsheet upload",
        "category": "Manual evidence",
        "status": "upload_ready",
        "required_plan": "free",
        "connection_methods": ["upload"],
        "imports": ["CSV", "PDF", "spreadsheets", "operator notes", "field logs"],
        "used_by": ["Evidence", "Reports", "Ask AGRO-AI"],
        "promise": "Upload fragmented evidence and let AGRO-AI structure it into field context.",
    },
    {
        "id": "gmail",
        "name": "Gmail",
        "category": "Email evidence",
        "status": "coming_soon",
        "required_plan": "pro",
        "connection_methods": ["oauth"],
        "imports": ["attachments", "operator emails", "reports", "vendor records"],
        "used_by": ["Evidence", "Reports", "Automations"],
        "promise": "Pull approved agricultural evidence from email threads and attachments.",
    },
    {
        "id": "outlook",
        "name": "Outlook",
        "category": "Email evidence",
        "status": "coming_soon",
        "required_plan": "pro",
        "connection_methods": ["oauth"],
        "imports": ["attachments", "operator emails", "reports", "vendor records"],
        "used_by": ["Evidence", "Reports", "Automations"],
        "promise": "Bring Microsoft email evidence into the same proof layer.",
    },
    {
        "id": "google_drive",
        "name": "Google Drive",
        "category": "Document evidence",
        "status": "coming_soon",
        "required_plan": "pro",
        "connection_methods": ["oauth"],
        "imports": ["folders", "PDFs", "spreadsheets", "reports"],
        "used_by": ["Evidence", "Reports"],
        "promise": "Connect field folders and keep reports/evidence synced.",
    },
    {
        "id": "custom_api",
        "name": "Custom API",
        "category": "Enterprise systems",
        "status": "enterprise",
        "required_plan": "enterprise",
        "connection_methods": ["api_contract", "webhook", "sftp"],
        "imports": ["ERP records", "district records", "sensor APIs", "custom telemetry"],
        "used_by": ["Enterprise deployments"],
        "promise": "Connect district, agribusiness, or enterprise systems into AGRO-AI.",
    },
]


@router.get("/catalog")
async def connector_catalog(
    tenant_id: str = Depends(require_current_tenant_id),
) -> dict[str, Any]:
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "connectors": CATALOG,
        "principles": [
            "No fake live connections.",
            "Evaluation data is clearly labeled.",
            "Credentials require secure setup before live sync.",
            "Every imported source becomes citation-ready evidence.",
        ],
    }


@router.post("/start")
async def start_connector_setup(
    payload: ConnectorStartRequest,
    tenant_id: str = Depends(require_current_tenant_id),
) -> dict[str, Any]:
    connector = next((item for item in CATALOG if item["id"] == payload.provider), None)
    if connector is None:
        return {
            "status": "unavailable",
            "message": "Connector is not available.",
            "tenant_id": tenant_id,
        }

    return {
        "status": "setup_started",
        "tenant_id": tenant_id,
        "provider": payload.provider,
        "connector": connector,
        "setup_url": f"/integrations?setup={payload.provider}",
        "credential_storage": "secure_vault_required_before_live_sync",
        "live_sync_enabled": False,
        "steps": [
            "Choose connection method",
            "Enter credentials or upload export",
            "Test connection",
            "Map farms, zones, blocks, and telemetry fields",
            "Review imported evidence",
            "Enable scheduled sync",
        ],
        "warning": "Do not paste production credentials into unsecured notes or chat. Use the portal credential vault when enabled.",
    }
