from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import io
import math
import random

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader

# Optional charts (safe if matplotlib installed)
def _chart_png(title: str, xs, ys):
    try:
        import matplotlib.pyplot as plt
        buf = io.BytesIO()
        plt.figure()
        plt.title(title)
        plt.plot(xs, ys)
        plt.xlabel("Week")
        plt.ylabel("Value")
        plt.tight_layout()
        plt.savefig(buf, format="png", dpi=140)
        plt.close()
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        return None

ACRE_INCH_GAL = 27154.285
ACRE_FOOT_GAL = 325851.0

router = APIRouter(tags=["demo"])

class Assumptions(BaseModel):
    scenario: str = Field(default="normal")
    target_savings_percent: float = Field(default=25)
    scenario_comparison: str = Field(default="")
    kwh_per_acre_foot: float = Field(default=280)
    water_price_per_acre_foot: float = Field(default=250)
    energy_price_per_kwh: float = Field(default=0.22)
    notes: str = Field(default="")

class CustomBlock(BaseModel):
    crop: str
    location: str
    acres: float
    baseline_inches_week: float

class DemoRunIn(BaseModel):
    block_ids: List[str] = Field(default_factory=lambda: ["B1"])
    mode: str = Field(default="synthetic")
    assumptions: Assumptions = Field(default_factory=Assumptions)
    custom_block: Optional[CustomBlock] = None
    report_pages: Optional[int] = 100

BLOCKS = [
    {"id": "B1", "name": "Vineyard North (12.4 ac)", "crop": "Vineyard", "location": "Napa, CA", "acres": 12.4, "baseline_inches_week": 1.0},
    {"id": "B2", "name": "Vineyard South (8.1 ac)", "crop": "Vineyard", "location": "Napa, CA", "acres": 8.1, "baseline_inches_week": 0.9},
]

@router.get("/v1/health")
def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z", "service": "agro-ai-demo"}

@router.get("/v1/demo/blocks")
def blocks():
    return BLOCKS

def _scenario_scalar(s: str) -> float:
    s = (s or "normal").lower()
    if s == "heat":
        return 1.18
    if s == "restriction":
        return 0.78
    return 1.0

def _compute(blocks: List[Dict[str, Any]], a: Assumptions) -> Dict[str, Any]:
    scenario = (a.scenario or "normal").lower()
    scalar = _scenario_scalar(scenario)
    target = max(0.0, min(0.9, (a.target_savings_percent or 0) / 100.0))

    acres_total = sum(float(b["acres"]) for b in blocks)
    baseline_gal = 0.0

    for b in blocks:
        bi = float(b["baseline_inches_week"]) * scalar
        baseline_gal += float(b["acres"]) * bi * ACRE_INCH_GAL

    recommended_gal = baseline_gal * (1 - target)
    savings_gal = max(0.0, baseline_gal - recommended_gal)
    savings_af = savings_gal / ACRE_FOOT_GAL

    energy_saved_kwh = savings_af * float(a.kwh_per_acre_foot)
    energy_saved_usd = energy_saved_kwh * float(a.energy_price_per_kwh)
    water_saved_usd = savings_af * float(a.water_price_per_acre_foot)

    # Simple weekly schedule (illustrative, consistent)
    # 7 days, gallons/day allocated with mild variation
    rng = random.Random(42 + int(target * 1000) + int(acres_total * 10))
    day_fracs = [max(0.08, min(0.18, 1/7 + rng.uniform(-0.03, 0.03))) for _ in range(7)]
    ssum = sum(day_fracs)
    day_fracs = [f/ssum for f in day_fracs]
    schedule = [{"day": i+1, "recommended_gal": recommended_gal * day_fracs[i]} for i in range(7)]

    return {
        "mode": "synthetic-live",
        "scenario": scenario,
        "totals": {
            "acres": acres_total,
            "baseline_gal_week": baseline_gal,
            "recommended_gal_week": recommended_gal,
            "savings_gal_week": savings_gal,
        },
        "economics": {
            "savings_acre_feet_week": savings_af,
            "energy_saved_kwh_week": energy_saved_kwh,
            "energy_saved_usd_week": energy_saved_usd,
            "water_saved_usd_week": water_saved_usd,
        },
        "assumptions": a.model_dump(),
        "blocks": blocks,
        "schedule": schedule,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

@router.post("/v1/demo/run")
def demo_run(inp: DemoRunIn):
    chosen = []
    ids = set(inp.block_ids or [])
    for b in BLOCKS:
        if b["id"] in ids:
            chosen.append(dict(b))
    if inp.custom_block:
        cb = inp.custom_block
        chosen.append({
            "id": "CUSTOM",
            "name": "Custom block",
            "crop": cb.crop,
            "location": cb.location,
            "acres": cb.acres,
            "baseline_inches_week": cb.baseline_inches_week,
        })
    if not chosen:
        chosen = [dict(BLOCKS[0])]

    result = _compute(chosen, inp.assumptions)

    # Human summary as plain text (frontend should show this, keep raw JSON too)
    t = result["totals"]
    e = result["economics"]
    a = result["assumptions"]
    summary = "\n".join([
        "Executive summary (demo)",
        f"Scenario: {result['scenario'].title()}",
        "",
        f"Across {t['acres']:.2f} acres, baseline is ~{t['baseline_gal_week']:.0f} gal/week.",
        f"Recommended is ~{t['recommended_gal_week']:.0f} gal/week → savings ~{t['savings_gal_week']:.0f} gal/week.",
        f"That’s ~{e['savings_acre_feet_week']:.2f} acre-feet/week avoided.",
        "",
        "Economics (illustrative):",
        f"• Water value saved: ${e['water_saved_usd_week']:.2f}/week (at ${a['water_price_per_acre_foot']:.2f}/acre-foot)",
        f"• Energy saved: {e['energy_saved_kwh_week']:.2f} kWh/week → ${e['energy_saved_usd_week']:.2f}/week (at ${a['energy_price_per_kwh']:.2f}/kWh)",
        "",
        "Transparency:",
        "• Assumptions are explicit + exportable",
        "• Per-block schedule attached",
    ])
    result["readable_summary"] = summary
    return JSONResponse(result)

@router.post("/v1/demo/report")
def demo_report(inp: DemoRunIn):
    # Reuse compute so PDF is consistent with /run
    chosen = []
    ids = set(inp.block_ids or [])
    for b in BLOCKS:
        if b["id"] in ids:
            chosen.append(dict(b))
    if inp.custom_block:
        cb = inp.custom_block
        chosen.append({
            "id": "CUSTOM",
            "name": "Custom block",
            "crop": cb.crop,
            "location": cb.location,
            "acres": cb.acres,
            "baseline_inches_week": cb.baseline_inches_week,
        })
    if not chosen:
        chosen = [dict(BLOCKS[0])]

    result = _compute(chosen, inp.assumptions)
    pages = int(inp.report_pages or 100)
    pages = max(10, min(200, pages))  # safety clamp

    # Charts (optional)
    xs = list(range(1, 13))
    base = [result["totals"]["baseline_gal_week"] * (1 + 0.02*math.sin(i)) for i in xs]
    rec = [result["totals"]["recommended_gal_week"] * (1 + 0.02*math.sin(i+1)) for i in xs]
    png1 = _chart_png("Baseline vs Recommended (12 weeks)", xs, base)
    png2 = _chart_png("Recommended (12 weeks)", xs, rec)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    W, H = letter

    def header(page_no: int, title: str):
        c.setFont("Helvetica-Bold", 14)
        c.drawString(0.75*inch, H - 0.75*inch, "AGRO-AI — Irrigation Intelligence Proof Report")
        c.setFont("Helvetica", 10)
        c.drawRightString(W - 0.75*inch, H - 0.72*inch, f"Page {page_no} / {pages}")
        c.setFont("Helvetica-Bold", 12)
        c.drawString(0.75*inch, H - 1.1*inch, title)
        c.setLineWidth(0.5)
        c.line(0.75*inch, H - 1.2*inch, W - 0.75*inch, H - 1.2*inch)

    # Page 1: cover
    header(1, "Executive cover")
    c.setFont("Helvetica", 11)
    c.drawString(0.75*inch, H - 1.6*inch, f"Scenario: {result['scenario'].title()}")
    c.drawString(0.75*inch, H - 1.85*inch, f"Generated: {result['generated_at']}")
    c.drawString(0.75*inch, H - 2.1*inch, "Purpose: prove the system responds + explain why (assumptions + schedule + economics).")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(0.75*inch, H - 2.8*inch, "Irrigation Intelligence — Decision Proof Package")
    c.setFont("Helvetica", 11)
    c.drawString(0.75*inch, H - 3.15*inch, "This demo report is synthetic but structurally identical to a pilot deliverable.")
    c.showPage()

    # Page 2: summary + KPIs
    header(2, "Executive summary")
    t = result["totals"]; e = result["economics"]; a = result["assumptions"]
    y = H - 1.6*inch
    c.setFont("Helvetica", 11)
    lines = [
        f"Across {t['acres']:.2f} acres, baseline irrigation is ~{t['baseline_gal_week']:.0f} gal/week.",
        f"AGRO-AI recommends ~{t['recommended_gal_week']:.0f} gal/week → savings ~{t['savings_gal_week']:.0f} gal/week.",
        f"That’s ~{e['savings_acre_feet_week']:.2f} acre-feet/week avoided.",
        "",
        f"Illustrative economics (per week): water saved ≈ ${e['water_saved_usd_week']:.2f}, energy saved ≈ ${e['energy_saved_usd_week']:.2f}.",
        "Decision posture: minimize waste without risking yield; respect constraints; keep it auditable.",
    ]
    for ln in lines:
        c.drawString(0.75*inch, y, ln); y -= 0.22*inch

    if png1:
        img = ImageReader(io.BytesIO(png1))
        c.drawImage(img, 0.75*inch, 1.4*inch, width=6.9*inch, height=3.0*inch, preserveAspectRatio=True, mask='auto')
    c.showPage()

    # Page 3: block inventory + assumptions
    header(3, "Block inventory + assumptions")
    y = H - 1.6*inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75*inch, y, "Blocks included"); y -= 0.25*inch
    c.setFont("Helvetica", 10)
    for b in chosen:
        c.drawString(0.9*inch, y, f"• {b['name']} — {b['acres']:.2f} ac — baseline {b['baseline_inches_week']:.2f} in/week — {b['location']}")
        y -= 0.2*inch

    y -= 0.15*inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(0.75*inch, y, "Assumptions (explicit)"); y -= 0.25*inch
    c.setFont("Helvetica", 10)
    for k, v in a.items():
        c.drawString(0.9*inch, y, f"• {k}: {v}")
        y -= 0.2*inch
        if y < 1.2*inch:
            break
    c.showPage()

    # Remaining pages: repeatable “proof” structure
    # We create sections: constraints, schedule, per-block rationale, economics sensitivity, appendix tables.
    rng = random.Random(1337)
    for page in range(4, pages + 1):
        section = (page - 4) % 6

        if section == 0:
            header(page, "Constraints + operating envelope")
            c.setFont("Helvetica", 10)
            y = H - 1.6*inch
            bullets = [
                "Irrigation window: favor early morning to reduce evaporation and peak pumping.",
                "Safety: avoid aggressive cuts during high ET weeks; maintain minimum soil moisture floor.",
                "Operational: keep runtime changes smooth to avoid valve/pump shock.",
                "Audit: every recommendation must tie back to assumptions + baseline + scenario.",
            ]
            for b in bullets:
                c.drawString(0.9*inch, y, f"• {b}"); y -= 0.22*inch

        elif section == 1:
            header(page, "7-day schedule (machine-ready)")
            c.setFont("Helvetica", 10)
            y = H - 1.6*inch
            c.drawString(0.75*inch, y, "Recommended gallons/day (illustrative allocation):"); y -= 0.25*inch
            for row in result["schedule"]:
                c.drawString(0.9*inch, y, f"Day {row['day']}: {row['recommended_gal']:.0f} gal"); y -= 0.2*inch

        elif section == 2:
            header(page, "Per-block rationale (what you’d show an ops lead)")
            c.setFont("Helvetica", 10)
            y = H - 1.6*inch
            for b in chosen:
                cut = a["target_savings_percent"]
                c.drawString(0.75*inch, y, f"{b['name']}: baseline {b['baseline_inches_week']:.2f} in/week → target cut {cut:.0f}% (scenario adjusted).")
                y -= 0.22*inch
                c.drawString(0.95*inch, y, "Reason: remove over-application while maintaining risk buffer for heat spikes & distribution inefficiency.")
                y -= 0.28*inch
                if y < 1.2*inch:
                    break

        elif section == 3:
            header(page, "Economics sensitivity (quick levers)")
            c.setFont("Helvetica", 10)
            y = H - 1.6*inch
            c.drawString(0.75*inch, y, "Weekly savings under alternate assumptions:"); y -= 0.25*inch
            for alt in [15, 25, 35]:
                target_alt = alt / 100.0
                base_g = t["baseline_gal_week"]
                rec_g = base_g * (1 - target_alt)
                sav_g = base_g - rec_g
                sav_af = sav_g / ACRE_FOOT_GAL
                water_usd = sav_af * a["water_price_per_acre_foot"]
                c.drawString(0.9*inch, y, f"Target {alt}% → save ~{sav_g:.0f} gal/week (~{sav_af:.2f} af) → water value ≈ ${water_usd:.2f}/week")
                y -= 0.2*inch

        elif section == 4:
            header(page, "Appendix table: weekly projection (12 weeks)")
            c.setFont("Helvetica", 9)
            y = H - 1.6*inch
            c.drawString(0.75*inch, y, "Week | Baseline (gal) | Recommended (gal) | Savings (gal)"); y -= 0.22*inch
            for w in range(1, 13):
                wobble = 1 + 0.03 * math.sin(w)
                bgal = t["baseline_gal_week"] * wobble
                rgal = t["recommended_gal_week"] * wobble
                sgal = max(0.0, bgal - rgal)
                c.drawString(0.75*inch, y, f"{w:>4} | {bgal:>13.0f} | {rgal:>16.0f} | {sgal:>11.0f}")
                y -= 0.18*inch
                if y < 1.2*inch:
                    break
            if png2:
                img = ImageReader(io.BytesIO(png2))
                c.drawImage(img, 0.75*inch, 1.15*inch, width=6.9*inch, height=2.6*inch, preserveAspectRatio=True, mask='auto')

        else:
            header(page, "Audit notes (why executives trust it)")
            c.setFont("Helvetica", 10)
            y = H - 1.6*inch
            bullets = [
                "All outputs are traceable to: baseline policy + scenario scalar + explicit target savings.",
                "Schedules are machine-ready and can map to controller runtime or setpoints.",
                "This report format is the same structure used in a paid pilot deliverable.",
                "In a real pilot: ET0/weather, soil telemetry, controller logs, and constraints replace synthetic inputs.",
            ]
            for b in bullets:
                c.drawString(0.9*inch, y, f"• {b}"); y -= 0.22*inch

        c.showPage()

    c.save()
    pdf = buf.getvalue()

    headers = {
        "Content-Type": "application/pdf",
        "Content-Disposition": "attachment; filename=AGRO-AI_Demo_Report.pdf",
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return Response(content=pdf, headers=headers, media_type="application/pdf")
