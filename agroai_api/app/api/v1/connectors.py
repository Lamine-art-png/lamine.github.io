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
        "used_by": ["Decisions", "Evidence", "Reports", "Assurance", "Agentic actions"],
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
        "used_by": ["Decisions", "Evidence", "Reports", "Assurance", "Agentic actions"],
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
        "imports": [
            "farms",
            "fields",
            "blocks",
            "zones",
            "valves",
            "pumps",
            "flow",
            "pressure",
            "irrigation events",
            "program schedules",
            "operator notes",
        ],
        "used_by": ["Ask AGRO-AI", "Decisions", "Evidence", "Reports", "Assurance", "Agentic actions", "Controller readiness"],
        "promise": "Bring any controller system into AGRO-AI through exports, API credentials, or a provider-assisted connector. AGRO-AI normalizes the data into one operating model before any physical execution is considered.",
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
