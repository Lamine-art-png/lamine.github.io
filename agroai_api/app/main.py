import uuid
import time
import csv
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from pydantic import BaseModel
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging, set_request_id
from app.core import metrics
from app.db.base import init_db
from app.api.v1 import api_router


logger = setup_logging()

# -------------------------------------------------------------------
# Lifespan: startup / shutdown
# -------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AGRO-AI API")
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down AGRO-AI API")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# -------------------------------------------------------------------
# Core API router (includes /v1/health, etc.)
# -------------------------------------------------------------------
app.include_router(api_router, prefix="/v1")

# -------------------------------------------------------------------
# Demo CSV-backed recommendation endpoint
# -------------------------------------------------------------------
DATA_CSV = Path(__file__).resolve().parent.parent / "data" / "demo_blocks.csv"


class DemoRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


class DemoBlockResponse(BaseModel):
    field_id: str
    crop: str
    acres: float
    baseline_inches_per_week: float
    agroai_inches_per_week: float
    water_savings_percent: float


class DemoResponse(BaseModel):
    status: str
    blocks: List[DemoBlockResponse]


@app.post("/v1/demo/recommendation", response_model=DemoResponse)
async def demo_recommendation(payload: DemoRequest) -> DemoResponse:
    """
    Tiny demo endpoint:

    - Reads data/demo_blocks.csv (if present)
    - Looks for a row matching field_id
    - Computes water savings from baseline vs. agroai column
    - If no CSV row found, synthesizes a fake 30% savings from payload
    """
    rows: List[DemoBlockResponse] = []

    # Load CSV if present
    if DATA_CSV.exists():
        with DATA_CSV.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("field_id") != payload.field_id:
                    continue

                baseline = float(row["baseline_inches_per_week"])
                agroai = float(row["agroai_inches_per_week"])
                savings_pct = round((baseline - agroai) / baseline * 100.0, 1)

                rows.append(
                    DemoBlockResponse(
                        field_id=row["field_id"],
                        crop=row["crop"],
                        acres=float(row["acres"]),
                        baseline_inches_per_week=baseline,
                        agroai_inches_per_week=agroai,
                        water_savings_percent=savings_pct,
                    )
                )

    # Fallback: synthesize from payload (pretend 30% savings)
    if not rows:
        baseline = payload.baseline_inches_per_week
        agroai = round(baseline * 0.7, 2)
        savings_pct = round((baseline - agroai) / baseline * 100.0, 1)

        rows.append(
            DemoBlockResponse(
                field_id=payload.field_id,
                crop=payload.crop,
                acres=payload.acres,
                baseline_inches_per_week=baseline,
                agroai_inches_per_week=agroai,
                water_savings_percent=savings_pct,
            )
        )

    return DemoResponse(status="ok", blocks=rows)


# -------------------------------------------------------------------
# CORS
# -------------------------------------------------------------------
# Safely read BACKEND_CORS_ORIGINS if it exists, otherwise default to "*"
allow_origins = getattr(settings, "BACKEND_CORS_ORIGINS", ["*"])

# If it comes from env as a comma-separated string, normalize to list
if isinstance(allow_origins, str):
    allow_origins = [o.strip() for o in allow_origins.split(",") if o.strip()]

if not allow_origins:
    allow_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------
# Request ID + timing + metrics middleware
# -------------------------------------------------------------------
@app.middleware("http")
async def add_request_id_and_timing(request: Request, call_next):
    request_id = str(uuid.uuid4())
    set_request_id(request_id)
    start = time.monotonic()

    try:
        response: Response = await call_next(request)
    except Exception:
        logger.error("Request failed", exc_info=True)
        raise
    finally:
        duration_ms = (time.monotonic() - start) * 1000.0

        logger.info(
            "request",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": getattr(response, "status_code", None),
                "request_id": request_id,
                "duration_ms": round(duration_ms, 2),
            },
        )

        # Best-effort metrics; never break the request on metrics failure
        try:
            status = getattr(response, "status_code", "NA")
            metrics.REQUEST_LATENCY.labels(
                method=request.method,
                path=request.url.path,
                status_code=status,
            ).observe(duration_ms / 1000.0)

            metrics.REQUEST_COUNT.labels(
                method=request.method,
                path=request.url.path,
                status_code=status,
            ).inc()
        except Exception:
            pass

    return response
