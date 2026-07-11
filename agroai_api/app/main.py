# agroai_api/app/main.py

from __future__ import annotations

import datetime
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.rate_limiting import limiter

logger = logging.getLogger(__name__)

VERSION = "2.0.1"


_SAAS_REQUIRED_SCHEMA: dict[str, set[str]] = {
    "users": {"id", "email", "email_verified_at", "email_verification_status", "credentials_changed_at", "account_status", "failed_login_attempts", "locked_until"},
    "organizations": {"id", "verification_status", "verification_score", "verification_engine_version"},
    "organization_verification_profiles": {"id", "organization_id", "decision", "score", "phone_ciphertext_b64", "evidence_digest"},
    "security_audit_events": {"id", "event_type", "outcome", "subject_hash", "ip_hash", "created_at"},
    "email_verification_tokens": {"id", "user_id", "token_hash", "expires_at", "used_at", "created_at"},
    "team_invitations": {"id", "organization_id", "email", "role", "status", "invited_by_user_id", "token_hash", "expires_at", "created_at", "updated_at"},
    "user_preferences": {"user_id", "locale", "timezone", "notifications_json", "ui_json", "created_at", "updated_at"},
    "saas_requests": {"id", "organization_id", "workspace_id", "user_id", "type", "status", "priority", "subject", "message", "notification_status", "metadata_json", "created_at", "updated_at"},
}


def saas_portal_schema_status() -> dict[str, Any]:
    """Read-only schema contract check.

    Schema ownership belongs to Alembic. This verifier deliberately does not
    create tables, alter columns, or repair request-time drift.
    """
    status: dict[str, Any] = {"ready": True, "missing": {}}
    try:
        from app.db.base import engine

        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            for table, required_columns in _SAAS_REQUIRED_SCHEMA.items():
                if table not in tables:
                    status["missing"][table] = sorted(required_columns)
                    continue
                columns = {item["name"] for item in inspector.get_columns(table)}
                missing_columns = required_columns - columns
                if missing_columns:
                    status["missing"][table] = sorted(missing_columns)
    except Exception:
        logger.exception("SaaS Portal schema verification failed")
        status["ready"] = False
        status["error"] = "schema_verification_failed"
        return status
    status["ready"] = not bool(status["missing"])
    return status


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start optional background services without making them API boot blockers."""
    schema_status = saas_portal_schema_status()
    if not schema_status["ready"]:
        logger.warning("SaaS Portal schema is not ready; run Alembic migrations before serving production traffic: %s", schema_status)
    scheduler_started = False

    if settings.ENABLE_SCHEDULER and settings.WISECONN_API_KEY:
        try:
            from app.core.scheduler import start_scheduler

            start_scheduler()
            scheduler_started = True
            logger.info("Scheduler started — first sync will run on next interval")
        except Exception:
            logger.exception("Background scheduler failed to start; API will continue without scheduled sync")
    else:
        logger.info(
            "Background scheduler disabled (ENABLE_SCHEDULER=%s, API key set=%s)",
            settings.ENABLE_SCHEDULER,
            bool(settings.WISECONN_API_KEY),
        )

    yield

    if scheduler_started:
        try:
            from app.core.scheduler import stop_scheduler

            stop_scheduler()
        except Exception:
            logger.exception("Background scheduler failed to stop cleanly")


app = FastAPI(title="AGRO-AI API", version=VERSION, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
_ALLOWED_ORIGIN_PATTERN = re.compile(ALLOWED_ORIGIN_REGEX)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-API-Key", "Idempotency-Key"],
    expose_headers=["x-agroai-runtime", "x-agroai-error"],
)


def _origin_allowed(origin: str) -> bool:
    return origin in ALLOWED_ORIGINS or _ALLOWED_ORIGIN_PATTERN.fullmatch(origin) is not None


def _add_runtime_cors_headers(response: JSONResponse, origin: str | None) -> JSONResponse:
    if origin and _origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, X-API-Key, Idempotency-Key"
        response.headers["Vary"] = "Origin"
    response.headers["x-agroai-runtime"] = VERSION
    return response


@app.middleware("http")
async def security_response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
    if str(getattr(settings, "APP_ENV", "development") or "development").lower() in {"production", "prod"}:
        response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
    if request.url.path.startswith("/v1/auth/") or request.url.path.startswith("/v1/account/"):
        response.headers.setdefault("Cache-Control", "no-store, max-age=0")
        response.headers.setdefault("Pragma", "no-cache")
    return response


@app.middleware("http")
async def durable_upload_compatibility_boundary(request: Request, call_next):
    """Route legacy uploads through distributed ingestion only when requested.

    With both distributed dependencies disabled, local/dev retains the legacy
    request-scoped synchronous behavior. If either dependency is selected, the
    hardened handler owns the request and rejects split-brain configuration.
    """
    object_backend = str(getattr(settings, "CONNECTOR_OBJECT_STORAGE_BACKEND", "disabled") or "disabled").strip().lower()
    queue_backend = str(getattr(settings, "TASK_QUEUE_BACKEND", "disabled") or "disabled").strip().lower()
    distributed_requested = (
        object_backend in {"s3", "r2", "s3_compatible"}
        or queue_backend in {"redis", "redis_streams", "redis-streams", "cloudflare", "cloudflare_queues", "cloudflare-queues"}
    )
    if (
        distributed_requested
        and request.method == "POST"
        and request.scope.get("path") == "/v1/evidence/upload"
    ):
        request.scope["path"] = "/v1/evidence/upload-stream"
        request.scope["raw_path"] = b"/v1/evidence/upload-stream"
    return await call_next(request)


@app.middleware("http")
async def runtime_error_boundary(request: Request, call_next):
    origin = request.headers.get("origin")
    try:
        response = await call_next(request)
    except Exception as exc:  # pragma: no cover
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
    return {"status": "ok", "service": "agroai-api", "version": VERSION, "checked_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"}


@app.get("/v1/readiness")
async def readiness_v1() -> Dict[str, Any]:
    from app.services.production_readiness import evaluate_production_readiness

    report = evaluate_production_readiness(settings)
    schema_status = saas_portal_schema_status()
    return {
        "status": "ready" if report.ready and schema_status["ready"] else "not_ready",
        "service": "agroai-api",
        "version": VERSION,
        "schema": schema_status,
        "production": report.to_dict(),
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
        "checked_at": datetime.datetime.utcnow().isoformat() + "Z",
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


from app.api.v1.auth import router as auth_router  # noqa: E402
from app.api.v1.billing import router as billing_router  # noqa: E402
from app.api.v1.evaluation import legacy_router as evaluation_legacy_router  # noqa: E402
from app.api.v1.evaluation import router as evaluation_router  # noqa: E402
from app.api.v1.preferences import router as preferences_router  # noqa: E402
from app.api.v1.product_shell import router as product_shell_router  # noqa: E402
from app.api.v1.platform_admin import router as platform_admin_router  # noqa: E402
from app.api.v1.platform_api import router as platform_api_router  # noqa: E402

app.include_router(auth_router, prefix="/v1")
app.include_router(billing_router, prefix="/v1")
app.include_router(evaluation_router)
app.include_router(evaluation_legacy_router)
app.include_router(preferences_router, prefix="/v1")
app.include_router(product_shell_router, prefix="/v1")
app.include_router(platform_admin_router, prefix="/v1")
app.include_router(platform_api_router, prefix="/v1")

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

from app.api.v1.chat_artifacts import router as chat_artifacts_router  # noqa: E402
app.include_router(chat_artifacts_router, prefix="/v1")

from app.api.v1.workbench import router as workbench_router  # noqa: E402
app.include_router(workbench_router, prefix="/v1")

from app.api.v1.compliance import router as compliance_router  # noqa: E402
app.include_router(compliance_router, prefix="/v1")

from app.api.v1.controllers import router as controllers_router  # noqa: E402
app.include_router(controllers_router, prefix="/v1")

from app.api.v1.talgil import router as talgil_router  # noqa: E402
app.include_router(talgil_router, prefix="/v1")

from app.api.v1.ai_stable import router as ai_stable_router  # noqa: E402
app.include_router(ai_stable_router, prefix="/v1")

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

from app.api.v1.connector_stream_api import router as connector_stream_router  # noqa: E402
app.include_router(connector_stream_router, prefix="/v1")

from app.api.v1.operator_cockpit import router as operator_cockpit_router  # noqa: E402
app.include_router(operator_cockpit_router, prefix="/v1")

from app.api.v1.field_operations import router as field_operations_router  # noqa: E402
app.include_router(field_operations_router, prefix="/v1")
