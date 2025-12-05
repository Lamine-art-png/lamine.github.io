from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agroai
from agroai.report import generate_sample_report

app = FastAPI(
    title="AGRO-AI Pilot API",
    version="1.1.0",
    openapi_url="/openapi.json",
)

# --- Static assets for demo reports (charts + fonts) ---

AGROAI_DIR = Path(agroai.__file__).resolve().parent
CHARTS_DIR = AGROAI_DIR / "charts"

app.mount(
    "/demo-assets",
    StaticFiles(directory=str(CHARTS_DIR)),
    name="demo-assets",
)


@app.get("/demo/sample-report", response_class=HTMLResponse)
def sample_report():
    html_path = generate_sample_report()
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # for demo; later we can tighten to your domains
    allow_methods=["*"],
    allow_headers=["*"],
)


class DemoRequest(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


class DemoResponse(BaseModel):
    field_id: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float
    recommended_inches_per_week: float
    savings_pct: float

@app.get("/demo/sample-report", response_class=HTMLResponse)
def sample_report() -> HTMLResponse:
    html_path = generate_sample_report()
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/v1/health")
async def health():
    return {
        "status": "ok",
        "database": "ok",
        "version": "1.1.0",
    }


@app.post("/v1/demo/recommendation", response_model=DemoResponse)
async def demo_recommendation(payload: DemoRequest):
    # Toy logic for demo: ~25% water savings
    rec = round(payload.baseline_inches_per_week * 0.75, 2)
    savings_pct = round(
        (payload.baseline_inches_per_week - rec)
        / payload.baseline_inches_per_week * 100,
        1,
    )

    return {
        **payload.dict(),
        "recommended_inches_per_week": rec,
        "savings_pct": savings_pct,
    }

@app.get("/demo/sample-report", response_class=HTMLResponse)
def sample_report():
    """
    Generate and return an HTML sample water report.
    """
    html_path = generate_sample_report()
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

