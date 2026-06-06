"""Report generation for the FCGMA Water Intelligence Copilot.

Generates:
  - Executive PDF (reportlab)
  - Detailed CSV
  - Exceptions CSV
  - Audit JSON
  - Data-lineage manifest JSON
  - Downloadable ZIP bundle

All reports carry a prominent disclaimer identifying demonstration data.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any

from .ledger import list_records, list_exceptions, ledger_stats, CALCULATION_VERSION
from .rule_pack import PACK_METADATA, DISCLAIMER as RULE_DISCLAIMER

REPORT_DISCLAIMER = (
    "ILLUSTRATIVE WORKSPACE — Not an official Fox Canyon Groundwater Management Agency "
    "reporting submission. All records are demonstration scenarios. No authorized Fox Canyon "
    "extraction data is included. This report must not be submitted to any regulatory body."
)

REPORT_FOOTER_NOTE = (
    "Illustrative workspace | AGRO-AI Applied Water Intelligence | "
    "All figures are demonstration scenarios — no authorized Fox Canyon data"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_dt(iso: str | None) -> str:
    if not iso:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso[:16] if iso else "N/A"


# ─────────────────────────────────────────────
# In-memory report store
# ─────────────────────────────────────────────
_REPORTS: dict[str, dict[str, Any]] = {}


def _store_report(report: dict[str, Any]) -> None:
    _REPORTS[report["report_id"]] = report


def get_report_meta(report_id: str) -> dict[str, Any] | None:
    return _REPORTS.get(report_id)


def list_reports() -> list[dict[str, Any]]:
    """Return all generated reports (public metadata only), newest first."""
    return [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in sorted(_REPORTS.values(), key=lambda r: r["generated_at"], reverse=True)
    ]


# ─────────────────────────────────────────────
# PDF generation
# ─────────────────────────────────────────────

def _generate_pdf(stats: dict[str, Any], records: list[dict[str, Any]], exceptions: list[dict[str, Any]]) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    FOREST = colors.HexColor("#285446")
    GRAPHITE = colors.HexColor("#222826")
    MUTED = colors.HexColor("#66736e")
    DANGER = colors.HexColor("#9f3529")
    STONE = colors.HexColor("#f6f5f1")

    def style(name: str, **kwargs) -> ParagraphStyle:
        base = styles["Normal"]
        return ParagraphStyle(name, parent=base, **kwargs)

    H1 = style("H1", fontSize=22, textColor=FOREST, spaceAfter=8, fontName="Helvetica-Bold")
    H2 = style("H2", fontSize=14, textColor=GRAPHITE, spaceAfter=6, fontName="Helvetica-Bold")
    H3 = style("H3", fontSize=11, textColor=FOREST, spaceAfter=4, fontName="Helvetica-Bold")
    BODY = style("BODY", fontSize=9, textColor=GRAPHITE, spaceAfter=4, leading=14)
    DISCLAIMER_S = style("DISCLAIMER", fontSize=8, textColor=DANGER, spaceAfter=4, leading=12,
                         backColor=colors.HexColor("#fff8f8"), borderColor=DANGER, borderWidth=0.5)
    MUTED_S = style("MUTED", fontSize=8, textColor=MUTED, leading=11)

    story = []
    generated_at = _now()
    open_excs = [e for e in exceptions if e.get("status") != "resolved"]
    requires_attention = [r for r in records if r["review_status"] == "requires_attention"]
    ready = [r for r in records if r["review_status"] in ("ready_for_export", "reviewer_approved")]

    # ── PAGE 1: Executive Summary ──
    story.append(Paragraph("AGRO-AI Applied Water Intelligence", H1))
    story.append(Paragraph("Reporting Readiness Brief — Fox Canyon Groundwater Management Agency", style("SUB", fontSize=12, textColor=MUTED, spaceAfter=4)))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Reporting Period: 2026-Q1 | Generated: {_format_dt(generated_at)}", MUTED_S))
    story.append(Spacer(1, 12))

    # Disclaimer box
    story.append(Paragraph(REPORT_DISCLAIMER, DISCLAIMER_S))
    story.append(Spacer(1, 12))

    # Source status table
    story.append(Paragraph("Source Status", H2))
    src_data = [
        ["Provider", "Status", "Records"],
        ["WiseConn Sanitized Replay", "Connected (demo)", str(sum(1 for r in records if r["provider"] == "wiseconn_sanitized_replay"))],
        ["FCGMA Generic AMI CSV", "Demo import", str(sum(1 for r in records if r["provider"] == "fcgma_generic_ami_csv"))],
        ["CIMIS Live Weather", "Pending CIMIS_APP_KEY", "0"],
        ["Ranch Systems", "Disabled — pending authorization", "0"],
    ]
    src_table = Table(src_data, colWidths=[3.2 * inch, 2.5 * inch, 1.0 * inch])
    src_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), FOREST),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [STONE, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ded9ce")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(src_table)
    story.append(Spacer(1, 12))

    # Key metrics
    story.append(Paragraph("Records Summary", H2))
    met_data = [
        ["Metric", "Value"],
        ["Total records processed", str(stats["total_records"])],
        ["Records requiring attention", str(stats["requires_attention"])],
        ["Records ready for export", str(stats["ready_for_export"])],
        ["Open exceptions", str(len(open_excs))],
        ["Supported extraction (AF — ready records)", f"{stats['supported_extraction_af']:.4f}"],
        ["Provisional extraction (AF)", f"{stats['provisional_af']:.4f}"],
        ["Injected scenario records", str(stats["injected_scenario_records"])],
    ]
    met_table = Table(met_data, colWidths=[4.0 * inch, 2.5 * inch])
    met_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), FOREST),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [STONE, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ded9ce")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(met_table)
    story.append(Spacer(1, 12))

    # Executive intelligence narrative
    story.append(Paragraph("Executive Intelligence Summary", H2))
    from .copilot import get_executive_summary
    exec_summary = get_executive_summary()
    story.append(Paragraph(exec_summary.get("narrative", "No narrative available."), BODY))
    story.append(Spacer(1, 12))

    # Reporting-readiness summary
    readiness = "NOT READY" if open_excs else "READY FOR REVIEW"
    story.append(Paragraph(f"Reporting Readiness: {readiness}", H2))
    if open_excs:
        story.append(Paragraph(
            f"{len(open_excs)} open exception(s) must be resolved before this dataset can be included "
            "in a reporting-ready export.", BODY
        ))

    story.append(PageBreak())

    # ── PAGE 2: Priority Action Queue ──
    story.append(Paragraph("Priority Action Queue", H1))
    story.append(Spacer(1, 8))

    if requires_attention:
        attn_data = [["Record ID", "Well", "Evidence Class", "Open Exceptions", "Status"]]
        for r in requires_attention[:20]:
            open_e = [e for e in r.get("exceptions", []) if e.get("status") != "resolved"]
            exc_summary = "; ".join(e["exception_type"].replace("_", " ") for e in open_e[:2])
            attn_data.append([
                r["id"][:16] + "…",
                r["well_id"],
                r["evidence_class"].replace("_", " ")[:28],
                exc_summary[:40] if exc_summary else "—",
                r["review_status"].replace("_", " "),
            ])
        attn_table = Table(attn_data, colWidths=[1.5 * inch, 1.2 * inch, 1.8 * inch, 2.0 * inch, 1.2 * inch])
        attn_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), FOREST),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#fff8f8"), colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ded9ce")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(attn_table)
    else:
        story.append(Paragraph("No records currently require attention.", BODY))

    story.append(PageBreak())

    # ── PAGE 3: Provider Health and Assumptions ──
    story.append(Paragraph("Provider Health & Unvalidated Assumptions", H1))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Data Quality Summary", H2))
    dq_data = [
        ["Evidence Class", "Records"],
    ]
    for ec, count in stats.get("evidence_class_breakdown", {}).items():
        dq_data.append([ec.replace("_", " "), str(count)])
    dq_table = Table(dq_data, colWidths=[4.5 * inch, 1.5 * inch])
    dq_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), FOREST),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [STONE, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ded9ce")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(dq_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Unvalidated Assumptions", H2))
    story.append(Paragraph(
        "The following assumptions require Fox Canyon Groundwater Management Agency validation "
        "before this dataset can be used for official reporting:", BODY
    ))
    assumptions = [
        "Applied-water model (DEMO RULESET v0.1) requires Fox Canyon validation.",
        "Backup estimation methodology requires FCGMA pre-approval.",
        "CombCode assignments for demonstration wells are illustrative.",
        "Ranch Systems adapter is pending official schema and API authorization.",
    ]
    for a in assumptions:
        story.append(Paragraph(f"• {a}", BODY))

    story.append(PageBreak())

    # ── APPENDIX ──
    story.append(Paragraph("Appendix: Rule Versions & Audit References", H1))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Rule Pack", H2))
    story.append(Paragraph(f"Pack ID: {PACK_METADATA['pack_id']}", BODY))
    story.append(Paragraph(f"Pack Version: {PACK_METADATA['pack_version']}", BODY))
    story.append(Paragraph(f"Status: {PACK_METADATA['validation_status']}", BODY))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Source URLs:", H3))
    for url in PACK_METADATA["sources"]:
        story.append(Paragraph(f"• {url}", MUTED_S))

    story.append(Spacer(1, 12))
    story.append(Paragraph("Calculation Version", H2))
    story.append(Paragraph(f"{CALCULATION_VERSION}", BODY))

    story.append(Spacer(1, 12))
    story.append(Paragraph("Source-Lineage Summary", H2))
    story.append(Paragraph(
        "All records in this report are demonstration scenarios. No authorized Fox Canyon "
        "extraction data is included. Records are sourced from:", BODY
    ))
    story.append(Paragraph("• fcgma_generic_ami_csv — Demo AMI import", BODY))
    story.append(Paragraph("• wiseconn_sanitized_replay — Anonymized WiseConn replay", BODY))
    story.append(Paragraph("• injected_demo_scenario — Controlled scenario injection", BODY))

    story.append(Spacer(1, 12))
    story.append(Paragraph(RULE_DISCLAIMER, DISCLAIMER_S))

    story.append(Spacer(1, 12))
    story.append(Paragraph(REPORT_FOOTER_NOTE, MUTED_S))

    doc.build(story)
    return buf.getvalue()


# ─────────────────────────────────────────────
# CSV generation
# ─────────────────────────────────────────────

def _generate_records_csv(records: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    fieldnames = [
        "id", "evidence_class", "provider", "sanitized_source_hash",
        "event_timestamp", "reporting_period", "well_id", "meter_id",
        "combcode", "parcel_ids", "cumulative_volume", "interval_volume",
        "unit", "unit_original", "multiplier", "pump_status",
        "source_quality", "review_status", "scenario_injected", "scenario_label",
        "calculation_version", "attribution_provisional", "provisional_applied_water_af",
        "exception_count",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        row = {k: r.get(k, "") for k in fieldnames}
        row["parcel_ids"] = "|".join(r.get("parcel_ids", []))
        row["exception_count"] = len(r.get("exceptions", []))
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def _generate_exceptions_csv(exceptions: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    fieldnames = ["id", "record_id", "exception_type", "severity", "detail", "rule_id", "status", "created_at"]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for e in exceptions:
        writer.writerow({k: e.get(k, "") for k in fieldnames})
    return buf.getvalue().encode("utf-8")


# ─────────────────────────────────────────────
# Report orchestration
# ─────────────────────────────────────────────

def generate_report(report_type: str = "full") -> dict[str, Any]:
    """Generate a complete report bundle."""
    report_id = f"rpt-{uuid.uuid4().hex[:12]}"
    generated_at = _now()

    records = list_records()
    exceptions = list_exceptions()
    stats = ledger_stats()

    # Generate all artifacts
    pdf_bytes = _generate_pdf(stats, records, exceptions)
    records_csv = _generate_records_csv(records)
    exceptions_csv = _generate_exceptions_csv(exceptions)

    audit_json = json.dumps({
        "report_id": report_id,
        "generated_at": generated_at,
        "calculation_version": CALCULATION_VERSION,
        "record_count": len(records),
        "exception_count": len(exceptions),
        "stats": stats,
        "disclaimer": REPORT_DISCLAIMER,
    }, indent=2).encode("utf-8")

    lineage_manifest = json.dumps({
        "report_id": report_id,
        "generated_at": generated_at,
        "records": [
            {
                "id": r["id"],
                "provider": r["provider"],
                "evidence_class": r["evidence_class"],
                "sanitized_source_hash": r["sanitized_source_hash"],
                "scenario_injected": r["scenario_injected"],
                "source_lineage": r.get("source_lineage", {}),
            }
            for r in records
        ],
        "disclaimer": REPORT_DISCLAIMER,
    }, indent=2).encode("utf-8")

    # Build ZIP
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{report_id}_executive_report.pdf", pdf_bytes)
        zf.writestr(f"{report_id}_records.csv", records_csv)
        zf.writestr(f"{report_id}_exceptions.csv", exceptions_csv)
        zf.writestr(f"{report_id}_audit.json", audit_json)
        zf.writestr(f"{report_id}_lineage_manifest.json", lineage_manifest)
        zf.writestr("README.txt", (
            f"AGRO-AI Applied Water Intelligence\n"
            f"Reporting Readiness Brief — Fox Canyon Groundwater Management Agency\n"
            f"Report ID: {report_id}\n"
            f"Generated: {generated_at}\n\n"
            f"{REPORT_DISCLAIMER}\n"
        ).encode("utf-8"))

    meta = {
        "report_id": report_id,
        "generated_at": generated_at,
        "record_count": len(records),
        "exception_count": len(exceptions),
        "stats": stats,
        "artifacts": [
            {"name": "executive_pdf", "content_type": "application/pdf", "filename": f"{report_id}_executive_report.pdf"},
            {"name": "records_csv", "content_type": "text/csv", "filename": f"{report_id}_records.csv"},
            {"name": "exceptions_csv", "content_type": "text/csv", "filename": f"{report_id}_exceptions.csv"},
            {"name": "audit_json", "content_type": "application/json", "filename": f"{report_id}_audit.json"},
            {"name": "lineage_manifest", "content_type": "application/json", "filename": f"{report_id}_lineage_manifest.json"},
        ],
        "disclaimer": REPORT_DISCLAIMER,
    }

    # Store artifacts in memory for retrieval
    _REPORTS[report_id] = {
        **meta,
        "_pdf": pdf_bytes,
        "_records_csv": records_csv,
        "_exceptions_csv": exceptions_csv,
        "_audit_json": audit_json,
        "_lineage_json": lineage_manifest,
        "_zip": zip_buf.getvalue(),
    }

    return meta


def get_report_artifact(report_id: str, artifact: str) -> tuple[bytes, str] | None:
    """Return (bytes, content_type) for a specific artifact, or None if not found."""
    report = _REPORTS.get(report_id)
    if not report:
        return None
    artifact_map = {
        "pdf": ("_pdf", "application/pdf"),
        "records_csv": ("_records_csv", "text/csv"),
        "exceptions_csv": ("_exceptions_csv", "text/csv"),
        "audit": ("_audit_json", "application/json"),
        "lineage": ("_lineage_json", "application/json"),
        "bundle": ("_zip", "application/zip"),
    }
    key, ct = artifact_map.get(artifact, (None, None))
    if not key:
        return None
    data = report.get(key)
    return (data, ct) if data else None
