# app/routers/demo.py
from __future__ import annotations

import io
import json
import uuid
import math
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/demo", tags=["demo"])

MODEL_VERSION = "demo-sim-v3"
ACRE_FOOT_GALLONS = 325851.4
ACRE_INCH_GALLONS = ACRE_FOOT_GALLONS / 12.0


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def gallons_from_inches_acres(inches: float, acres: float) -> float:
    return inches * acres * ACRE_INCH_GALLONS


def acre_feet_from_inches_acres(inches: float, acres: float) -> float:
    return (inches / 12.0) * acres


def deterministic_risk_score(count(geo_key: str) -> int:
    # Deterministic "risk score" 1-100 based on location key (demo-safe, repeatable)
    h = int(hashlib.md5(geo_key.encode("utf-8")).hexdigest()[:6], 16)
    return int(25 + (h % 70))  # 25..94


@dataclass
class DemoBlock:
    block_id: str
    label: str
    crop: str
    acres: float
    location: str
    county: str
    state: str
    baseline_inches_per_week: float
    # optional irrigation system context for “enterprise-ish” outputs
    system_flow_gpm: float = 900.0
    application_efficiency: float = 0.85


# You can tune these to match your narrative (vineyard + almonds etc.)
DEMO_BLOCKS: Dict[str, DemoBlock] = {
    "B1": DemoBlock(
        block_id="B1",
        label="Block 1",
        crop="Vineyard",
        acres=12.4,
        location="Napa, CA",
        county="Napa",
        state="CA",
        baseline_inches_per_week=1.00,
        system_flow_gpm=800.0,
        application_efficiency=0.86,
    ),
    "B2": DemoBlock(
        block_id="B2",
        label="Block 2",
        crop="Vineyard",
        acres=18.1,
        location="Sonoma, CA",
        county="Sonoma",
        state="CA",
        baseline_inches_per_week=1.00,
        system_flow_gpm=950.0,
        application_efficiency=0.84,
    ),
    "B3": DemoBlock(
        block_id="B3",
        label="Block 3",
        crop="Almonds",
        acres=22.0,
        location="Fresno, CA",
        county="Fresno",
        state="CA",
        baseline_inches_per_week=0.75,
        system_flow_gpm=1100.0,
        application_efficiency=0.83,
    ),
}


class DemoRunRequest(BaseModel):
    block_ids: List[str] = Field(..., min_length=1)
    mode: str = Field(default="synthetic")
    assumptions: Dict[str, Any] = Field(default_factory=dict)


class DemoPrescription(BaseModel):
    block_id: str
    label: str
    crop: str
    acres: float
    location: str
    county: str
    state: str

    baseline_inches_per_week: float
    recommended_inches_per_week: float
    savings_pct: float

    baseline_gallons_per_week: float
    recommended_gallons_per_week: float
    gallons_saved_per_week: float
    acre_feet_saved_per_week: float

    # enterprise-ish metadata
    water_risk_score: int
    confidence: float
    reason: str


class DemoRunResponse(BaseModel):
    request_id: str
    generated_at: str
    mode: str
    model_version: str
    assumptions: Dict[str, Any]

    # Compatibility fields for various UIs:
    summary: str
    prescriptions: List[DemoPrescription]
    recommendations: List[DemoPrescription]  # alias
    report_endpoint: str


def resolve_blocks(block_ids: List[str], assumptions: Dict[str, Any]) -> List[DemoBlock]:
    blocks: List[DemoBlock] = []
    for bid in block_ids:
        if bid == "CUSTOM":
            custom = assumptions.get("custom_block") or {}
            try:
                blocks.append(
                    DemoBlock(
                        block_id="CUSTOM",
                        label=custom.get("label") or "Custom block",
                        crop=custom.get("crop") or "Unknown crop",
                        acres=float(custom.get("acres") or 10.0),
                        location=custom.get("location") or "Custom, CA",
                        county=custom.get("county") or "Unknown",
                        state=custom.get("state") or "CA",
                        baseline_inches_per_week=float(custom.get("baseline_inches_per_week") or 1.0),
                        system_flow_gpm=float(custom.get("system_flow_gpm") or 900.0),
                        application_efficiency=float(custom.get("application_efficiency") or 0.85),
                    )
                )
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid custom_block: {e}")
        else:
            if bid not in DEMO_BLOCKS:
                raise HTTPException(status_code=400, detail=f"Unknown block_id: {bid}")
            blocks.append(DEMO_BLOCKS[bid])
    return blocks


def compute_prescriptions(blocks: List[DemoBlock], assumptions: Dict[str, Any]) -> List[DemoPrescription]:
    # Default: 25% savings target unless user overrides
    target = assumptions.get("target_savings_pct", 25)
    try:
        target = float(target)
    except Exception:
        target = 25.0
    target = clamp(target, 5, 60)

    # Optional: “kWh per acre-foot” (used in PDF page, not required)
    # Put defaults that look enterprise-ish but safe
    assumptions.setdefault("kwh_per_acre_foot", 280)        # placeholder
    assumptions.setdefault("water_unit_price_per_af", 250)  # placeholder
    assumptions.setdefault("energy_price_per_kwh", 0.22)    # placeholder

    out: List[DemoPrescription] = []
    for b in blocks:
        recommended = b.baseline_inches_per_week * (1.0 - target / 100.0)
        recommended = max(0.0, round(recommended, 3))

        base_gal = gallons_from_inches_acres(b.baseline_inches_per_week, b.acres)
        rec_gal = gallons_from_inches_acres(recommended, b.acres)
        saved_gal = max(0.0, base_gal - rec_gal)
        saved_af = max(0.0, acre_feet_from_inches_acres(b.baseline_inches_per_week - recommended, b.acres))

        risk = deterministic_risk_score(f"{b.county},{b.state}")

        out.append(
            DemoPrescription(
                block_id=b.block_id,
                label=b.label,
                crop=b.crop,
                acres=round(b.acres, 2),
                location=b.location,
                county=b.county,
                state=b.state,
                baseline_inches_per_week=round(b.baseline_inches_per_week, 3),
                recommended_inches_per_week=round(recommended, 3),
                savings_pct=round(target, 1),
                baseline_gallons_per_week=round(base_gal, 0),
                recommended_gallons_per_week=round(rec_gal, 0),
                gallons_saved_per_week=round(saved_gal, 0),
                acre_feet_saved_per_week=round(saved_af, 3),
                water_risk_score=risk,
                confidence=0.62,
                reason="demo logic: reduce baseline by target savings % (placeholder for model)",
            )
        )
    return out


@router.get("/blocks")
def get_blocks():
    # Rich block objects for the UI
    items = []
    for b in DEMO_BLOCKS.values():
        items.append(
            {
                "block_id": b.block_id,
                "label": f'{b.label} — {b.crop} — {b.location}',
                "crop": b.crop,
                "acres": b.acres,
                "location": b.location,
                "county": b.county,
                "state": b.state,
                "baseline_inches_per_week": b.baseline_inches_per_week,
                "system_flow_gpm": b.system_flow_gpm,
                "application_efficiency": b.application_efficiency,
            }
        )
    return JSONResponse(items)


@router.post("/run", response_model=DemoRunResponse)
def run(req: DemoRunRequest):
    request_id = str(uuid.uuid4())
    generated_at = iso_now()

    blocks = resolve_blocks(req.block_ids, req.assumptions)
    prescriptions = compute_prescriptions(blocks, req.assumptions)

    # Human readable summary (helps homepage card)
    first = prescriptions[0]
    summary = (
        f"{first.label} — {first.crop} — {first.location}: "
        f"{first.baseline_inches_per_week:.2f} in/wk → {first.recommended_inches_per_week:.2f} in/wk "
        f"({first.savings_pct:.0f}% savings)."
    )

    resp = DemoRunResponse(
        request_id=request_id,
        generated_at=generated_at,
        mode=req.mode,
        model_version=MODEL_VERSION,
        assumptions=req.assumptions,
        summary=summary,
        prescriptions=prescriptions,
        recommendations=prescriptions,  # alias for UI compatibility
        report_endpoint="/v1/demo/report",
    )
    return resp


@router.post("/recommendation", response_model=DemoRunResponse)
def recommendation(req: DemoRunRequest):
    # Alias endpoint because some frontends call /recommendation
    return run(req)


# ---------- PDF REPORT (multi-page, charts, tables, compliance, risk, scenarios) ----------

def _require_pdf_deps():
    try:
        import reportlab  # noqa: F401
        return True
    except Exception:
        return False


def _build_charts_png(prescriptions: List[DemoPrescription], scenario_pcts: List[float]) -> Tuple[Optional[bytes], Optional[bytes]]:
    # Returns (bar_chart_png, scenario_chart_png)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
    except Exception:
        return (None, None)

    # Bar chart: baseline vs recommended gallons per week
    labels = [p.block_id for p in prescriptions]
    baseline = [p.baseline_gallons_per_week for p in prescriptions]
    recommended = [p.recommended_gallons_per_week for p in prescriptions]

    # Chart 1
    fig = plt.figure(figsize=(8, 3.2))
    ax = fig.add_subplot(111)
    x = list(range(len(labels)))
    ax.bar([i - 0.2 for i in x], baseline, width=0.4, label="Baseline")
    ax.bar([i + 0.2 for i in x], recommended, width=0.4, label="Recommended")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Gallons / week")
    ax.set_title("Water Use (Baseline vs Recommended)")
    ax.legend()
    buf1 = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf1, format="png", dpi=200)
    plt.close(fig)
    bar_png = buf1.getvalue()

    # Chart 2: Scenario savings comparison (aggregate)
    # Build total saved AF under each scenario relative to baseline
    base_total_af = sum(acre_feet_from_inches_acres(p.baseline_inches_per_week, p.acres) for p in prescriptions)
    scenario_saved_af = []
    for pct in scenario_pcts:
        pct = clamp(float(pct), 5, 60)
        rec_total_af = sum(acre_feet_from_inches_acres(p.baseline_inches_per_week * (1 - pct / 100.0), p.acres) for p in prescriptions)
        scenario_saved_af.append(max(0.0, base_total_af - rec_total_af))

    fig2 = plt.figure(figsize=(8, 3.2))
    ax2 = fig2.add_subplot(111)
    ax2.plot([str(int(p)) + "%" for p in scenario_pcts], scenario_saved_af, marker="o")
    ax2.set_ylabel("Acre-feet saved / week")
    ax2.set_title("Scenario Comparison (weekly savings)")
    ax2.grid(True, alpha=0.25)
    buf2 = io.BytesIO()
    fig2.tight_layout()
    fig2.savefig(buf2, format="png", dpi=200)
    plt.close(fig2)
    scenario_png = buf2.getvalue()

    return (bar_png, scenario_png)


def build_pdf_report(
    request_id: str,
    generated_at: str,
    mode: str,
    assumptions: Dict[str, Any],
    prescriptions: List[DemoPrescription],
    scenario_pcts: List[float],
) -> bytes:
    if not _require_pdf_deps():
        raise HTTPException(
            status_code=500,
            detail="PDF dependencies missing. Add 'reportlab' (and optionally 'matplotlib') to your API requirements.",
        )

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
        Image as RLImage,
    )

    styles = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=styles["Heading1"], spaceAfter=10)
    H2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceAfter=8)
    BODY = ParagraphStyle("BODY", parent=styles["BodyText"], leading=14, spaceAfter=6)
    SMALL = ParagraphStyle("SMALL", parent=styles["BodyText"], fontSize=9, leading=11, textColor=colors.grey)

    total_saved_gal = sum(p.gallons_saved_per_week for p in prescriptions)
    total_saved_af = sum(p.acre_feet_saved_per_week for p in prescriptions)

    # Simple “impact economics” (demo placeholders)
    kwh_per_af = float(assumptions.get("kwh_per_acre_foot", 280))
    price_per_af = float(assumptions.get("water_unit_price_per_af", 250))
    price_per_kwh = float(assumptions.get("energy_price_per_kwh", 0.22))
    est_kwh_saved = total_saved_af * kwh_per_af
    est_water_value = total_saved_af * price_per_af
    est_energy_value = est_kwh_saved * price_per_kwh

    # Charts (optional)
    bar_png, scenario_png = _build_charts_png(prescriptions, scenario_pcts)

    # Compliance audit payload hash (SGMA-ish audit trail vibe)
    audit_payload = {
        "request_id": request_id,
        "generated_at": generated_at,
        "mode": mode,
        "model_version": MODEL_VERSION,
        "assumptions": assumptions,
        "prescriptions": [p.model_dump() for p in prescriptions],
        "scenario_pcts": scenario_pcts,
    }
    audit_hash = stable_hash(audit_payload)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54)

    story: List[Any] = []

    # Page 1 — Cover
    story.append(Paragraph("AGRO-AI — Weekly Proof Report (DEMO)", H1))
    story.append(Paragraph(f"Generated: <b>{generated_at}</b>", BODY))
    story.append(Paragraph(f"Request ID: <b>{request_id}</b> &nbsp;&nbsp; Model: <b>{MODEL_VERSION}</b> &nbsp;&nbsp; Mode: <b>{mode}</b>", BODY))
    story.append(Paragraph(f"Audit hash: <b>{audit_hash}</b>", BODY))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>Executive headline</b>: block-level water use optimization with compliance-ready reporting.", BODY))
    story.append(Spacer(1, 14))

    headline_table = [
        ["Metric", "Weekly (selected blocks)"],
        ["Water saved", f"{total_saved_gal:,.0f} gallons  ({total_saved_af:.3f} acre-feet)"],
        ["Est. pumping energy saved*", f"{est_kwh_saved:,.0f} kWh"],
        ["Est. value of water saved*", f"${est_water_value:,.0f} / week"],
        ["Est. energy cost avoided*", f"${est_energy_value:,.0f} / week"],
    ]
    t = Table(headline_table, colWidths=[2.2 * inch, 3.7 * inch])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b6b3a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(Paragraph("*Estimated values use demo defaults unless overridden in assumptions.", SMALL))
    story.append(PageBreak())

    # Page 2 — Prescriptions table
    story.append(Paragraph("Prescriptions Summary", H2))
    story.append(Paragraph("Block-level weekly recommendations and savings.", BODY))

    rows = [["Block", "Crop", "Acres", "Baseline (in/wk)", "Rec. (in/wk)", "Saved (gal/wk)", "Risk"]]
    for p in prescriptions:
        rows.append(
            [
                p.block_id,
                p.crop,
                f"{p.acres:.1f}",
                f"{p.baseline_inches_per_week:.2f}",
                f"{p.recommended_inches_per_week:.2f}",
                f"{p.gallons_saved_per_week:,.0f}",
                f"{p.water_risk_score}/100",
            ]
        )

    table = Table(rows, colWidths=[0.7 * inch, 1.2 * inch, 0.7 * inch, 1.0 * inch, 0.9 * inch, 1.1 * inch, 0.7 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 12))

    if bar_png:
        story.append(Paragraph("Water Use Chart", H2))
        story.append(Paragraph("Baseline vs recommended water use (weekly).", BODY))
        story.append(RLImage(io.BytesIO(bar_png), width=7.0 * inch, height=2.8 * inch))
    else:
        story.append(Paragraph("Charts unavailable (matplotlib not installed).", SMALL))

    story.append(PageBreak())

    # Page 3 — Water risk score (by county/zone)
    story.append(Paragraph("Water Risk Score (Demo)", H2))
    story.append(Paragraph("A simple county/zone-level risk indicator used for prioritization and reporting.", BODY))

    risk_rows = [["County", "State", "Blocks", "Risk Score (1–100)", "Interpretation"]]
    # aggregate by county/state
    agg: Dict[Tuple[str, str], List[DemoPrescription]] = {}
    for p in prescriptions:
        agg.setdefault((p.county, p.state), []).append(p)

    for (county, state), ps in agg.items():
        score = int(round(sum(pp.water_risk_score for pp in ps) / len(ps)))
        interp = "High" if score >= 75 else ("Moderate" if score >= 55 else "Lower")
        risk_rows.append([county, state, ", ".join(pp.block_id for pp in ps), f"{score}/100", interp])

    risk_table = Table(risk_rows, colWidths=[1.6 * inch, 0.6 * inch, 1.3 * inch, 1.2 * inch, 1.1 * inch])
    risk_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b6b3a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdf4")]),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(risk_table)
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "Note: This demo score is deterministic by location key (for repeatability). "
            "Production score can combine drought indices, allocations, basin stress, SGMA status, and historical deficit signals.",
            SMALL,
        )
    )
    story.append(PageBreak())

    # Page 4 — Compliance-ready audit trail
    story.append(Paragraph("Compliance-Ready Audit Trail (SGMA-style)", H2))
    story.append(Paragraph("Fields typically required for operational and compliance reporting.", BODY))

    compliance_rows = [
        ["Field", "Value"],
        ["Generated at", generated_at],
        ["Request ID", request_id],
        ["Audit hash", audit_hash],
        ["Model version", MODEL_VERSION],
        ["Data provenance (demo)", "Weather: synthetic | Soil: synthetic | ET0: synthetic | Telemetry: synthetic"],
        ["Recommendation policy", "Target savings % applied to baseline (placeholder)"],
        ["Write-back", "Read-only demo (no actuation)"],
        ["Retention", "Configurable (per customer)"],
    ]
    compliance = Table(compliance_rows, colWidths=[2.2 * inch, 3.7 * inch])
    compliance.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(compliance)

    story.append(Spacer(1, 12))
    story.append(Paragraph("Assumptions Used", H2))
    story.append(Paragraph(f"<pre>{json.dumps(assumptions, indent=2)[:1500]}</pre>", SMALL))
    story.append(PageBreak())

    # Page 5 — Scenario comparison (25% vs 35% etc.)
    story.append(Paragraph("Scenario Comparison", H2))
    story.append(Paragraph("Compare target savings policies (e.g., 25% vs 35%).", BODY))

    # Build scenario table
    scenario_rows = [["Scenario", "Target savings", "Total gallons saved / week", "Total AF saved / week"]]
    base_total_gal = sum(p.baseline_gallons_per_week for p in prescriptions)
    base_total_af = sum(acre_feet_from_inches_acres(p.baseline_inches_per_week, p.acres) for p in prescriptions)

    for pct in scenario_pcts:
        pct = clamp(float(pct), 5, 60)
        rec_total_gal = sum(gallons_from_inches_acres(p.baseline_inches_per_week * (1 - pct / 100.0), p.acres) for p in prescriptions)
        rec_total_af = sum(acre_feet_from_inches_acres(p.baseline_inches_per_week * (1 - pct / 100.0), p.acres) for p in prescriptions)
        scenario_rows.append(
            [
                f"Policy {int(pct)}%",
                f"{pct:.0f}%",
                f"{(base_total_gal - rec_total_gal):,.0f}",
                f"{(base_total_af - rec_total_af):.3f}",
            ]
        )

    scen_table = Table(scenario_rows, colWidths=[1.2 * inch, 1.0 * inch, 2.0 * inch, 1.7 * inch])
    scen_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b6b3a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdf4")]),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(scen_table)
    story.append(Spacer(1, 12))

    if scenario_png:
        story.append(RLImage(io.BytesIO(scenario_png), width=7.0 * inch, height=2.8 * inch))
    else:
        story.append(Paragraph("Scenario chart unavailable (matplotlib not installed).", SMALL))

    story.append(PageBreak())

    # Page 6 — Appendix (raw JSON)
    story.append(Paragraph("Appendix: Raw Payload + Outputs", H2))
    story.append(Paragraph("Useful for integration debugging and audit review.", BODY))
    raw = json.dumps(audit_payload, indent=2)
    story.append(Paragraph(f"<pre>{raw[:3500]}</pre>", SMALL))
    story.append(Paragraph("…(truncated for demo)", SMALL))

    doc.build(story)
    return buf.getvalue()


@router.post("/report")
def report(req: DemoRunRequest):
    request_id = str(uuid.uuid4())
    generated_at = iso_now()

    blocks = resolve_blocks(req.block_ids, req.assumptions)
    prescriptions = compute_prescriptions(blocks, req.assumptions)

    # Scenario list (default to your “enterprise brutal” ask)
    scenario_pcts = req.assumptions.get("scenario_savings_pcts", [25, 35])
    if not isinstance(scenario_pcts, list) or not scenario_pcts:
        scenario_pcts = [25, 35]
    scenario_pcts = [float(x) for x in scenario_pcts][:5]

    pdf_bytes = build_pdf_report(
        request_id=request_id,
        generated_at=generated_at,
        mode=req.mode,
        assumptions=req.assumptions,
        prescriptions=prescriptions,
        scenario_pcts=scenario_pcts,
    )

    headers = {"Content-Disposition": 'inline; filename="agroai_weekly_proof_report_demo.pdf"'}
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)

