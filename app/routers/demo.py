# app/routers/demo.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from io import BytesIO
import json

# PDF generation (ReportLab)
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )
except Exception as e:
    # We’ll raise a clean error at runtime if reportlab isn't installed
    letter = None
    colors = None
    inch = None
    getSampleStyleSheet = None
    ParagraphStyle = None
    SimpleDocTemplate = None
    Paragraph = None
    Spacer = None
    Table = None
    TableStyle = None
    _REPORTLAB_IMPORT_ERROR = e
else:
    _REPORTLAB_IMPORT_ERROR = None


router = APIRouter()

# 1 acre-inch of water ≈ 27,154 gallons
GALLONS_PER_ACRE_INCH = 27154


# -------------------------
# Request/Response models
# -------------------------

class DemoBlock(BaseModel):
    block_id: str
    label: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float


class RunRequest(BaseModel):
    block_ids: List[str] = Field(..., min_length=1)
    mode: str = "synthetic"
    assumptions: Dict[str, Any] = Field(default_factory=dict)


class Prescription(BaseModel):
    block_id: str
    label: str
    crop: str
    acres: float
    location: str
    baseline_inches_per_week: float
    recommended_inches_per_week: float
    savings_pct: float
    gallons_saved_per_week: float
    confidence: float
    reason: str


class RunResponse(BaseModel):
    generated_at: str
    mode: str
    assumptions: Dict[str, Any]
    prescriptions: List[Prescription]
    totals: Dict[str, Any]
    report_endpoint: str


# -------------------------
# Demo data + logic
# -------------------------

def get_demo_blocks() -> List[DemoBlock]:
    # Keep these aligned with what you show in the UI
    return [
        DemoBlock(
            block_id="B1",
            label="Block 1 — Vineyard — Napa, CA",
            crop="Vineyard",
            acres=12.4,
            location="Napa, CA",
            baseline_inches_per_week=1.0,
        ),
        DemoBlock(
            block_id="B2",
            label="Block 2 — Vineyard — Sonoma, CA",
            crop="Vineyard",
            acres=18.2,
            location="Sonoma, CA",
            baseline_inches_per_week=0.9,
        ),
        DemoBlock(
            block_id="B3",
            label="Block 3 — Almonds — Fresno, CA",
            crop="Almonds",
            acres=25.0,
            location="Fresno, CA",
            baseline_inches_per_week=1.2,
        ),
    ]


def _pick_blocks(block_ids: List[str]) -> List[DemoBlock]:
    blocks = get_demo_blocks()
    by_id = {b.block_id: b for b in blocks}
    picked: List[DemoBlock] = []
    for bid in block_ids:
        if bid in by_id:
            picked.append(by_id[bid])
    if not picked:
        raise HTTPException(status_code=400, detail="No valid block_ids selected")
    return picked


def _num(x: Any, default: float) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def compute_prescriptions(blocks: List[DemoBlock], mode: str, assumptions: Dict[str, Any]) -> List[Prescription]:
    """
    Contract: takes {block_ids, mode, assumptions} and returns prescriptions.
    This is synthetic logic, but *not* empty. It also supports simple overrides via assumptions.
    """

    # Optional knobs (safe defaults)
    target_savings_pct = _num(assumptions.get("target_savings_pct"), 25.0)  # e.g. 20–35
    target_savings_pct = max(0.0, min(60.0, target_savings_pct))

    # Optional baseline override
    baseline_multiplier = _num(assumptions.get("baseline_multiplier"), 1.0)
    baseline_multiplier = max(0.2, min(3.0, baseline_multiplier))

    # Optional confidence override
    base_confidence = _num(assumptions.get("confidence"), 0.62)
    base_confidence = max(0.05, min(0.99, base_confidence))

    # Optional per-block overrides:
    # assumptions = { "overrides": { "B1": {"baseline_inches_per_week": 1.1, "target_savings_pct": 30}, ... } }
    overrides: Dict[str, Any] = assumptions.get("overrides") or {}

    out: List[Prescription] = []

    for b in blocks:
        ov = overrides.get(b.block_id) or {}

        baseline_in = _num(ov.get("baseline_inches_per_week"), b.baseline_inches_per_week)
        baseline_in *= baseline_multiplier

        savings_pct = _num(ov.get("target_savings_pct"), target_savings_pct)
        savings_pct = max(0.0, min(60.0, savings_pct))

        recommended_in = baseline_in * (1.0 - savings_pct / 100.0)
        recommended_in = max(0.0, recommended_in)

        inches_saved = max(0.0, baseline_in - recommended_in)
        gallons_saved = inches_saved * b.acres * GALLONS_PER_ACRE_INCH

        reason = (
            f"Demo ({mode}): baseline adjusted by {savings_pct:.0f}% to illustrate weekly savings. "
            "Replace with ET₀ + crop coefficients + soil water balance + controller telemetry."
        )

        conf = _num(ov.get("confidence"), base_confidence)

        out.append(
            Prescription(
                block_id=b.block_id,
                label=b.label,
                crop=b.crop,
                acres=b.acres,
                location=b.location,
                baseline_inches_per_week=round(baseline_in, 3),
                recommended_inches_per_week=round(recommended_in, 3),
                savings_pct=round(savings_pct, 1),
                gallons_saved_per_week=round(gallons_saved, 0),
                confidence=round(conf, 2),
                reason=reason,
            )
        )

    return out


def compute_totals(prescriptions: List[Prescription]) -> Dict[str, Any]:
    total_acres = sum(p.acres for p in prescriptions)
    total_gal = sum(p.gallons_saved_per_week for p in prescriptions)
    avg_savings = 0.0
    if prescriptions:
        avg_savings = sum(p.savings_pct for p in prescriptions) / len(prescriptions)

    return {
        "blocks": len(prescriptions),
        "total_acres": round(total_acres, 2),
        "total_gallons_saved_per_week": round(total_gal, 0),
        "avg_savings_pct": round(avg_savings, 1),
        "gallons_per_acre_inch": GALLONS_PER_ACRE_INCH,
    }


# -------------------------
# PDF generation
# -------------------------

def _pretty_json(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, sort_keys=True)
    except Exception:
        return str(obj)


def build_pdf_report(
    *,
    generated_at: str,
    mode: str,
    assumptions: Dict[str, Any],
    prescriptions: List[Prescription],
    totals: Dict[str, Any],
) -> bytes:
    if _REPORTLAB_IMPORT_ERROR is not None:
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation unavailable (reportlab not installed): {_REPORTLAB_IMPORT_ERROR}",
        )

    buf = BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="AGRO-AI Weekly Proof Report",
        author="AGRO-AI",
    )

    styles = getSampleStyleSheet()
    title = styles["Title"]
    normal = styles["BodyText"]

    small = ParagraphStyle(
        "small",
        parent=normal,
        fontSize=9,
        leading=11,
    )

    mono = ParagraphStyle(
        "mono",
        parent=normal,
        fontName="Courier",
        fontSize=8.5,
        leading=10,
    )

    story: List[Any] = []

    story.append(Paragraph("AGRO-AI — Weekly Proof Report (DEMO)", title))
    story.append(Spacer(1, 8))

    meta_lines = [
        f"<b>Generated (UTC):</b> {generated_at}",
        f"<b>Mode:</b> {mode}",
        f"<b>Blocks:</b> {', '.join([p.block_id for p in prescriptions])}",
    ]
    story.append(Paragraph("<br/>".join(meta_lines), small))
    story.append(Spacer(1, 12))

    # Totals / headline
    headline = (
        f"<b>Weekly impact (demo):</b> "
        f"{totals.get('total_gallons_saved_per_week', 0):,.0f} gallons saved / week "
        f"across {totals.get('total_acres', 0)} acres "
        f"(avg savings {totals.get('avg_savings_pct', 0)}%)."
    )
    story.append(Paragraph(headline, normal))
    story.append(Spacer(1, 10))

    # Table
    table_data: List[List[Any]] = [[
        "Block",
        "Crop",
        "Location",
        "Acres",
        "Baseline\n(in/wk)",
        "Recommended\n(in/wk)",
        "Savings",
        "Gallons saved\n/wk",
        "Confidence",
    ]]

    for p in prescriptions:
        table_data.append([
            p.block_id,
            p.crop,
            p.location,
            f"{p.acres:.1f}",
            f"{p.baseline_inches_per_week:.2f}",
            f"{p.recommended_inches_per_week:.2f}",
            f"{p.savings_pct:.1f}%",
            f"{p.gallons_saved_per_week:,.0f}",
            f"{p.confidence:.2f}",
        ])

    # Totals row
    table_data.append([
        "TOTAL",
        "",
        "",
        f"{totals.get('total_acres', 0):.2f}",
        "",
        "",
        f"{totals.get('avg_savings_pct', 0):.1f}%",
        f"{totals.get('total_gallons_saved_per_week', 0):,.0f}",
        "",
    ])

    tbl = Table(
        table_data,
        colWidths=[0.7*inch, 1.0*inch, 1.3*inch, 0.6*inch, 0.85*inch, 0.95*inch, 0.65*inch, 1.05*inch, 0.7*inch],
        hAlign="LEFT",
        repeatRows=1,
    )

    tbl_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#234224")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (3, 1), (8, -1), "RIGHT"),
        ("ALIGN", (0, 0), (2, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D6D6D6")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F6F8F6")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EEF3EE")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.HexColor("#234224")),
    ])
    tbl.setStyle(tbl_style)

    story.append(tbl)
    story.append(Spacer(1, 12))

    # Per-block notes (reason)
    story.append(Paragraph("<b>Notes by block</b>", normal))
    story.append(Spacer(1, 6))
    for p in prescriptions:
        story.append(Paragraph(f"<b>{p.block_id}</b>: {p.reason}", small))
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 10))

    # Assumptions block
    story.append(Paragraph("<b>Assumptions (input)</b>", normal))
    story.append(Spacer(1, 6))

    assumptions_text = _pretty_json(assumptions if assumptions is not None else {})
    # Keep it readable in PDF: replace newlines with <br/>
    assumptions_html = assumptions_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
    story.append(Paragraph(assumptions_html, mono))

    story.append(Spacer(1, 12))

    # Methodology footer
    story.append(Paragraph("<b>Methodology (demo)</b>", normal))
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "Gallons saved are computed as: (baseline − recommended) × acres × 27,154 gallons per acre-inch. "
            "This report is a demo artifact for illustrating irrigation intelligence + reporting. "
            "Production reporting should include ET₀ sources, crop coefficients, soil water balance, irrigation events, and audit trail.",
            small,
        )
    )

    doc.build(story)
    return buf.getvalue()


# -------------------------
# Routes (match live-demo contract)
# -------------------------

@router.get("/blocks")
def demo_blocks():
    # Returns a list the UI can render in a multi-select
    return [b.model_dump() for b in get_demo_blocks()]


@router.api_route("/recommendation", methods=["GET", "POST"])
def demo_recommendation():
    """
    Keep this simple and predictable for the frontend demo card.
    Your client code tries GET then POST if it sees 405; we support both.
    """
    # Example block-level schedule (toy)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "synthetic",
        "prescriptions": [
            {
                "block_id": "B1",
                "label": "Block 1",
                "crop": "Vineyard",
                "acres": 12.4,
                "location": "Napa, CA",
                "baseline_inches_per_week": 1.0,
                "recommended_inches_per_week": 0.75,
                "savings_pct": 25.0,
                "confidence": 0.62,
                "reason": "Synthetic demo response for UI wiring.",
            }
        ],
    }


@router.post("/run")
def demo_run(req: RunRequest) -> RunResponse:
    generated_at = datetime.now(timezone.utc).isoformat()
    blocks = _pick_blocks(req.block_ids)
    prescriptions = compute_prescriptions(blocks, req.mode, req.assumptions)
    totals = compute_totals(prescriptions)

    return RunResponse(
        generated_at=generated_at,
        mode=req.mode,
        assumptions=req.assumptions or {},
        prescriptions=prescriptions,
        totals=totals,
        report_endpoint="/v1/demo/report",
    )


@router.post("/report")
def demo_report(req: RunRequest):
    """
    Contract:
      POST /v1/demo/report
      Body: { block_ids: [...], mode: "synthetic", assumptions: {...} }
      Header Accept: application/pdf
      Returns: application/pdf
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    blocks = _pick_blocks(req.block_ids)
    prescriptions = compute_prescriptions(blocks, req.mode, req.assumptions)
    totals = compute_totals(prescriptions)

    pdf_bytes = build_pdf_report(
        generated_at=generated_at,
        mode=req.mode,
        assumptions=req.assumptions or {},
        prescriptions=prescriptions,
        totals=totals,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="agroai_weekly_proof_report_demo.pdf"',
            "Cache-Control": "no-store",
        },
    )

