# agroai_api/app/main.py

from __future__ import annotations

import datetime
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings

logger = logging.getLogger(__name__)

VERSION = "2.0.0"


def _ensure_column(connection, inspector, table: str, column: str, ddl: str) -> None:
    columns = {item["name"] for item in inspector.get_columns(table)}
    if column not in columns:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_saas_portal_runtime_schema() -> None:
    """Repair the small v2.1 auth schema before request handling.

    Alembic remains the source of truth. This is an emergency runtime guard for
    production so auth/email verification does not fail when a Render startup
    migration was partial, skipped, or blocked by existing objects.
    """

    try:
        from app.db.base import engine

        with engine.begin() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            if "users" not in tables:
                return

            _ensure_column(connection, inspector, "users", "email_verified_at", "email_verified_at TIMESTAMP")
            inspector = inspect(connection)
            _ensure_column(connection, inspector, "users", "email_verification_status", "email_verification_status VARCHAR DEFAULT 'unverified'")
            connection.execute(text("UPDATE users SET email_verification_status = 'unverified' WHERE email_verification_status IS NULL"))

            tables = set(inspect(connection).get_table_names())
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
            else:
                inspector = inspect(connection)
                for column, ddl in [
                    ("id", "id VARCHAR"),
                    ("user_id", "user_id VARCHAR"),
                    ("token_hash", "token_hash VARCHAR"),
                    ("expires_at", "expires_at TIMESTAMP"),
                    ("used_at", "used_at TIMESTAMP"),
                    ("created_at", "created_at TIMESTAMP"),
                ]:
                    _ensure_column(connection, inspector, "email_verification_tokens", column, ddl)
                    inspector = inspect(connection)

            tables = set(inspect(connection).get_table_names())
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
            else:
                inspector = inspect(connection)
                for column, ddl in [
                    ("id", "id VARCHAR"),
                    ("organization_id", "organization_id VARCHAR"),
                    ("email", "email VARCHAR"),
                    ("role", "role VARCHAR"),
                    ("status", "status VARCHAR"),
                    ("invited_by_user_id", "invited_by_user_id VARCHAR"),
                    ("token_hash", "token_hash VARCHAR"),
                    ("expires_at", "expires_at TIMESTAMP"),
                    ("created_at", "created_at TIMESTAMP"),
                    ("updated_at", "updated_at TIMESTAMP"),
                ]:
                    _ensure_column(connection, inspector, "team_invitations", column, ddl)
                    inspector = inspect(connection)
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
    "https://api.agroai-pilot.com",
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
    expose_headers=["x-agroai-runtime", "x-agroai-error"],
)


def _origin_allowed(origin: str) -> bool:
    if origin in ALLOWED_ORIGINS:
        return True
    return bool(origin.endswith(".pages.dev") and ("agroai-portal" in origin or "lamine-github-io" in origin or "agroai-command-center-v2-preview" in origin))


def _add_runtime_cors_headers(response: JSONResponse, origin: str | None) -> JSONResponse:
    if origin and _origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Vary"] = "Origin"
    response.headers["x-agroai-runtime"] = VERSION
    return response


@app.middleware("http")
async def runtime_error_boundary(request: Request, call_next):
    """Keep browser diagnostics truthful even when a route crashes.

    Without this, an internal 500 can appear in Chrome as a CORS failure, which
    hides the real backend issue. This middleware preserves CORS headers and
    returns a small JSON error envelope instead of letting the browser lie.
    """

    origin = request.headers.get("origin")
    try:
        response = await call_next(request)
    except Exception as exc:  # pragma: no cover - production safety boundary
        logger.exception("Unhandled API error path=%s", request.url.path)
        payload = {
            "status": "error",
            "error": "backend_runtime_error",
            "path": request.url.path,
            "reason": exc.__class__.__name__,
            "checked_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        response = JSONResponse(payload, status_code=500)
        response.headers["x-agroai-error"] = exc.__class__.__name__
        return _add_runtime_cors_headers(response, origin)

    if origin and _origin_allowed(origin):
        response.headers.setdefault("Access-Control-Allow-Origin", origin)
        response.headers.setdefault("Access-Control-Allow-Credentials", "true")
        response.headers.setdefault("Vary", "Origin")
    response.headers.setdefault("x-agroai-runtime", VERSION)
    return response


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


@app.get("/v1/runtime/ai-status")
async def ai_runtime_status() -> Dict[str, Any]:
    from app.services.model_router import ModelRouter

    router = ModelRouter()
    status_payload = router.status()
    return {
        "status": "ok",
        "runtime": VERSION,
        "configured": status_payload.get("configured"),
        "provider": status_payload.get("provider"),
        "mode": status_payload.get("mode"),
        "base_url_present": status_payload.get("base_url_present"),
        "selected_model": status_payload.get("model"),
        "missing_env": status_payload.get("missing_env", []),
        "fallback_active": status_payload.get("fallback_active"),
        "profiles": status_payload.get("profiles", {}),
        "checked_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


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


@app.post("/v1/auth/email-verification/request")
async def email_verification_request_runtime(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """Operational resend route with truthful provider status."""

    stage = "validate_email"
    email = str(payload.get("email") or "").strip().lower()
    if not email or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail="valid email required")

    from app.db.base import SessionLocal
    from app.models.saas import User
    from app.services.email_delivery import send_email
    from app.services.email_verification import _verification_email_html, create_verification_token, verification_base_url

    db = SessionLocal()
    try:
        stage = "schema_guard"
        ensure_saas_portal_runtime_schema()

        stage = "find_user"
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return {
                "message": "If an account exists, we processed the verification request.",
                "delivery": {"delivery": "unknown", "provider": "none", "reason": "account_not_found", "stage": stage},
            }
        if user.email_verification_status == "verified" and user.email_verified_at:
            return {
                "message": "This account is already verified.",
                "delivery": {"delivery": "not_needed", "provider": "none", "reason": "already_verified", "stage": stage},
            }

        stage = "create_token"
        token = create_verification_token(db, user)
        db.commit()

        stage = "send_email"
        verification_url = f"{verification_base_url()}/verify-email?token={token}"
        result = send_email(
            to_email=user.email,
            subject="Confirm your AGRO-AI email address",
            text_body=(
                "Confirm your email address to activate your AGRO-AI Enterprise Portal workspace.\n\n"
                f"Open this link: {verification_url}\n\n"
                "This link expires in 24 hours."
            ),
            html_body=_verification_email_html(verification_url=verification_url),
        )
        if result.get("ok"):
            return {
                "message": "We sent a verification link to your email.",
                "delivery": {"delivery": "sent", "provider": result.get("provider"), "status_code": result.get("status_code"), "reason": "accepted", "stage": stage},
            }
        return {
            "message": "Email verification is required, but the email provider did not accept the message.",
            "delivery": {
                "delivery": "failed",
                "provider": result.get("provider") or "none",
                "status_code": result.get("status_code"),
                "reason": result.get("reason") or "provider_failed",
                "stage": stage,
            },
        }
    except Exception as exc:
        db.rollback()
        logger.exception("Verification email operational route failed stage=%s", stage)
        return {
            "message": "Email verification is required, but the verification email could not be sent.",
            "delivery": {"delivery": "failed", "provider": "none", "reason": exc.__class__.__name__, "stage": stage},
        }
    finally:
        db.close()


from app.api.v1.auth import router as auth_router  # noqa: E402
from app.api.v1.billing import router as billing_router  # noqa: E402
from app.api.v1.product_shell import router as product_shell_router  # noqa: E402

app.include_router(auth_router, prefix="/v1")
app.include_router(billing_router, prefix="/v1")
app.include_router(product_shell_router, prefix="/v1")

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

from app.api.v1.brain import router as brain_router  # noqa: E402
app.include_router(brain_router, prefix="/v1")

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

from app.api.v1.brain import router as brain_router  # noqa: E402
app.include_router(brain_router, prefix="/v1")

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
