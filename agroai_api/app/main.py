# agroai_api/app/main.py

from __future__ import annotations

import datetime
import io
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings

logger = logging.getLogger(__name__)

VERSION = "2.0.0"


def ensure_saas_portal_runtime_schema() -> None:
    """Repair the small v2.1 auth schema before request handling."""

    try:
        from app.db.base import engine

        with engine.begin() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            if "users" not in tables:
                return

            user_columns = {column["name"] for column in inspector.get_columns("users")}
            if "email_verified_at" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMP"))
            if "email_verification_status" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN email_verification_status VARCHAR DEFAULT 'unverified'"))
            connection.execute(text("UPDATE users SET email_verification_status = 'unverified' WHERE email_verification_status IS NULL"))

            if "email_verification_tokens" not in tables:
                connection.execute(text("""
                    CREATE TABLE IF NOT EXISTS email_verification_tokens (
                        id VARCHAR PRIMARY KEY,
                        user_id VARCHAR NOT NULL,
                        token_hash VARCHAR NOT NULL UNIQUE,
                        expires_at TIMESTAMP NOT NULL,
                        used_at TIMESTAMP,
                        created_at TIMESTAMP NOT NULL
                    )
                """))

            if "team_invitations" not in tables:
                connection.execute(text("""
                    CREATE TABLE IF NOT EXISTS team_invitations (
                        id VARCHAR PRIMARY KEY,
                        organization_id VARCHAR NOT NULL,
                        email VARCHAR NOT NULL,
                        role VARCHAR NOT NULL,
                        status VARCHAR NOT NULL,
                        invited_by_user_id VARCHAR NOT NULL,
                        token_hash VARCHAR UNIQUE,
                        expires_at TIMESTAMP,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL
                    )
                """))
    except SQLAlchemyError:
        logger.exception("SaaS Portal v2.1 runtime schema guard failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle — starts scheduler after Alembic migrations."""

    ensure_saas_portal_runtime_schema()

    if settings.ENABLE_SCHEDULER and settings.WISECONN_API_KEY:
        from app.core.scheduler import start_scheduler

        start_scheduler()
        logger.info("Scheduler started — first sync will run on next interval")
    else:
        logger.info("Background scheduler disabled (ENABLE_SCHEDULER=%s, API key set=%s)",
                    settings.ENABLE_SCHEDULER, bool(settings.WISECONN_API_KEY))

    yield

    if settings.ENABLE_SCHEDULER:
        from app.core.scheduler import stop_scheduler
        stop_scheduler()


app = FastAPI(
    title="AGRO-AI API",
    version=VERSION,
    lifespan=lifespan,
)

ALLOWED_ORIGINS = [
    "https://app.agroai-pilot.com",
    "https://agroai-pilot.com",
    "https://www.agroai-pilot.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if getattr(settings, "APP_URL", "") and settings.APP_URL not in ALLOWED_ORIGINS:
    ALLOWED_ORIGINS.append(settings.APP_URL)

ALLOWED_ORIGIN_REGEX = r"^https://([a-z0-9-]+\.)?(agroai-portal|lamine-github-io|agroai-command-center-v2-preview)\.pages\.dev$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def health_payload() -> Dict[str, str]:
    return {
        "status": "ok",
        "service": "agroai-api",
        "version": VERSION,
        "checked_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


@app.get("/health")
async def health_root() -> Dict[str, str]:
    return await health_payload()


@app.get("/v1/health")
async def health_v1() -> Dict[str, str]:
    return await health_payload()


@app.get("/v1/auth/email-delivery/status")
async def email_delivery_runtime_status() -> Dict[str, Any]:
    from app.services.email_delivery import delivery_status

    current = delivery_status()
    return {
        "configured": current.get("configured"),
        "provider": current.get("provider"),
        "missing_env": current.get("missing_env", []),
        "from_email_configured": current.get("from_email_configured"),
        "from_email_domain": current.get("from_email_domain"),
        "resend_configured": current.get("resend_configured"),
        "sendgrid_configured": current.get("sendgrid_configured"),
        "smtp_configured": current.get("smtp_configured"),
        "resend_app_url_configured": current.get("resend_app_url_configured"),
        "verification_base_url": current.get("verification_base_url"),
    }


from app.api.v1.auth import router as auth_router  # noqa: E402
from app.api.v1.billing import router as billing_router  # noqa: E402

app.include_router(auth_router, prefix="/v1")
app.include_router(billing_router, prefix="/v1")

from app.api.v1.saas import router as saas_router  # noqa: E402
app.include_router(saas_router, prefix="/v1")

from app.api.v1.assurance import router as assurance_router  # noqa: E402
app.include_router(assurance_router, prefix="/v1")

from app.api.v1.wiseconn import router as wiseconn_router  # noqa: E402
app.include_router(wiseconn_router, prefix="/v1")

from app.api.v1.decisioning import router as decisioning_router  # noqa: E402
app.include_router(decisioning_router, prefix="/v1")

from app.api.v1.execution_assurance import router as execution_router  # noqa: E402
app.include_router(execution_router, prefix="/v1")

from app.api.v1.forecast import router as forecast_router  # noqa: E402
app.include_router(forecast_router, prefix="/v1")

from app.api.v1.intelligence import router as intelligence_router  # noqa: E402
app.include_router(intelligence_router, prefix="/v1")

from app.api.v1.workbench import router as workbench_router  # noqa: E402
app.include_router(workbench_router, prefix="/v1")

from app.api.v1.compliance import router as compliance_router  # noqa: E402
app.include_router(compliance_router, prefix="/v1")
from app.api.v1.controllers import router as controllers_router  # noqa: E402
app.include_router(controllers_router, prefix="/v1")

from app.api.v1.talgil import router as talgil_router  # noqa: E402
app.include_router(talgil_router, prefix="/v1")

from app.api.v1.ai import router as ai_router  # noqa: E402
app.include_router(ai_router, prefix="/v1")

from app.api.v1.agents import router as agents_router  # noqa: E402
app.include_router(agents_router, prefix="/v1")

from app.api.v1.platform_intelligence import router as platform_intelligence_router  # noqa: E402
app.include_router(platform_intelligence_router, prefix="/v1")

from app.api.v1.connector_hub import router as connector_hub_router  # noqa: E402
app.include_router(connector_hub_router, prefix="/v1")

from app.api.v1.connector_launch import router as connector_launch_router  # noqa: E402
app.include_router(connector_launch_router, prefix="/v1")

from app.api.v1.connectors import router as connectors_router  # noqa: E402
app.include_router(connectors_router, prefix="/v1")

from app.api.v1.operator_cockpit import router as operator_cockpit_router  # noqa: E402
app.include_router(operator_cockpit_router, prefix="/v1")

from app.api.v1.field_operations import router as field_operations_router  # noqa: E402
app.include_router(field_operations_router, prefix="/v1")