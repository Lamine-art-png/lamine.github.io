"""Main FastAPI application for AGRO-AI."""

import time
import uuid
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging, set_request_id
from app.core import metrics
from app.db.base import init_db
from app.api.v1 import api_router

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logger = setup_logging()


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
  """Application lifespan events."""
  # Startup
  logger.info("Starting AGRO-AI API")
  init_db()
  logger.info("Database initialized")

  yield

  # Shutdown
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
  allow_origins=["*"],          # tighten for production
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Middleware: request ID
# ---------------------------------------------------------------------------

@app.middleware("http")
async def add_request_id(request: Request, call_next):
  """Attach a request ID to each request/response."""
  request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
  set_request_id(request_id)

  response = await call_next(request)
  response.headers["X-Request-ID"] = request_id
  return response


# ---------------------------------------------------------------------------
# Middleware: request logging
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
  """Log basic request/response information."""
  start_time = time.time()

  logger.info(
    "Request started",
    extra={
      "method": request.method,
      "path": request.url.path,
      "client": request.client.host if request.client else None,
    },
  )

  response = await call_next(request)

  duration_ms = round((time.time() - start_time) * 1000, 2)
  logger.info(
    "Request completed",
    extra={
      "method": request.method,
      "path": request.url.path,
      "status_code": response.status_code,
      "duration_ms": duration_ms,
    },
  )

  return response


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
  """Catch-all exception handler."""
  logger.error("Unhandled exception", exc_info=True)

  return JSONResponse(
    status_code=500,
    content={
      "detail": "Internal server error",
      "type": "internal_error",
    },
  )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# ---------------------------------------------------------------------------
# Health / metrics / root
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz():
  """Container / load balancer health check endpoint."""
  return {"status": "ok"}


@app.get("/metrics")
def get_metrics():
  """Prometheus metrics endpoint."""
  if not settings.ENABLE_METRICS:
    return Response(status_code=404)
  return metrics.metrics_endpoint()


@app.get("/")
def root():
  """Root endpoint."""
  return {
    "name": settings.APP_NAME,
    "version": settings.VERSION,
    "docs": "/docs",
    "openapi": "/openapi.json",
    "health": "/healthz",
    "api_v1": settings.API_V1_PREFIX,
  }
