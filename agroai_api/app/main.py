kimport uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging, set_request_id
from app.core import metrics
from app.db.base import init_db
from app.api.v1 import api_router

logger = setup_logging()


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AGRO-AI API")
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down AGRO-AI API")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request ID + timing middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_request_id_header(request: Request, call_next):
    request_id = str(uuid.uuid4())
    start_time = time.time()
    set_request_id(request_id)

    response: Response = await call_next(request)

    duration_ms = (time.time() - start_time) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-ms"] = f"{duration_ms:.2f}"
    return response


# ---------------------------------------------------------------------------
# Logging middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(
        "Request start",
        extra={"path": request.url.path, "method": request.method},
    )
    response: Response = await call_next(request)
    logger.info(
        "Request end",
        extra={
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
        },
    )
    return response


# ---------------------------------------------------------------------------
# Global error handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": "internal_error"},
    )


# ---------------------------------------------------------------------------
# Mount v1 API router (health + demo + debug)
# settings.API_V1_PREFIX is what makes paths start with /v1
# ---------------------------------------------------------------------------
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# ---------------------------------------------------------------------------
# Metrics endpoint
# ---------------------------------------------------------------------------
@app.get("/metrics")
def get_metrics():
    if not getattr(settings, "ENABLE_METRICS", False):
        return Response(status_code=404)
    return metrics.metrics_endpoint()


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": f"{settings.API_V1_PREFIX}/health",
        "demo_recommendation": f"{settings.API_V1_PREFIX}/demo/recommendation",
        "debug_routes": f"{settings.API_V1_PREFIX}/debug/routes",
    }

