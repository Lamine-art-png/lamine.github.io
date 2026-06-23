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

from app.core.config import settings

logger = logging.getLogger(__name__)

VERSION = "2.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle — starts scheduler, initializes DB."""
    from app.db.base import init_db

    # Initialize database tables
    init_db()
    logger.info("Database initialized")

    # Start background scheduler if enabled (sync runs on schedule, NOT blocking startup)
    if settings.ENABLE_SCHEDULER and settings.WISECONN_API_KEY:
        from app.core.scheduler import start_scheduler

        start_scheduler()
        logger.info("Scheduler started — first sync will run on next interval")
    else:
        logger.info("Background scheduler disabled (ENABLE_SCHEDULER=%s, API key set=%s)",
                     settings.ENABLE_SCHEDULER, bool(settings.WISECONN_API_KEY))

    yield  # App is running

    # Shutdown
    if settings.ENABLE_SCHEDULER:
        from app.core.scheduler import stop_scheduler
        stop_scheduler()


app = FastAPI(
    title="AGRO-AI API",
    version=VERSION,
    lifespan=lifespan,
)

# WiseConn integration routes
from app.api.v1.wiseconn import router as wiseconn_router  # noqa: E402

app.include_router(wiseconn_router, prefix="/v1")

# Decisioning routes (water state + recommendations)
from app.api.v1.decisioning import router as decisioning_router  # noqa: E402

app.include_router(decisioning_router, prefix="/v1")

# Execution assurance routes (verification + outcome tracking)
from app.api.v1.execution_assurance import router as execution_router  # noqa: E402

app.include_router(execution_router, prefix="/v1")

# Forecast routes (VWC forecast, accuracy, optimization)
from app.api.v1.forecast import router as forecast_router  # noqa: E402

app.include_router(forecast_router, prefix="/v1")

from app.api.v1.intelligence import router as intelligence_router  # noqa: E402
app.include_router(intelligence_router, prefix="/v1")

from app.api.v1.workbench import router as workbench_router  # noqa: E402
app.include_router(workbench_router, prefix="/v1")

from app.api.v1.talgil import router as talgil_router  # noqa: E402
app.include_router(talgil_router, prefix="/v1")

from app.api.v1.compliance import router as compliance_router  # noqa: E402
app.include_router(compliance_router, prefix="/v1")

from app.api.v1.assurance import router as assurance_router  # noqa: E402
app.include_router(assurance_router, prefix="/v1")

from app.api.v1.agents import router as agents_router  # noqa: E402
app.include_router(agents_router, prefix="/v1")


# Prometheus metrics endpoint
from app.core.metrics import metrics_endpoint  # noqa: E402

app.get("/metrics")(metrics_endpoint)


# Request metrics middleware
import time  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from app.core.metrics import api_requests, api_latency  # noqa: E402


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = time.time() - start
        endpoint = request.url.path
        method = request.method
        api_requests.labels(method=method, endpoint=endpoint, status=response.status_code).inc()
        api_latency.labels(method=method, endpoint=endpoint).observe(elapsed)
        return response


app.add_middleware(MetricsMiddleware)

# CORS: allow your production site + local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://agroai-pilot.com",
        "https://www.agroai-pilot.com",
        "https://app.agroai-pilot.com",
        "https://agroai-portal.pages.dev",
        "https://agroai-command-center-v2-preview.pages.dev",
        "https://app-v2.agroai-pilot.com",
        "http://localhost:4173",
        "http://localhost:4174",
        "http://127.0.0.1:4174",
        "http://localhost:4180",
        "http://127.0.0.1:4180",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Health
# -------------------------
@app.get("/v1/health")
async def health() -> Dict[str, Any]:
    from app.core.scheduler import get_last_sync_result

    sync_status = get_last_sync_result()
    return {
        "status": "ok",
        "database": "ok",
        "version": VERSION,
        "scheduler_enabled": settings.ENABLE_SCHEDULER,
        "last_sync": sync_status,
    }


# -------------------------
# Existing evaluation recommendation route
# (Keeps your current behavior compatible)
# -------------------------
class EvaluationRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float = Field(..., gt=0)


class EvaluationResponse(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float
    recommended_inches_per_week: float
    savings_pct: float


@app.post("/v1/evaluation/recommendation", response_model=EvaluationResponse)
@app.post("/v1/demo/recommendation", response_model=EvaluationResponse, include_in_schema=False)
async def evaluation_recommendation(payload: EvaluationRequest) -> EvaluationResponse:
    # Toy logic: ~25% water savings
    rec = round(payload.baseline_inches_per_week * 0.75, 2)
    savings_pct = round(
        (payload.baseline_inches_per_week - rec) / payload.baseline_inches_per_week * 100,
        1,
    )

    return EvaluationResponse(
        **payload.dict(),
        recommended_inches_per_week=rec,
        savings_pct=savings_pct,
    )


# -------------------------
# Optional: simple HTML sample report page
# (Keeps your existing "/demo/sample-report" idea but self-contained)
# -------------------------
@app.get("/evaluation/sample-report", response_class=HTMLResponse)
@app.get("/demo/sample-report", response_class=HTMLResponse, include_in_schema=False)
def sample_report() -> HTMLResponse:
    html = f"""
    <html>
      <head><title>AGRO-AI Sample Report</title></head>
      <body style="font-family: system-ui; margin: 32px;">
        <h2>AGRO-AI — Sample Report</h2>
        <p>API version: <b>{VERSION}</b></p>
        <p>This is a placeholder HTML report for evaluation workflows.</p>
        <hr/>
        <p><b>Next:</b> use <code>POST /v1/evaluation/report</code> to generate a PDF from selected blocks.</p>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


# -------------------------
# NEW: Block list + Run + PDF report (Cristobal-proof)
# These are what lightweight website evaluation pages can call.
# -------------------------
class EvaluationBlock(BaseModel):
    id: str
    label: str
    crop: str
    acres: float
    location: str


# Hardcoded sample blocks (reliable, zero dependencies)
EVALUATION_BLOCKS: List[EvaluationBlock] = [
    EvaluationBlock(id="B1", label="Block 1", crop="Vineyard", acres=12.4, location="Napa, CA"),
    EvaluationBlock(id="B2", label="Block 2", crop="Vineyard", acres=18.1, location="Sonoma, CA"),
    EvaluationBlock(id="B3", label="Block 3", crop="Almonds", acres=25.0, location="Fresno, CA"),
]


class EvaluationRunRequest(BaseModel):
    block_ids: List[str] = Field(..., min_length=1)
    mode: str = "synthetic"
    assumptions: Dict[str, Any] = Field(default_factory=dict)


@app.get("/v1/evaluation/blocks", response_model=List[EvaluationBlock])
@app.get("/v1/demo/blocks", response_model=List[EvaluationBlock], include_in_schema=False)
def evaluation_blocks() -> List[EvaluationBlock]:
    return EVALUATION_BLOCKS


@app.post("/v1/evaluation/run")
@app.post("/v1/demo/run", include_in_schema=False)
def evaluation_run(payload: EvaluationRunRequest = Body(...)) -> Dict[str, Any]:
    blocks_by_id = {b.id: b for b in EVALUATION_BLOCKS}
    prescriptions: List[Dict[str, Any]] = []

    for bid in payload.block_ids:
        b = blocks_by_id.get(bid)
        if not b:
            raise HTTPException(status_code=404, detail=f"Unknown sample block: {bid}")

        # Toy baseline vs recommended (placeholder for your real engine)
        baseline = 1.0  # inches/week (toy)
        recommended = round(baseline * 0.75, 2)  # 25% savings toy logic
        savings_pct = round((baseline - recommended) / baseline * 100, 1)

        prescriptions.append(
            {
                "block_id": b.id,
                "label": b.label,
                "crop": b.crop,
                "acres": b.acres,
                "location": b.location,
                "baseline_inches_per_week": baseline,
                "recommended_inches_per_week": recommended,
                "savings_pct": savings_pct,
                "mode": "decision-support",
                "reason": "evaluation logic: reduce baseline by 25% (placeholder for model)",
                "confidence": 0.62,
            }
        )

    return {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "mode": payload.mode,
        "prescriptions": prescriptions,
        "report_endpoint": "/v1/evaluation/report",
    }


@app.post("/v1/evaluation/report")
@app.post("/v1/demo/report", include_in_schema=False)
def evaluation_report(payload: EvaluationRunRequest = Body(...)) -> Response:
    """
    Bulletproof: generates a PDF on-demand from the request.
    No run_id, no in-memory state, no 404 after restarts.
    """
    run = evaluation_run(payload)

    # PDF generation (requires reportlab in requirements)
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h - 50, "AGRO-AI — Weekly Proof Report")

    c.setFont("Helvetica", 11)
    c.drawString(50, h - 80, f"Generated: {run['generated_at']}")
    c.drawString(50, h - 100, f"Blocks: {', '.join(payload.block_ids)}")

    y = h - 140
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Prescriptions Summary")
    y -= 20

    c.setFont("Helvetica", 10)
    for item in run["prescriptions"][:12]:
        line = (
            f"- {item['label']} ({item['crop']}): "
            f"{item['recommended_inches_per_week']} in/wk  "
            f"(savings {item['savings_pct']}%)"
        )
        c.drawString(60, y, line)
        y -= 14
        if y < 90:
            c.showPage()
            y = h - 60
            c.setFont("Helvetica", 10)

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(50, 55, "Evaluation report — not a compliance document. For illustration only.")
    c.save()

    pdf_bytes = buf.getvalue()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=agroai_sample_report.pdf"},
    )
