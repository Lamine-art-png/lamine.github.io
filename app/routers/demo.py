# app/routers/demo.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from io import BytesIO
import json
import math

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
        PageBreak,
        KeepTogether,
    )
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.charts.legends import Legend
except Exception as e:
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
    PageBreak = None
    KeepTogether = None
    Drawing = None
    String = None
    VerticalBarChart = None
    LinePlot = None
    Legend = None
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
    # What the UI displays
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
    Synthetic logic, but non-empty and supports overrides.
    """

    target_savings_pct = _num(assumptions.get("target_savings_pct"), 25.0)  # e.g. 20–35
    target_savings_pct = max(0.0, min(60.0, target_savings_pct))

    baseline_multiplier = _num(assumptions.get("baseline_multiplier"), 1.0)
    baseline_multiplier = max(0.2, min(3.0, baseline_multiplier))

    base_confidence = _num(assumptions.get("confidence"), 0.68)
    base_confidence = max(0.05, min(0.99, base_confidence))

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
            f"Demo ({mode}): synthetic weekly schedule derived from baseline ET assumptions and a "
            f"{savings_pct:.0f}% optimization target. Production uses ET₀ + Kc + soil water balance + telemetry."
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
    avg_savings = (sum(p.savings_pct for p in prescriptions) / len(prescriptions)) if prescriptions else 0.0

    return {
        "blocks": len(prescriptions),
        "total_acres": round(total_acres, 2),
        "total_gallons_saved_per_week": round(total_gal, 0),
        "avg_savings_pct": round(avg_savings, 1),
        "gallons_per_acre_inch": GALLONS_PER_ACRE_INCH,
    }


# -------------------------
# PDF helpers
# -------------------------

def _pretty_json(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, sort_keys=True)
    except Exception:
        return str(obj)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def _fmt_int(x: float) -> str:
    return f"{x:,.0f}"


def _fmt_float(x: float, n: int = 2) -> str:
    return f"{x:.{n}f}"


def _daily_profile(total_weekly_gal: float, pattern: str = "smooth") -> List[float]:
    """
    Create a 7-day split that looks realistic.
    """
    if total_weekly_gal <= 0:
        return [0.0] * 7

    if pattern == "weekend_light":
        weights = [1.05, 1.00, 1.00, 0.98, 0.98, 0.75, 0.75]
    elif pattern == "pulse":
        weights = [1.35, 0.80, 1.20, 0.75, 1.05, 0.45, 0.40]
    else:
        weights = [1.05, 1.00, 1.02, 0.98, 0.97, 0.99, 0.99]

    s = sum(weights)
    return [total_weekly_gal * (w / s) for w in weights]


def _build_schedule_rows(
    p: Prescription,
    assumptions: Dict[str, Any],
) -> List[List[Any]]:
    """
    Returns table rows: Day, Baseline gal, Recommended gal, Runtime (min), Window, Notes
    """
    gpm = _clamp(_num(assumptions.get("pump_gpm"), 850.0), 100.0, 4000.0)
    start_window = assumptions.get("irrigation_window", "04:00–08:00")
    pattern = assumptions.get("weekly_pattern", "smooth")

    baseline_weekly_gal = p.baseline_inches_per_week * p.acres * GALLONS_PER_ACRE_INCH
    rec_weekly_gal = p.recommended_inches_per_week * p.acres * GALLONS_PER_ACRE_INCH

    baseline_days = _daily_profile(baseline_weekly_gal, pattern=pattern)
    rec_days = _daily_profile(rec_weekly_gal, pattern=pattern)

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    rows: List[List[Any]] = []
    for i, d in enumerate(days):
        bg = baseline_days[i]
        rg = rec_days[i]
        minutes = 0.0 if gpm <= 0 else (rg / (gpm * 60.0))
        note = "Maintain soil profile" if i < 5 else "Weekend light set"
        rows.append([d, _fmt_int(bg), _fmt_int(rg), _fmt_float(minutes, 1), start_window, note])

    return rows


def _bar_chart(
    title: str,
    labels: List[str],
    values: List[float],
    width: float = 6.8 * inch,
    height: float = 2.3 * inch,
) -> Drawing:
    d = Drawing(width, height)
    d.add(String(0, height - 12, title, fontSize=11))

    chart = VerticalBarChart()
    chart.x = 30
    chart.y = 18
    chart.height = height - 40
    chart.width = width - 45
    chart.data = [values]
    chart.valueAxis.valueMin = 0
    vmax = max(values) if values else 1
    chart.valueAxis.valueMax = max(1, math.ceil(vmax * 1.15))
    chart.valueAxis.valueStep = max(1, math.ceil(chart.valueAxis.valueMax / 5))

    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.boxAnchor = "ne"
    chart.categoryAxis.labels.angle = 25
    chart.categoryAxis.labels.dy = -2
    chart.categoryAxis.labels.dx = -6

    # Use a nice brand-ish fill without hardcoding too many colors
    chart.bars[0].fillColor = colors.HexColor("#0b6b3a")

    d.add(chart)
    return d


def _line_chart_two_series(
    title: str,
    x_labels: List[str],
    series_a: List[float],
    series_b: List[float],
    label_a: str,
    label_b: str,
    width: float = 6.8 * inch,
    height: float = 2.3 * inch,
) -> Drawing:
    d = Drawing(width, height)
    d.add(String(0, height - 12, title, fontSize=11))

    lp = LinePlot()
    lp.x = 35
    lp.y = 20
    lp.height = height - 48
    lp.width = width - 60

    # x positions: 0..n-1
    n = min(len(series_a), len(series_b), len(x_labels))
    data_a = [(i, series_a[i]) for i in range(n)]
    data_b = [(i, series_b[i]) for i in range(n)]

    lp.data = [data_a, data_b]
    lp.lines[0].strokeColor = colors.HexColor("#111827")
    lp.lines[0].strokeWidth = 1.6
    lp.lines[1].strokeColor = colors.HexColor("#0b6b3a")
    lp.lines[1].strokeWidth = 2.0

    ymax = max([0.0] + series_a[:n] + series_b[:n])
    lp.yValueAxis.valueMin = 0
    lp.yValueAxis.valueMax = max(1, math.ceil(ymax * 1.2))
    lp.yValueAxis.valueStep = max(1, math.ceil(lp.yValueAxis.valueMax / 4))

    lp.xValueAxis.valueMin = 0
    lp.xValueAxis.valueMax = max(1, n - 1)
    lp.xValueAxis.valueStep = 1
    lp.xValueAxis.labelTextFormat = lambda v: x_labels[int(v)] if 0 <= int(v) < n else ""

    d.add(lp)

    # Legend
    leg = Legend()
    leg.x = width - 150
    leg.y = height - 40
    leg.alignment = "right"
    leg.colorNamePairs = [
        (colors.HexColor("#111827"), label_a),
        (colors.HexColor("#0b6b3a"), label_b),
    ]
    d.add(leg)

    return d


def _on_page(canvas, doc):
    # Header + footer
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#0b6b3a"))
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(0.75 * inch, 10.85 * inch, "AGRO-AI — Weekly Proof Report (DEMO)")

    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(7.75 * inch, 0.55 * inch, f"Page {doc.page}")
    canvas.restoreState()


# -------------------------
# PDF generation (5+ pages)
# -------------------------

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
        topMargin=0.85 * inch,
        bottomMargin=0.75 * inch,
        title="AGRO-AI Weekly Proof Report",
        author="AGRO-AI",
    )

    styles = getSampleStyleSheet()
    title = styles["Title"]
    body = styles["BodyText"]

    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, leading=22, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, leading=16, spaceAfter=8)

    small = ParagraphStyle("small", parent=body, fontSize=9, leading=11)
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=8.5, leading=10)

    story: List[Any] = []

    # ---------- Page 1: Cover ----------
    story.append(Spacer(1, 1.4 * inch))
    story.append(Paragraph("AGRO-AI — Weekly Proof Report (DEMO)", ParagraphStyle("cover", parent=title, fontSize=26, leading=30)))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Irrigation intelligence + reporting layer for commercial farms.", ParagraphStyle("sub", parent=body, fontSize=12, leading=16, textColor=colors.HexColor("#334155"))))
    story.append(Spacer(1, 24))

    cover_meta = [
        f"<b>Generated (UTC):</b> {generated_at}",
        f"<b>Mode:</b> {mode}",
        f"<b>Blocks selected:</b> {', '.join([p.block_id for p in prescriptions])}",
        f"<b>Total acres:</b> {totals.get('total_acres', 0)}",
        f"<b>Total water saved:</b> {totals.get('total_gallons_saved_per_week', 0):,.0f} gallons/week",
    ]
    story.append(Paragraph("<br/>".join(cover_meta), small))
    story.append(Spacer(1, 18))
    story.append(Paragraph(
        "<b>Disclaimer:</b> This report is a demo artifact. Values are synthetic to illustrate reporting capabilities. "
        "Production reports include ET₀ sources, crop coefficients, soil water balance, irrigation events, and audit trail.",
        small,
    ))
    story.append(PageBreak())

    # ---------- Page 2: Executive summary ----------
    story.append(Paragraph("Executive summary", h1))

    # Add some “enterprise-looking” derived KPIs
    # These are assumptions-driven so you can tune during demos.
    water_cost_per_kgal = _clamp(_num(assumptions.get("water_cost_per_kgal"), 3.5), 0.0, 50.0)  # $/1000 gal
    kwh_per_kgal = _clamp(_num(assumptions.get("kwh_per_kgal"), 1.15), 0.0, 10.0)
    electricity_cost_per_kwh = _clamp(_num(assumptions.get("electricity_cost_per_kwh"), 0.22), 0.0, 2.0)
    labor_minutes_saved_per_block_per_week = _clamp(_num(assumptions.get("labor_minutes_saved_per_block_per_week"), 45.0), 0.0, 600.0)

    total_kgal = float(totals.get("total_gallons_saved_per_week", 0.0)) / 1000.0
    est_water_cost_saved = total_kgal * water_cost_per_kgal
    est_kwh_saved = total_kgal * kwh_per_kgal
    est_energy_cost_saved = est_kwh_saved * electricity_cost_per_kwh
    est_labor_hours_saved = (len(prescriptions) * labor_minutes_saved_per_block_per_week) / 60.0

    kpi_data = [
        ["KPI (weekly)", "Value", "Notes"],
        ["Water saved", f"{_fmt_int(totals.get('total_gallons_saved_per_week', 0))} gal/wk", f"Across {totals.get('total_acres', 0)} acres"],
        ["Avg savings", f"{totals.get('avg_savings_pct', 0)}%", "Optimization vs baseline"],
        ["Estimated water $ saved", _fmt_money(est_water_cost_saved), f"Assumes ${water_cost_per_kgal:.2f}/kgal"],
        ["Estimated energy saved", f"{_fmt_int(est_kwh_saved)} kWh", f"Assumes {kwh_per_kgal:.2f} kWh/kgal"],
        ["Estimated energy $ saved", _fmt_money(est_energy_cost_saved), f"Assumes ${electricity_cost_per_kwh:.2f}/kWh"],
        ["Estimated labor saved", f"{_fmt_float(est_labor_hours_saved, 1)} hrs", f"Assumes {labor_minutes_saved_per_block_per_week:.0f} min/block/wk"],
    ]
    kpi_table = Table(kpi_data, colWidths=[2.2 * inch, 1.6 * inch, 2.8 * inch])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b6b3a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D6D6D6")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8F6")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("Key takeaways", h2))
    bullets = [
        "This report demonstrates the reporting layer: block-level recommendations, KPIs, and an audit-ready narrative.",
        "Production deployment connects to telemetry (controllers/sensors), ET₀ sources, and generates compliance-ready proof.",
        "The same pipeline supports API integration with OEM platforms and farm management software.",
    ]
    story.append(Paragraph("<br/>".join([f"• {b}" for b in bullets]), small))

    story.append(PageBreak())

    # ---------- Page 3: Portfolio overview + charts ----------
    story.append(Paragraph("Portfolio overview", h1))

    port_rows = [["Block", "Crop", "Location", "Acres", "Baseline (in/wk)", "Rec (in/wk)", "Savings", "Gal saved/wk", "Conf"]]
    for p in prescriptions:
        port_rows.append([
            p.block_id,
            p.crop,
            p.location,
            _fmt_float(p.acres, 1),
            _fmt_float(p.baseline_inches_per_week, 2),
            _fmt_float(p.recommended_inches_per_week, 2),
            f"{_fmt_float(p.savings_pct, 1)}%",
            _fmt_int(p.gallons_saved_per_week),
            _fmt_float(p.confidence, 2),
        ])
    port_table = Table(port_rows, repeatRows=1, colWidths=[0.65*inch, 0.9*inch, 1.2*inch, 0.6*inch, 0.95*inch, 0.85*inch, 0.7*inch, 1.0*inch, 0.55*inch])
    port_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D6D6D6")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FF")]),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
    ]))
    story.append(port_table)
    story.append(Spacer(1, 12))

    labels = [p.block_id for p in prescriptions]
    gal_vals = [float(p.gallons_saved_per_week) for p in prescriptions]
    story.append(_bar_chart("Water saved by block (gallons/week)", labels, gal_vals))
    story.append(Spacer(1, 10))

    # Baseline vs recommended (inches/week) chart
    base_vals = [float(p.baseline_inches_per_week) for p in prescriptions]
    rec_vals = [float(p.recommended_inches_per_week) for p in prescriptions]
    # A line chart across blocks is okay; this is demo-friendly
    story.append(_line_chart_two_series(
        "Baseline vs recommended (inches/week)",
        labels,
        base_vals,
        rec_vals,
        "Baseline",
        "Recommended",
    ))

    story.append(PageBreak())

    # ---------- Page 4+: Per-block detail pages ----------
    story.append(Paragraph("Block detail", h1))
    story.append(Paragraph("The following pages show an example weekly schedule table + daily profile chart per block.", small))
    story.append(Spacer(1, 10))

    for idx, p in enumerate(prescriptions):
        # Force each block to start on a fresh page AFTER the intro block-detail page
        story.append(PageBreak())

        story.append(Paragraph(f"{p.block_id} — {p.crop} — {p.location}", h1))

        info = [
            ["Field / Block", p.label],
            ["Crop", p.crop],
            ["Location", p.location],
            ["Acres", _fmt_float(p.acres, 1)],
            ["Baseline (in/wk)", _fmt_float(p.baseline_inches_per_week, 2)],
            ["Recommended (in/wk)", _fmt_float(p.recommended_inches_per_week, 2)],
            ["Savings", f"{_fmt_float(p.savings_pct, 1)}%"],
            ["Water saved (gal/wk)", _fmt_int(p.gallons_saved_per_week)],
            ["Confidence", _fmt_float(p.confidence, 2)],
        ]
        info_tbl = Table(info, colWidths=[1.8 * inch, 4.8 * inch])
        info_tbl.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D6D6D6")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F6F8F6")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(info_tbl)
        story.append(Spacer(1, 10))

        story.append(Paragraph("Weekly irrigation schedule (demo)", h2))
        sched_rows = [["Day", "Baseline gal", "Recommended gal", "Runtime (min)", "Window", "Notes"]]
        sched_rows.extend(_build_schedule_rows(p, assumptions))
        sched_tbl = Table(sched_rows, repeatRows=1, colWidths=[0.6*inch, 1.0*inch, 1.1*inch, 0.95*inch, 1.1*inch, 2.0*inch])
        sched_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b6b3a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D6D6D6")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8F6")]),
            ("ALIGN", (1, 1), (3, -1), "RIGHT"),
            ("FONTSIZE", (0, 1), (-1, -1), 8.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(sched_tbl)
        story.append(Spacer(1, 10))

        # Daily chart baseline vs recommended gallons
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        baseline_weekly_gal = p.baseline_inches_per_week * p.acres * GALLONS_PER_ACRE_INCH
        rec_weekly_gal = p.recommended_inches_per_week * p.acres * GALLONS_PER_ACRE_INCH
        pattern = assumptions.get("weekly_pattern", "smooth")
        baseline_days = _daily_profile(baseline_weekly_gal, pattern=pattern)
        rec_days = _daily_profile(rec_weekly_gal, pattern=pattern)

        story.append(_line_chart_two_series(
            "Daily gallons profile (baseline vs recommended)",
            days,
            baseline_days,
            rec_days,
            "Baseline gal/day",
            "Recommended gal/day",
        ))
        story.append(Spacer(1, 10))

        story.append(Paragraph("<b>Recommendation narrative</b>", h2))
        story.append(Paragraph(
            f"{p.reason} "
            "In production, this section expands into: ET₀ source attribution, soil constraints, irrigation events, and a change log.",
            small,
        ))

    # ---------- Final pages: Assumptions + Methodology ----------
    story.append(PageBreak())
    story.append(Paragraph("Assumptions & data policy (demo)", h1))
    story.append(Paragraph(
        "This section exists to demonstrate an audit-ready reporting format. "
        "In production deployments, AGRO-AI records input sources, model versions, and recommendation provenance.",
        small,
    ))
    story.append(Spacer(1, 10))

    # Assumptions JSON block
    assumptions_text = _pretty_json(assumptions if assumptions is not None else {})
    assumptions_html = (
        assumptions_text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    story.append(Paragraph("<b>Assumptions (input)</b>", h2))
    story.append(Paragraph(assumptions_html, mono))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Methodology appendix (demo)", h1))
    story.append(Paragraph(
        "Core formula used in this demo report:",
        small,
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Gallons saved = (baseline_inches_per_week − recommended_inches_per_week) × acres × 27,154.",
        mono,
    ))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Production methodology expands to include: ET₀ from trusted sources, crop coefficients (Kc), "
        "soil water balance, rainfall integration, irrigation event ingestion, and controller write-back where permitted. "
        "Every recommendation can be tied to inputs (provenance) for compliance and reporting.",
        small,
    ))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Next steps (what this becomes in production)", h2))
    nxt = [
        "Connect ET₀ source(s) + station metadata; record source attribution in every report.",
        "Ingest irrigation events from controller telemetry (read-only first).",
        "Generate a weekly PDF + JSON report package per ranch/portfolio; store with retention policies.",
        "Expose the same objects via API for OEM dashboards and farm management platforms.",
    ]
    story.append(Paragraph("<br/>".join([f"• {x}" for x in nxt]), small))

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()


# -------------------------
# Routes (match live-demo contract)
# -------------------------

@router.get("/blocks")
def demo_blocks():
    return [b.model_dump() for b in get_demo_blocks()]


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

