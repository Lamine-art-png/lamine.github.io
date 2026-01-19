# app/routers/demo.py
from __future__ import annotations

import io
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict

# PDF (ReportLab)
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    XPreformatted,
    PageBreak,
)
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import LineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.legends import Legend

router = APIRouter()

GALLONS_PER_ACRE_FOOT = 325_851.0
ACRE_INCH_GALLONS = 27_154.285  # 1 acre-inch in gallons (approx)
THEME_BRAND = colors.HexColor("#2f343b")  # glacial slate
THEME_DARK = colors.HexColor("#111827")
THEME_GRID = colors.HexColor("#c7c9cf")
THEME_LIGHT = colors.HexColor("#fafafa")


# -------------------------
# Models
# -------------------------
class Assumptions(BaseModel):
    # IMPORTANT: allow extra keys from the UI without 422s
    model_config = ConfigDict(extra="allow")

    # scenario switch (Normal / Heat / Restriction) — keep as str to avoid 422 if UI sends variants
    scenario: str = Field(default="normal")

    # proof/audit metadata (optional, but makes PDF look enterprise-grade)
    baseline_policy: str = Field(default="typical_grower_schedule")
    system_type: str = Field(default="drip/micro (demo)")
    data_sources: List[str] = Field(
        default_factory=lambda: [
            "Baseline schedule (declared)",
            "Weather/ET0 (demo: synthetic placeholder)",
            "Soil/constraints (demo: synthetic placeholder)",
        ]
    )
    constraints: List[str] = Field(default_factory=lambda: ["irrigation window", "allocation limits (scenario)"])

    # economics knobs
    target_savings_pct: float = Field(default=25, ge=0, le=80)
    scenario_savings_pcts: List[float] = Field(default_factory=lambda: [25, 35])
    kwh_per_acre_foot: float = Field(default=280, ge=0)
    water_price_per_acre_foot: float = Field(default=250, ge=0)
    energy_price_per_kwh: float = Field(default=0.22, ge=0)
    notes: str = Field(default="")


class CustomBlock(BaseModel):
    model_config = ConfigDict(extra="allow")

    label: str = "Custom block"
    crop: str = "Unknown"
    location: str = "Unknown"
    acres: float = Field(default=10, ge=0)
    baseline_in_per_week: float = Field(default=1.0, ge=0)


class DemoRequest(BaseModel):
    # IMPORTANT: allow extra keys from future UIs without 422s
    model_config = ConfigDict(extra="allow")

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
                block_id="CUSTOM",
                label=cb.label or "Custom block",
                crop=cb.crop or "Unknown",
                location=cb.location or "Unknown",
                acres=float(cb.acres or 0),
                baseline_in_per_week=float(cb.baseline_in_per_week or 0),
                county=_infer_county(cb.location),
                state="CA",
            )
        )

    # HARDEN: if nothing selected, default to B1 so demo never returns empty
    if not blocks and "B1" in demo:
        blocks = [demo["B1"]]

    # if caller didn’t provide field_id, derive something stable
    if not req.field_id:
        req.field_id = blocks[0].block_id if blocks else "UNKNOWN"

    return blocks


# -------------------------
# Core calc
# -------------------------
def _scenario_effective_target(a: Assumptions) -> float:
    """Scenario switch changes the effective savings target to create believable behavior.

    - normal: use target_savings_pct
    - heat: reduce savings (you need to irrigate more)
    - restriction: increase savings (you must cut more)
    """
    target = float(a.target_savings_pct or 0)
    s = (a.scenario or "normal").strip().lower()

    # normalize common variants
    if "heat" in s:
        factor = 0.55
    elif "restrict" in s:
        factor = 1.25
    else:
        factor = 1.0

    eff = target * factor
    eff = max(0.0, min(80.0, eff))
    return eff


def compute_prescriptions(blocks: List[Block], a: Assumptions) -> List[Prescription]:
    eff_target = _scenario_effective_target(a)
    out: List[Prescription] = []

    for b in blocks:
        baseline = max(0.0, b.baseline_in_per_week)
        recommended = max(0.0, baseline * (1.0 - eff_target / 100.0))

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
        confidence = 0.86 if b.county != "Unknown" else 0.74

        scenario_note = (a.scenario or "normal").strip().lower()
        rationale = (
            f"Scenario='{scenario_note}'. Recommendation reduces applied water relative to the declared baseline "
            f"using an effective savings target of {eff_target:.1f}%. "
            "Savings are computed against baseline and priced using the provided assumptions (water + pumping energy). "
            "In production, baselines and confidence are estimated from measured ET, soil moisture, controller logs, and yield/quality constraints."
        )

        out.append(
            Prescription(
                block=b,
                recommended_in_per_week=recommended,
                savings_pct=eff_target,
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
            scenario=a.scenario,
            baseline_policy=a.baseline_policy,
            system_type=a.system_type,
            data_sources=list(a.data_sources or []),
            constraints=list(a.constraints or []),
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
                "scenario": tmp.scenario,
                "total_gallons_saved_week": sum(x.gallons_saved_week for x in pres),
                "total_kwh_saved_week": sum(x.energy_kwh_saved_week for x in pres),
                "total_water_value_saved_usd_week": sum(x.water_value_saved_usd_week for x in pres),
                "total_energy_value_saved_usd_week": sum(x.energy_value_saved_usd_week for x in pres),
                "total_value_saved_usd_week": sum(x.total_value_saved_usd_week for x in pres),
            }
        )
    return scenarios


def fmt(n: float, d: int = 2) -> str:
    if n is None:
        return "-"
    if isinstance(n, float) and (math.isnan(n) or math.isinf(n)):
        return "-"
    return f"{n:,.{d}f}"


# -------------------------
# Charts (ReportLab graphics)
# -------------------------
def _legend(series_names: List[str], series_colors: List[colors.Color], x: float, y: float) -> Legend:
    lg = Legend()
    lg.x = x
    lg.y = y
    lg.alignment = "right"
    lg.fontName = "Helvetica"
    lg.fontSize = 8
    lg.dxTextSpace = 6
    lg.dy = 6
    lg.columnMaximum = 1
    lg.colorNamePairs = list(zip(series_colors, series_names))
    return lg


def make_grouped_bar_chart(
    title: str,
    labels: List[str],
    series: List[List[float]],
    series_names: List[str],
) -> Drawing:
    w, h = 7.0 * inch, 3.1 * inch
    d = Drawing(w, h)

    d.add(String(0, h - 14, title, fontName="Helvetica-Bold", fontSize=12, fillColor=THEME_DARK))

    chart = VerticalBarChart()
    chart.x = 28
    chart.y = 32
    chart.width = w - 56
    chart.height = h - 64
    chart.data = series
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 8
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 8
    chart.valueAxis.gridStrokeColor = colors.HexColor("#d6d8dc")

    palette = [THEME_BRAND, colors.HexColor("#6b7280"), colors.HexColor("#111827"), colors.HexColor("#9ca3af")]
    for i in range(len(series)):
        chart.bars[i].fillColor = palette[i % len(palette)]

    d.add(chart)

    if series_names:
        series_colors = [chart.bars[i].fillColor for i in range(len(series))]
        d.add(_legend(series_names, series_colors, w - 8, h - 22))

    return d


def make_line_chart(title: str, labels: List[str], values: List[float]) -> Drawing:
    w, h = 7.0 * inch, 3.0 * inch
    d = Drawing(w, h)

    d.add(String(0, h - 14, title, fontName="Helvetica-Bold", fontSize=12, fillColor=THEME_DARK))

    lc = LineChart()
    lc.x = 30
    lc.y = 34
    lc.width = w - 60
    lc.height = h - 70
    lc.data = [values]
    lc.categoryAxis.categoryNames = labels
    lc.categoryAxis.labels.fontName = "Helvetica"
    lc.categoryAxis.labels.fontSize = 8
    lc.valueAxis.labels.fontName = "Helvetica"
    lc.valueAxis.labels.fontSize = 8
    lc.valueAxis.gridStrokeColor = colors.HexColor("#d6d8dc")

    lc.lines[0].strokeColor = THEME_BRAND
    lc.lines[0].strokeWidth = 2

    d.add(lc)
    return d


def make_pie_chart(title: str, labels: List[str], values: List[float]) -> Drawing:
    w, h = 7.0 * inch, 3.2 * inch
    d = Drawing(w, h)

    d.add(String(0, h - 14, title, fontName="Helvetica-Bold", fontSize=12, fillColor=THEME_DARK))

    pie = Pie()
    pie.x = 70
    pie.y = 18
    pie.width = 220
    pie.height = 220
    pie.data = [max(0.0, float(v)) for v in values]
    pie.labels = labels
    pie.slices.strokeWidth = 0.5
    pie.slices.strokeColor = colors.white

    palette = [THEME_BRAND, colors.HexColor("#6b7280"), colors.HexColor("#9ca3af"), colors.HexColor("#111827")]
    for i in range(len(values)):
        pie.slices[i].fillColor = palette[i % len(palette)]
        pie.slices[i].labelRadius = 1.08
        pie.slices[i].fontName = "Helvetica"
        pie.slices[i].fontSize = 8

    d.add(pie)
    return d


# -------------------------
# PDF report
# -------------------------
def _try_logo() -> Optional[Image]:
    candidates = [
        os.path.join(os.getcwd(), "public", "agro-ai-logo.png"),
        os.path.join(os.getcwd(), "public", "agro-ai-logo.jpg"),
        os.path.join(os.getcwd(), "public", "agro-ai-logo.jpeg"),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                img = Image(p)
                img.drawHeight = 0.35 * inch
                img.drawWidth = 0.35 * inch
                return img
            except Exception:
                return None
    return None


def build_pdf(req: DemoRequest, blocks: List[Block], pres: List[Prescription]) -> bytes:
    ts = datetime.now(timezone.utc).isoformat()
    scenarios = compute_scenarios(blocks, req.assumptions)

    styles = getSampleStyleSheet()
    base = styles["BodyText"]
    base.fontName = "Helvetica"
    base.fontSize = 10
    base.leading = 14

    h1 = ParagraphStyle(
        "h1",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=THEME_DARK,
    )
    h2 = ParagraphStyle(
        "h2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=THEME_DARK,
    )
    small = ParagraphStyle(
        "small",
        parent=base,
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#374151"),
    )
    mono = ParagraphStyle("mono", parent=base, fontName="Courier", fontSize=8, leading=10)

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        sc = (req.assumptions.scenario or "normal")
        canvas.drawString(
            doc.leftMargin,
            0.55 * inch,
            f"AGRO-AI Weekly Proof Report (DEMO) • Field {req.field_id} • scenario={sc} • {ts}",
        )
        canvas.drawRightString(LETTER[0] - doc.rightMargin, 0.55 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.78 * inch,
        title="AGRO-AI Weekly Proof Report (DEMO)",
        author="AGRO-AI",
    )

    story: List[Any] = []

    total_gal = sum(x.gallons_saved_week for x in pres)
    total_kwh = sum(x.energy_kwh_saved_week for x in pres)
    total_usd = sum(x.total_value_saved_usd_week for x in pres)
    total_water_usd = sum(x.water_value_saved_usd_week for x in pres)
    total_energy_usd = sum(x.energy_value_saved_usd_week for x in pres)

    # PAGE 1
    logo = _try_logo()
    if logo:
        header_tbl = Table([[logo, Paragraph("AGRO-AI — Weekly Proof Report (DEMO)", h1)]], colWidths=[0.45 * inch, 6.2 * inch])
        header_tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story.append(header_tbl)
    else:
        story.append(Paragraph("AGRO-AI — Weekly Proof Report (DEMO)", h1))

    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Generated (UTC):</b> {ts}", base))
    story.append(Paragraph(f"<b>Field ID:</b> {req.field_id}", base))
    story.append(Paragraph(f"<b>Mode:</b> {req.mode}", base))
    story.append(Paragraph(f"<b>Scenario:</b> {(req.assumptions.scenario or 'normal')}", base))
    story.append(Spacer(1, 10))

    kpi = [
        ["KPI", "Value"],
        ["Blocks evaluated", str(len(blocks))],
        ["Target savings (effective)", f"{fmt(_scenario_effective_target(req.assumptions), 1)}%"],
        ["Water saved (gal / week)", fmt(total_gal, 0)],
        ["Energy saved (kWh / week)", fmt(total_kwh, 0)],
        ["Total value saved ($ / week)", f"${fmt(total_usd, 0)}"],
    ]
    t = Table(kpi, colWidths=[2.6 * inch, 3.8 * inch])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e7ea")),
                ("TEXTCOLOR", (0, 0), (-1, 0), THEME_DARK),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, THEME_GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, THEME_LIGHT]),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Executive takeaways</b>", h2))
    story.append(
        Paragraph(
            "This report quantifies weekly water, energy, and cost impact from irrigation prescriptions relative to a declared baseline. "
            "This is a demo path: synthetic logic + assumptions for pricing; production binds these to measured ET/soil/controller logs and site-specific economics.",
            base,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            f"Weekly savings: <b>{fmt(total_gal, 0)}</b> gallons/week and <b>${fmt(total_usd, 0)}</b>/week total value "
            f"(water: <b>${fmt(total_water_usd, 0)}</b>, energy: <b>${fmt(total_energy_usd, 0)}</b>).",
            base,
        )
    )

    story.append(PageBreak())

    # PAGE 2 — Portfolio overview + charts
    story.append(Paragraph("Portfolio Overview", h1))
    story.append(Spacer(1, 8))

    blocks_rows = [["Block", "Crop / Location", "Acres", "Baseline (in/wk)", "County"]]
    for b in blocks:
        blocks_rows.append([b.block_id, f"{b.crop} — {b.location}", fmt(b.acres, 1), fmt(b.baseline_in_per_week, 2), b.county])

    bt = Table(blocks_rows, colWidths=[0.75 * inch, 2.7 * inch, 0.8 * inch, 1.2 * inch, 1.1 * inch], repeatRows=1)
    bt.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), THEME_DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, THEME_GRID),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, THEME_LIGHT]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(bt)
    story.append(Spacer(1, 14))

    labels = [p.block.block_id for p in pres]
    baseline_vals = [p.block.baseline_in_per_week for p in pres]
    rec_vals = [p.recommended_in_per_week for p in pres]
    gallons_by_block = [p.gallons_saved_week for p in pres]

    story.append(
        make_grouped_bar_chart(
            "Baseline vs Recommended (inches / week)",
            labels=labels,
            series=[baseline_vals, rec_vals],
            series_names=["Baseline", "Recommended"],
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        make_grouped_bar_chart(
            "Water Saved by Block (gallons / week)",
            labels=labels,
            series=[gallons_by_block],
            series_names=["Gallons saved"],
        )
    )

    story.append(PageBreak())

    # PAGE 3 — Scenario comparison
    story.append(Paragraph("Scenario Comparison", h1))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "Comparison across requested savings scenarios (independent of the scenario switch). "
            "Use this to calibrate proof standards with stakeholders.",
            base,
        )
    )
    story.append(Spacer(1, 10))

    scen_rows = [["Scenario", "Gallons saved / wk", "kWh saved / wk", "Water $ / wk", "Energy $ / wk", "Total $ / wk"]]
    scen_labels: List[str] = []
    scen_gal: List[float] = []
    scen_usd: List[float] = []
    for s in scenarios:
        lbl = f"{int(round(float(s['savings_pct'])))}%"
        scen_labels.append(lbl)
        scen_gal.append(float(s["total_gallons_saved_week"]))
        scen_usd.append(float(s["total_value_saved_usd_week"]))
        scen_rows.append(
            [
                lbl,
                fmt(float(s["total_gallons_saved_week"]), 0),
                fmt(float(s["total_kwh_saved_week"]), 0),
                f"${fmt(float(s['total_water_value_saved_usd_week']), 0)}",
                f"${fmt(float(s['total_energy_value_saved_usd_week']), 0)}",
                f"${fmt(float(s['total_value_saved_usd_week']), 0)}",
            ]
        )

    scen_tbl = Table(scen_rows, colWidths=[0.8 * inch, 1.35 * inch, 1.1 * inch, 0.95 * inch, 0.95 * inch, 0.9 * inch], repeatRows=1)
    scen_tbl.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, THEME_GRID),
                ("BACKGROUND", (0, 0), (-1, 0), THEME_DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, THEME_LIGHT]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(scen_tbl)
    story.append(Spacer(1, 14))
    story.append(make_grouped_bar_chart("Water Saved (gal / week) by Scenario", labels=scen_labels, series=[scen_gal], series_names=["Gallons saved"]))
    story.append(Spacer(1, 10))
    story.append(make_line_chart("Total Value Saved ($ / week) by Scenario", labels=scen_labels, values=scen_usd))

    story.append(PageBreak())

    # PAGE 4 — Economics
    story.append(Paragraph("Economics Breakdown", h1))
    story.append(Spacer(1, 8))
    water_value_by_block = [p.water_value_saved_usd_week for p in pres]
    energy_value_by_block = [p.energy_value_saved_usd_week for p in pres]
    story.append(
        make_grouped_bar_chart(
            "Weekly Value Saved by Block (Water vs Energy)",
            labels=labels,
            series=[water_value_by_block, energy_value_by_block],
            series_names=["Water value ($/wk)", "Energy value ($/wk)"],
        )
    )
    story.append(Spacer(1, 12))
    total_value_by_block = [p.total_value_saved_usd_week for p in pres]
    story.append(make_pie_chart("Share of Total Weekly Value Saved (by Block)", labels=[p.block.block_id for p in pres], values=total_value_by_block))

    story.append(PageBreak())

    # PAGE 5 — Prescription detail
    story.append(Paragraph("Prescription Detail", h1))
    story.append(Spacer(1, 8))

    detail_rows = [[
        "Block", "Acres", "Baseline (in/wk)", "Rec (in/wk)", "AF saved/wk",
        "Gallons saved/wk", "kWh saved/wk", "Total $/wk", "Conf."
    ]]
    conf_vals = []
    for p in pres:
        b = p.block
        conf_vals.append(float(p.confidence) * 100.0)
        detail_rows.append([
            b.block_id,
            fmt(b.acres, 1),
            fmt(b.baseline_in_per_week, 2),
            fmt(p.recommended_in_per_week, 2),
            fmt(p.acre_feet_saved_week, 3),
            fmt(p.gallons_saved_week, 0),
            fmt(p.energy_kwh_saved_week, 0),
            f"${fmt(p.total_value_saved_usd_week, 0)}",
            f"{fmt(p.confidence * 100, 0)}%",
        ])

    dt = Table(
        detail_rows,
        colWidths=[0.6*inch, 0.6*inch, 0.95*inch, 0.75*inch, 0.75*inch, 1.05*inch, 0.85*inch, 0.75*inch, 0.5*inch],
        repeatRows=1,
    )
    dt.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), THEME_DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, THEME_GRID),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, THEME_LIGHT]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(dt)
    story.append(Spacer(1, 14))
    story.append(make_grouped_bar_chart("Model Confidence by Block (demo proxy, %)", labels=labels, series=[conf_vals], series_names=["Confidence (%)"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>Rationale (applies to this demo run)</b>", h2))
    story.append(Paragraph(pres[0].rationale if pres else "No prescriptions.", base))

    story.append(PageBreak())

    # PAGE 6 — Audit trail
    story.append(Paragraph("Compliance & Audit Trail (SGMA-style)", h1))
    story.append(Spacer(1, 8))

    model_version = os.getenv("GIT_SHA", os.getenv("RENDER_GIT_COMMIT", "dev"))
    audit = [
        ["Field", "Value"],
        ["Report type", "Weekly proof report (demo)"],
        ["Generated (UTC)", ts],
        ["Field ID", req.field_id],
        ["Scenario", (req.assumptions.scenario or "normal")],
        ["Blocks", ", ".join([b.block_id for b in blocks])],
        ["Locations", "; ".join(sorted(set([b.location for b in blocks])))],
        ["Counties", "; ".join(sorted(set([b.county for b in blocks])))],
        ["Baseline policy", req.assumptions.baseline_policy],
        ["System type", req.assumptions.system_type],
        ["Assumptions (target savings)", f"{fmt(req.assumptions.target_savings_pct, 1)}%"],
        ["Assumptions (effective savings)", f"{fmt(_scenario_effective_target(req.assumptions), 1)}%"],
        ["Assumptions (water $/AF)", f"${fmt(req.assumptions.water_price_per_acre_foot, 0)}"],
        ["Assumptions (kWh/AF)", fmt(req.assumptions.kwh_per_acre_foot, 0)],
        ["Assumptions (energy $/kWh)", f"${fmt(req.assumptions.energy_price_per_kwh, 2)}"],
        ["Notes", req.assumptions.notes or "-"],
        ["Data sources (demo)", "; ".join(req.assumptions.data_sources or [])],
        ["Constraints (demo)", "; ".join(req.assumptions.constraints or [])],
        ["Model/Build version (demo)", model_version],
    ]
    at = Table(audit, colWidths=[2.2 * inch, 4.2 * inch])
    at.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, THEME_GRID),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e7ea")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, THEME_LIGHT]),
            ]
        )
    )
    story.append(at)

    story.append(PageBreak())

    # PAGE 7 — Appendix JSON
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

    story.append(Paragraph("Raw JSON (truncated for PDF safety):", h2))
    story.append(Spacer(1, 6))
    raw = json.dumps(payload, indent=2)
    raw = raw[:24_000] + ("\n…\n" if len(raw) > 24_000 else "")
    story.append(XPreformatted(raw, mono))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Disclaimer:", h2))
    story.append(
        Paragraph(
            "This PDF is generated from a demo computation path. It shows the structure of an audit-ready report "
            "(KPIs, prescriptions, scenario comparison, economics, and metadata). For production, bind baselines and "
            "confidence to measured ET/soil/controller data and basin-specific compliance rules.",
            small,
        )
    )

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
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
    blocks_ = resolve_blocks(req)
    pres = compute_prescriptions(blocks_, req.assumptions)

    return {
        "field_id": req.field_id,
        "generated": datetime.now(timezone.utc).isoformat(),
        "assumptions": req.assumptions.model_dump(),
        "prescriptions": [
            {
                "block": asdict(p.block),
                "block_id": p.block.block_id,  # compat
                "label": p.block.label,
                "crop": p.block.crop,
                "location": p.block.location,
                "acres": p.block.acres,
                "baseline_in_per_week": p.block.baseline_in_per_week,
                "baseline_inches_per_week": p.block.baseline_in_per_week,  # compat
                "recommended_in_per_week": p.recommended_in_per_week,
                "recommended_inches_per_week": p.recommended_in_per_week,  # compat
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
        ],
    }


@router.post("/recommendation")
def recommendation(req: DemoRequest):
    return run(req)


@router.post("/report")
def report(req: DemoRequest):
    blocks_ = resolve_blocks(req)
    pres = compute_prescriptions(blocks_, req.assumptions)
    pdf = build_pdf(req, blocks_, pres)

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline; filename=agro_ai_weekly_proof_report_demo.pdf",
            "Cache-Control": "no-store",
        },
    )


# NEW: Same-origin GET PDF endpoint (for /demo/report.pdf proxy style)
@router.get("/report.pdf")
def report_pdf(
    block_ids: str = Query(default="", description="Comma-separated block IDs, e.g. B1,B2"),
    scenario: str = Query(default="normal", description="normal|heat|restriction"),
    target_savings_pct: Optional[float] = Query(default=None, description="Override target savings %"),
):
    bids = [b.strip() for b in (block_ids or "").split(",") if b.strip()]
    a = Assumptions()
    a.scenario = scenario or "normal"
    if target_savings_pct is not None:
        a.target_savings_pct = float(target_savings_pct)

    req = DemoRequest(block_ids=bids, mode="synthetic", assumptions=a)
    blocks_ = resolve_blocks(req)
    pres = compute_prescriptions(blocks_, req.assumptions)
    pdf = build_pdf(req, blocks_, pres)

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline; filename=agro_ai_weekly_proof_report_demo.pdf",
            "Cache-Control": "no-store",
        },
    )
