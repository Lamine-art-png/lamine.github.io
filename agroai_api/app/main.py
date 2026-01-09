from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi import Body
from fastapi.responses import Response
from typing import List, Dict, Any, Optional
import io

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

# ✅ FIX: ensure directory exists so StaticFiles doesn't crash the app
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

app.mount(
    "/demo-assets",
    StaticFiles(directory=str(CHARTS_DIR)),
    name="demo-assets",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo; lock down later
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

@app.get("/v1/health")
async def health():
    return {
        "status": "ok",
        "database": "ok",
        "version": "1.1.0",
    }

@app.get("/demo/sample-report", response_class=HTMLResponse)
def sample_report():
    html_path = generate_sample_report()
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@app.post("/v1/demo/recommendation", response_model=DemoResponse)
async def demo_recommendation(payload: DemoRequest):
    # Toy logic for demo: ~25% water savings
    rec = round(payload.baseline_inches_per_week * 0.75, 2)
    savings_pct = round(
        (payload.baseline_inches_per_week - rec) / payload.baseline_inches_per_week * 100,
        1,
    )

    return {
        **payload.dict(),
        "recommended_inches_per_week": rec,
        "savings_pct": savings_pct,
    }

class DemoBlock(BaseModel):
    id: str
    label: str
    crop: str
    acres: float
    location: str

# Hardcoded demo blocks (simple, reliable)
DEMO_BLOCKS: List[DemoBlock] = [
    DemoBlock(id="B1", label="Block 1", crop="Vineyard", acres=12.4, location="Napa, CA"),
    DemoBlock(id="B2", label="Block 2", crop="Vineyard", acres=18.1, location="Sonoma, CA"),
    DemoBlock(id="B3", label="Block 3", crop="Almonds", acres=25.0, location="Fresno, CA"),
]

class DemoRunRequest(BaseModel):
    block_ids: List[str]
    mode: str = "synthetic"
    assumptions: Dict[str, Any] = {}

@app.get("/v1/demo/blocks", response_model=List[DemoBlock])
def demo_blocks():
    return DEMO_BLOCKS

@app.post("/v1/demo/run")
def demo_run(payload: DemoRunRequest = Body(...)):
    # Use your existing toy savings logic style (consistent with /v1/demo/recommendation)
    blocks_by_id = {b.id: b for b in DEMO_BLOCKS}
    prescriptions = []

    for bid in payload.block_ids:
        b = blocks_by_id.get(bid)
        if not b:
            raise HTTPException(status_code=404, detail=f"Unknown demo block: {bid}")

        # simple “baseline vs recommended” numbers for demo
        baseline = 1.0  # inches/week (toy)
        recommended = round(baseline * 0.75, 2)  # 25% savings toy logic
        savings_pct = round((baseline - recommended) / baseline * 100, 1)

        prescriptions.append({
            "block_id": b.id,
            "label": b.label,
            "crop": b.crop,
            "acres": b.acres,
            "location": b.location,
            "baseline_inches_per_week": baseline,
            "recommended_inches_per_week": recommended,
            "savings_pct": savings_pct,
            "mode": "decision-support",
            "reason": "demo logic: reduce baseline by 25% (placeholder for model)",
            "confidence": 0.62,
        })

    return {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "prescriptions": prescriptions,
        "report_endpoint": "/v1/demo/report"
    }

@app.post("/v1/demo/report")
def demo_report(payload: DemoRunRequest = Body(...)):
    # Generate prescriptions first (no state)
    run = demo_run(payload)

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h - 50, "AGRO-AI — Weekly Proof Report (DEMO)")

    c.setFont("Helvetica", 11)
    c.drawString(50, h - 80, f"Generated: {run['generated_at']}")
    c.drawString(50, h - 100, f"Blocks: {', '.join(payload.block_ids)}")

    y = h - 140
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Prescriptions Summary")
    y -= 20

    c.setFont("Helvetica", 10)
    for item in run["prescriptions"][:12]:
        line = f"- {item['label']} ({item['crop']}): {item['recommended_inches_per_week']} in/wk  (savings {item['savings_pct']}%)"
        c.drawString(60, y, line)
        y -= 14
        if y < 90:
            c.showPage()
            y = h - 60
            c.setFont("Helvetica", 10)

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(50, 55, "Demo report — not a compliance document. For illustration only.")
    c.save()

    pdf_bytes = buf.getvalue()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=agroai_demo_report.pdf"},
    )

