from __future__ import annotations

import io
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

# PDF (ReportLab)
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.widgets.markers import makeMarker

router = APIRouter()

GALLONS_PER_ACRE_FOOT = 325_851.0


# -------------------------
# Models
# -------------------------
class Assumptions(BaseModel):
    target_savings_pct: float = Field(default=25, ge=0, le=80)
    scenario_savings_pcts: List[float] = Field(default_factory=lambda: [25, 35])
    kwh_per_acre_foot: float = Field(default=280, ge=0)
    water_price_per_acre_foot: float = Field(default=250, ge=0)
    energy_price_per_kwh: float = Field(default=0.22, ge=0)
    notes: str = Field(default="")


class CustomBlock(BaseModel):
    label: str = "Custom block"
    crop: str = "Unknown"
    location: str = "Unknown"
    acres: float = Field(default=10, ge=0)
    baseline_in_per_week: float = Field(default=1.0, ge=0)


class DemoRequest(BaseModel):
    # Backward compatible: some callers used field_id
    field_id: Optional[str] = None

    block_ids: List[str] = Field(default_factory=list)
    mode: Literal["synthetic", "real"] = "synthetic"
    assumptions: Assumptions = Field(default_factory=Assumptions)
    custom_block: Optional[CustomBlock] = None


@dataclass
class Block:
    block_id: str
    label: str
    crop: str
    location: str
    acres: float
    baseline_in_per_week: float
    county: str = "Unknown"
    state: str = "CA"


@dataclass
class Prescription:
    block: Block
    recommended_in_per_week: float
    savings_pct: float
    gallons_saved_week: float
    acre_feet_saved_week: float
    water_value_saved_usd_week: float
    energy_kwh_saved_week: float
    energy_value_saved_usd_week: float
    total_value_saved_usd_week: float
    confidence: float
    rationale: str


# -------------------------
# Demo blocks (synthetic)
# -------------------------
def _infer_county(location: str) -> str:
    s = (location or "").lower()
    if "napa" in s:
        return "Napa"
    if "sonoma" in s:
        return "Sonoma"
    if "fresno" in s:
        return "Fresno"
    if "kern" in s:
        return "Kern"
    if "tulare" in s:
        return "Tulare"
    return "Unknown"


def get_demo_blocks() -> List[Block]:
    return [
        Block(
            block_id="B1",
            label="Block 1 — Vineyard — Napa, CA",
            crop="Vineyard",
            location="Napa, CA",
            acres=12.4,
            baseline_in_per_week=1.00,
            county="Napa",
            state="CA",
        ),
        Block(
            block_id="B2",
            label="Block 2 — Vineyard — Sonoma, CA",
            crop="Vineyard",
            location="Sonoma, CA",
            acres=18.2,
            baseline_in_per_week=1.10,
            county="Sonoma",
            state="CA",
        ),
        Block(
            block_id="B3",
            label="Block 3 — Almonds — Fresno, CA",
            crop="Almonds",
            location="Fresno, CA",
            acres=33.0,
            baseline_in_per_week=1.25,
            county="Fresno",
            state="CA",
        ),
    ]


def resolve_blocks(req: DemoRequest) -> List[Block]:
    demo = {b.block_id: b for b in get_demo_blocks()}
    blocks: List[Block] = []

    for bid in req.block_ids:
        if bid in demo:
            blocks.append(demo[bid])

    if req.custom_block is not None:
        cb = req.custom_block
        blocks.append(
            Block(
                block_id=req.field_id or "CUSTOM",
                label=cb.label or "Custom block",
                crop=cb.crop or "Unknown",
                location=cb.location or "Unknown",
                acres=float(cb.acres or 0),
                baseline_in_per_week=float(cb.baseline_in_per_week or 0),
                county=_infer_county(cb.location),
                state="CA",
            )
        )

    # if caller didn’t provide field_id, derive something stable
    if not req.field_id:
        req.field_id = blocks[0].block_id if blocks else "UNKNOWN"

    return blocks


# -------------------------
# Core calc
# -------------------------
def compute_prescriptions(blocks: List[Block], a: Assumptions) -> List[Prescription]:
    target = float(a.target_savings_pct or 0)
    out: List[Prescription] = []

    for b in blocks:
        baseline = max(0.0, b.baseline_in_per_week)
        recommended = baseline * (1.0 - target / 100.0)

        # inches -> acre-feet: (in/12) * acres
        baseline_af = (baseline / 12.0) * b.acres
        rec_af = (recommended / 12.0) * b.acres
        saved_af = max(0.0, baseline_af - rec_af)

        saved_gal = saved_af * GALLONS_PER_ACRE_FOOT

        water_value = saved_af * float(a.water_price_per_acre_foot or 0)
        kwh_saved = saved_af * float(a.kwh_per_acre_foot or 0)
        energy_value = kwh_saved * float(a.energy_price_per_kwh or 0)

        total_value = water_value + energy_value

        # Confidence is synthetic here (demo); in real mode this would be model-driven
        confidence = 0.82 if b.county != "Unknown" else 0.72

        rationale = (
            "Prescription reduces applied water while maintaining agronomic bounds. "
            "Savings are computed against declared baseline and priced using provided assumptions."
        )

        out.append(
            Prescription(
                block=b,
                recommended_in_per_week=recommended,
                savings_pct=target,
                gallons_saved_week=saved_gal,
                acre_feet_saved_week=saved_af,
                water_value_saved_usd_week=water_value,
                energy_kwh_saved_week=kwh_saved,
                energy_value_saved_usd_week=energy_value,
                total_value_saved_usd_week=total_value,
                confidence=confidence,
                rationale=rationale,
            )
        )

    return out


def compute_scenarios(blocks: List[Block], a: Assumptions) -> List[Dict[str, Any]]:
    pcts = [x for x in (a.scenario_savings_pcts or []) if isinstance(x, (int, float))]
    pcts = [float(x) for x in pcts if 0 < float(x) < 90]
    if not pcts:
        pcts = [float(a.target_savings_pct or 25)]

    scenarios: List[Dict[str, Any]] = []
    for pct in sorted(set(pcts)):
        tmp = Assumptions(
            target_savings_pct=pct,
            scenario_savings_pcts=pcts,
            kwh_per_acre_foot=a.kwh_per_acre_foot,
            water_price_per_acre_foot=a.water_price_per_acre_foot,
            energy_price_per_kwh=a.energy_price_per_kwh,
            notes=a.notes,
        )
        pres = compute_prescriptions(blocks, tmp)
        scenarios.append(
            {
                "savings_pct": pct,
                "total_gallons_saved_week": sum(x.gallons_saved_week for x in pres),
                "total_kwh_saved_week": sum(x.energy_kwh_saved_week for x in pres),
                "total_value_saved_usd_week": sum(x.total_value_saved_usd_week for x in pres),
            }
        )
    return scenarios


def fmt(n: float, d: int = 2) -> str:
    if n is None or (isinstance(n, float) and (math.isnan(n) or math.isinf(n))):
        return "-"
    return f"{n:,.{d}f}"


# -------------------------
# Charts (ReportLab graphics)
# -------------------------
def make_bar_chart(title: str, labels: List[str], values: List[float]) -> Drawing:
    w, h = 7.2 * inch, 3.2 * inch
    d = Drawing(w, h)

    d.add(String(0, h - 14, title, fontName="Helvetica-Bold", fontSize=12))

    chart = VerticalBarChart()
    chart.x = 24
    chart.y = 28
    chart.width = w - 48
    chart.height = h - 56
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 8
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 8
    chart.valueAxis.gridStrokeColor = colors.HexColor("#d6d8dc")
    chart.bars[0].fillColor = colors.HexColor("#2f343b")  # glacial grey

    d.add(chart)
    return d


def make_line_chart(title: str, labels: List[str], values: List[float]) -> Drawing:
    w, h = 7.2 * inch, 3.0 * inch
    d = Drawing(w, h)
    d.add(String(0, h - 14, title, fontName="Helvetica-Bold", fontSize=12))

    pts = list(enumerate(values))
    lp = LinePlot()
    lp.x = 32
    lp.y = 28
    lp.width = w - 56
    lp.height = h - 56
    lp.data = [pts]
    lp.lines[0].strokeColor = colors.HexColor("#2f343b")
    lp.lines[0].symbol = makeMarker("FilledCircle")
    lp.lines[0].symbol.size = 4
    lp.lines[0].symbol.fillColor = colors.HexColor("#2f343b")
    lp.xValueAxis.valueMin = 0
    lp.xValueAxis.valueMax = max(0, len(values) - 1)
    lp.xValueAxis.valueSteps = list(range(len(values)))
    lp.xValueAxis.labels = labels
    lp.xValueAxis.labels.fontSize = 8
    lp.yValueAxis.labels.fontSize = 8
    lp.yValueAxis.gridStrokeColor = colors.HexColor("#d6d8dc")

    d.add(lp)
    return d


# -------------------------
# PDF report
# -------------------------
def build_pdf(req: DemoRequest, blocks: List[Block], pres: List[Prescription]) -> bytes:
    ts = datetime.now(timezone.utc).isoformat()
    scenarios = compute_scenarios(blocks, req.assumptions)

    styles = getSampleStyleSheet()
    base = styles["BodyText"]
    base.fontName = "Helvetica"
    base.fontSize = 10
    base.leading = 14

    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=22)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=16)
    mono = ParagraphStyle("mono", parent=base, fontName="Courier", fontSize=8, leading=10)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="AGRO-AI Weekly Proof Report (DEMO)",
    )

    story: List[Any] = []

    # Page 1: Executive summary
    story.append(Paragraph("AGRO-AI — Weekly Proof Report (DEMO)", h1))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>Generated (UTC):</b> {ts}", base))
    story.append(Paragraph(f"<b>Field ID:</b> {req.field_id}", base))
    story.append(Paragraph(f"<b>Mode:</b> {req.mode}", base))
    story.append(Spacer(1, 10))

    total_gal = sum(x.gallons_saved_week for x in pres)
    total_kwh = sum(x.energy_kwh_saved_week for x in pres)
    total_usd = sum(x.total_value_saved_usd_week for x in pres)

    kpi = [
        ["KPI", "Value"],
        ["Blocks evaluated", str(len(blocks))],
        ["Target savings", f"{fmt(req.assumptions.target_savings_pct, 1)}%"],
        ["Water saved (gal / week)", fmt(total_gal, 0)],
        ["Energy saved (kWh / week)", fmt(total_kwh, 0)],
        ["Total value saved ($ / week)", f"${fmt(total_usd, 0)}"],
    ]
    t = Table(kpi, colWidths=[2.6 * inch, 3.8 * inch])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e7ea")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c7c9cf")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 14))

    story.append(Paragraph("Prescriptions Summary", h2))
    summary_rows = [["Block", "Crop / Location", "Acres", "Baseline (in/wk)", "Recommended (in/wk)", "Savings", "Gallons saved / wk", "Total $ / wk"]]
    for p in pres:
        b = p.block
        summary_rows.append(
            [
                b.block_id,
                f"{b.crop} — {b.location}",
                fmt(b.acres, 1),
                fmt(b.baseline_in_per_week, 2),
                fmt(p.recommended_in_per_week, 2),
                f"{fmt(p.savings_pct, 1)}%",
                fmt(p.gallons_saved_week, 0),
                f"${fmt(p.total_value_saved_usd_week, 0)}",
            ]
        )

    stbl = Table(summary_rows, colWidths=[0.7*inch, 1.9*inch, 0.7*inch, 1.1*inch, 1.2*inch, 0.7*inch, 1.1*inch, 0.9*inch])
    stbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c7c9cf")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
            ]
        )
    )
    story.append(stbl)
    story.append(PageBreak())

    # Page 2: Block detail + rationale
    story.append(Paragraph("Block Detail", h1))
    story.append(Spacer(1, 8))
    for p in pres:
        b = p.block
        story.append(Paragraph(f"{b.block_id} — {b.crop} — {b.location}", h2))
        detail = [
            ["Field", "Value"],
            ["Acres", fmt(b.acres, 1)],
            ["Baseline (in/week)", fmt(b.baseline_in_per_week, 2)],
            ["Recommended (in/week)", fmt(p.recommended_in_per_week, 2)],
            ["Savings (%)", f"{fmt(p.savings_pct, 1)}%"],
            ["Water saved (acre-ft/week)", fmt(p.acre_feet_saved_week, 3)],
            ["Water saved (gal/week)", fmt(p.gallons_saved_week, 0)],
            ["Energy saved (kWh/week)", fmt(p.energy_kwh_saved_week, 0)],
            ["Water value ($/week)", f"${fmt(p.water_value_saved_usd_week, 0)}"],
            ["Energy value ($/week)", f"${fmt(p.energy_value_saved_usd_week, 0)}"],
            ["Total value ($/week)", f"${fmt(p.total_value_saved_usd_week, 0)}"],
            ["Confidence", f"{fmt(p.confidence*100, 0)}%"],
        ]
        dt = Table(detail, colWidths=[2.2 * inch, 4.2 * inch])
        dt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c7c9cf")),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e7ea")),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, -1), 9),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")])]))
        story.append(dt)
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>Rationale:</b> {p.rationale}", base))
        story.append(Spacer(1, 10))
    story.append(PageBreak())

    # Page 3: Scenario comparison + charts
    story.append(Paragraph("Scenario Comparison", h1))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Comparison across requested savings scenarios.", base))
    story.append(Spacer(1, 10))

    scen_rows = [["Scenario", "Gallons saved / wk", "kWh saved / wk", "Total value / wk ($)"]]
    labels = []
    gallons_vals = []
    value_vals = []
    for s in scenarios:
        lbl = f"{int(round(s['savings_pct']))}%"
        labels.append(lbl)
        gallons_vals.append(float(s["total_gallons_saved_week"]))
        value_vals.append(float(s["total_value_saved_usd_week"]))
        scen_rows.append([lbl, fmt(s["total_gallons_saved_week"], 0), fmt(s["total_kwh_saved_week"], 0), f"${fmt(s['total_value_saved_usd_week'], 0)}"])

    scen_tbl = Table(scen_rows, colWidths=[1.0*inch, 2.0*inch, 1.8*inch, 1.8*inch])
    scen_tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c7c9cf")),
                                  ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                                  ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                  ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                  ("FONTSIZE", (0, 0), (-1, -1), 9),
                                  ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")])]))
    story.append(scen_tbl)
    story.append(Spacer(1, 14))

    story.append(make_bar_chart("Water Saved (gal / week) by Scenario", labels, gallons_vals))
    story.append(Spacer(1, 10))
    story.append(make_line_chart("Total Value Saved ($ / week) by Scenario", labels, value_vals))
    story.append(PageBreak())

    # Page 4: Compliance-ready audit trail
    story.append(Paragraph("Compliance & Audit Trail (SGMA-style)", h1))
    story.append(Spacer(1, 8))

    audit = [
        ["Field", "Value"],
        ["Report type", "Weekly proof report (demo)"],
        ["Generated (UTC)", ts],
        ["Field ID", req.field_id],
        ["Blocks", ", ".join([b.block_id for b in blocks])],
        ["Locations", "; ".join(sorted(set([b.location for b in blocks])))],
        ["Counties", "; ".join(sorted(set([b.county for b in blocks])))],
        ["Assumptions (target savings)", f"{fmt(req.assumptions.target_savings_pct, 1)}%"],
        ["Assumptions (scenario list)", ", ".join([str(int(round(x))) for x in (req.assumptions.scenario_savings_pcts or [])])],
        ["Assumptions (water $/AF)", f"${fmt(req.assumptions.water_price_per_acre_foot, 0)}"],
        ["Assumptions (kWh/AF)", fmt(req.assumptions.kwh_per_acre_foot, 0)],
        ["Assumptions (energy $/kWh)", f"${fmt(req.assumptions.energy_price_per_kwh, 2)}"],
        ["Notes", req.assumptions.notes or "-"],
        ["Data sources (demo)", "Declared baseline + synthetic weather/ET placeholders + pricing assumptions"],
        ["Model version (demo)", os.getenv("GIT_SHA", "dev")],
    ]
    at = Table(audit, colWidths=[2.2 * inch, 4.2 * inch])
    at.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c7c9cf")),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e7ea")),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")])]))
    story.append(at)
    story.append(PageBreak())

    # Page 5: Water risk score (synthetic) + ops impact
    story.append(Paragraph("Water Risk & Operational Impact (Demo)", h1))
    story.append(Spacer(1, 8))

    risk_rows = [["County", "Risk score (0-100)", "Band", "Driver"]]
    for county in sorted(set(b.county for b in blocks)):
        base_in = sum(b.baseline_in_per_week for b in blocks if b.county == county) / max(1, sum(1 for b in blocks if b.county == county))
        hot_bonus = 15 if county in {"Fresno", "Kern", "Tulare"} else 5
        score = min(100, max(0, int(round(base_in * 40 + hot_bonus))))
        band = "LOW" if score < 35 else ("MODERATE" if score < 70 else "HIGH")
        risk_rows.append([county, str(score), band, "Baseline demand + zone stress proxy"])

    rt = Table(risk_rows, colWidths=[1.4 * inch, 1.4 * inch, 0.9 * inch, 2.7 * inch])
    rt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c7c9cf")),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")])]))
    story.append(rt)
    story.append(Spacer(1, 14))

    story.append(Paragraph("Operational notes (demo):", h2))
    story.append(Paragraph("• Compute layer is designed to emit prescriptions + audit fields suitable for integration into farm ops and compliance workflows.", base))
    story.append(Paragraph("• Energy + cost impacts are priced from declared assumptions; in production these attach to utility rates and pump curves.", base))
    story.append(Paragraph("• Risk scoring here is a placeholder; production scoring binds to basin/county indicators and allocation constraints.", base))
    story.append(PageBreak())

    # Page 6: Appendix (raw JSON)
    story.append(Paragraph("Appendix — Raw Payload & Outputs", h1))
    story.append(Spacer(1, 8))

    payload = req.model_dump()
    payload["resolved_blocks"] = [asdict(b) for b in blocks]
    payload["prescriptions"] = [
        {
            "block": asdict(p.block),
            "recommended_in_per_week": p.recommended_in_per_week,
            "savings_pct": p.savings_pct,
            "gallons_saved_week": p.gallons_saved_week,
            "acre_feet_saved_week": p.acre_feet_saved_week,
            "water_value_saved_usd_week": p.water_value_saved_usd_week,
            "energy_kwh_saved_week": p.energy_kwh_saved_week,
            "energy_value_saved_usd_week": p.energy_value_saved_usd_week,
            "total_value_saved_usd_week": p.total_value_saved_usd_week,
            "confidence": p.confidence,
            "rationale": p.rationale,
        }
        for p in pres
    ]
    payload["scenarios"] = scenarios

    story.append(Paragraph("Request + computed outputs (JSON):", base))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<pre>{json.dumps(payload, indent=2)[:14000]}</pre>", mono))

    doc.build(story)
    return buf.getvalue()


# -------------------------
# Routes
# -------------------------
@router.get("/blocks")
def blocks():
    return [
        {
            "block_id": b.block_id,
            "label": b.label,
            "crop": b.crop,
            "location": b.location,
            "acres": b.acres,
            "baseline_in_per_week": b.baseline_in_per_week,
        }
        for b in get_demo_blocks()
    ]


@router.post("/run")
def run(req: DemoRequest):
    blocks = resolve_blocks(req)
    pres = compute_prescriptions(blocks, req.assumptions)
    return {
        "field_id": req.field_id,
        "generated": datetime.now(timezone.utc).isoformat(),
        "assumptions": req.assumptions.model_dump(),
        "prescriptions": [
            {
                "block": asdict(p.block),
                "acres": p.block.acres,
                "baseline_in_per_week": p.block.baseline_in_per_week,
                "recommended_in_per_week": p.recommended_in_per_week,
                "savings_pct": p.savings_pct,
                "gallons_saved_week": p.gallons_saved_week,
                "total_value_saved_usd_week": p.total_value_saved_usd_week,
                "confidence": p.confidence,
                "rationale": p.rationale,
            }
            for p in pres
        ],
    }


@router.post("/recommendation")
def recommendation(req: DemoRequest):
    # Backward compat
    return run(req)


@router.post("/report")
def report(req: DemoRequest):
    blocks = resolve_blocks(req)
    pres = compute_prescriptions(blocks, req.assumptions)
    pdf = build_pdf(req, blocks, pres)

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline; filename=agro_ai_weekly_proof_report_demo.pdf",
            "Cache-Control": "no-store",
        },
    )

