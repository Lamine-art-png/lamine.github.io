"""Ask AGRO-AI memory and artifact routes."""
from __future__ import annotations

import base64
import io
import re
from datetime import datetime
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from reportlab.lib.utils import ImageReader
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import require_current_tenant_id
from app.db.base import get_db
from app.models.saas import Conversation, ConversationMessage, User

router = APIRouter(prefix="/intelligence/chat", tags=["intelligence"])

BRAND_GREEN = "#0D2B1E"
BRAND_LIME = "#A7E03A"
BRAND_MUTED = "#667467"
BRAND_LINE = "#D7DFD8"
BRAND_BG = "#F6F8F4"

# Embedded AGRO-AI mark, derived from the supplied AGRO-AI logo. Keeping it embedded
# makes report generation deterministic in Render/production without relying on a
# local static asset copy step.
BRAND_LOGO_PNG_BASE64 = """
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
""".strip()


class PersistMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    output: str | None = Field(default=None, max_length=50000)


class ReportPdfRequest(BaseModel):
    title: str | None = None
    question: str = "AGRO-AI report"
    answer: str = ""
    uploaded_evidence: list[dict[str, Any]] = Field(default_factory=list)


class ReportEmailRequest(ReportPdfRequest):
    to_email: str | None = None


def _conversation_for(db: Session, tenant_id: str, conversation_id: str) -> Conversation:
    row = db.get(Conversation, conversation_id)
    if not row or row.organization_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return row


@router.post("/conversations/{conversation_id}/messages")
def persist_message(
    conversation_id: str,
    payload: PersistMessageRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    conversation = _conversation_for(db, tenant_id, conversation_id)
    user_message = ConversationMessage(
        conversation_id=conversation.id,
        organization_id=tenant_id,
        user_id=user.id,
        role="user",
        content=payload.content,
    )
    db.add(user_message)
    if payload.output:
        assistant_message = ConversationMessage(
            conversation_id=conversation.id,
            organization_id=tenant_id,
            user_id=None,
            role="assistant",
            content=payload.output,
            artifacts_json=[],
            citations_json=[],
            missing_data_json=[],
            recommended_actions_json=[],
        )
        db.add(assistant_message)
    conversation.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "conversation_id": conversation.id}


def _plain(value: Any, limit: int = 800) -> str:
    return str(value or "").replace("\n", " ").strip()[:limit]


def _pdf_filename(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "agroai-operating-report"
    return f"{slug[:80]}.pdf"


def _safe_paragraph(value: Any) -> str:
    return escape(str(value or "")).replace("\n", "<br/>")


def _rows_count(item: dict[str, Any]) -> int:
    value = item.get("rows_parsed")
    if value is None:
        value = item.get("rows")
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _upload_line(item: dict[str, Any]) -> str:
    filename = _plain(item.get("filename") or item.get("name"), 160)
    file_type = _plain(item.get("file_type") or item.get("source_type") or item.get("content_type"), 80)
    rows = item.get("rows_parsed") or item.get("rows")
    columns = item.get("columns") or []
    warnings = item.get("warnings") or []
    bits = [filename, file_type]
    if rows is not None:
        bits.append(f"rows={rows}")
    if columns:
        bits.append("columns=" + ", ".join(str(col) for col in columns[:12]))
    if warnings:
        bits.append("warnings=" + "; ".join(str(warning) for warning in warnings[:3]))
    return " - ".join(bit for bit in bits if bit)


def _total_rows(items: list[dict[str, Any]]) -> int:
    return sum(_rows_count(item) for item in items or [])


def _coverage_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No imported evidence attached"
    if any(item.get("warnings") for item in items):
        return "Imported evidence with parsing warnings"
    return "Imported evidence attached"


def _brand_logo_reader() -> ImageReader | None:
    try:
        return ImageReader(io.BytesIO(base64.b64decode(BRAND_LOGO_PNG_BASE64)))
    except Exception:
        return None


def _draw_brand_header(canvas: Any, doc: Any) -> None:
    from reportlab.lib import colors

    canvas.saveState()
    width, height = doc.pagesize
    canvas.setFillColor(colors.HexColor(BRAND_GREEN))
    canvas.rect(0, height - 42, width, 42, fill=1, stroke=0)

    logo = _brand_logo_reader()
    if logo:
        canvas.drawImage(
            logo,
            42,
            height - 35,
            width=24,
            height=25,
            preserveAspectRatio=True,
            mask="auto",
        )
        text_x = 72
    else:
        text_x = 42

    canvas.setFillColorRGB(1, 1, 1)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(text_x, height - 26, "AGRO-AI")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(width - 42, height - 25, "Operating Evidence Report")
    canvas.setStrokeColor(colors.HexColor(BRAND_LIME))
    canvas.setLineWidth(1)
    canvas.line(42, 34, width - 42, 34)
    canvas.setFillColor(colors.HexColor(BRAND_MUTED))
    canvas.setFont("Helvetica", 7)
    canvas.drawString(42, 22, "Generated by AGRO-AI Report Factory v1")
    canvas.drawRightString(width - 42, 22, f"Page {doc.page}")
    canvas.restoreState()


def _section(story: list[Any], styles: Any, title: str, body: str | None = None) -> None:
    from reportlab.platypus import Paragraph, Spacer

    story.append(Spacer(1, 8))
    story.append(Paragraph(_safe_paragraph(title), styles["Heading2"]))
    if body:
        story.append(Paragraph(_safe_paragraph(body), styles["BodyText"]))
        story.append(Spacer(1, 6))


def _evidence_table(items: list[dict[str, Any]]) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    table_data = [["Evidence source", "Type", "Rows", "Controls / notes"]]
    if not items:
        table_data.append(["No uploaded file", "—", "—", "Report should not be treated as evidence-backed until source data is attached."])
    for item in items[:14]:
        columns = item.get("columns") or []
        warnings = item.get("warnings") or []
        controls = ", ".join(str(column) for column in columns[:8])
        if warnings:
            controls = (controls + " | " if controls else "") + "; ".join(str(warning) for warning in warnings[:2])
        table_data.append([
            _plain(item.get("filename") or item.get("name"), 36),
            _plain(item.get("file_type") or item.get("source_type") or item.get("content_type"), 24),
            str(_rows_count(item)) if item.get("rows_parsed") is not None or item.get("rows") is not None else "—",
            _plain(controls or "Source received; field mapping/reviewer validation required.", 78),
        ])
    table = Table(table_data, colWidths=[150, 88, 45, 235], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND_GREEN)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(BRAND_LINE)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#FFFFFF")),
    ]))
    return table


def build_report_pdf_bytes(payload: ReportPdfRequest, tenant_id: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    title = payload.title or "AGRO-AI Operating Report"
    generated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    evidence_count = len(payload.uploaded_evidence)
    row_count = _total_rows(payload.uploaded_evidence)
    coverage = _coverage_status(payload.uploaded_evidence)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        title=title,
        rightMargin=42,
        leftMargin=42,
        topMargin=62,
        bottomMargin=54,
    )
    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor(BRAND_GREEN)
    styles["Heading2"].textColor = colors.HexColor(BRAND_GREEN)
    styles["Heading3"].textColor = colors.HexColor(BRAND_GREEN)

    story: list[Any] = [
        Paragraph(_safe_paragraph(title), styles["Title"]),
        Spacer(1, 8),
        Paragraph("Compliance-grade operating intelligence draft", styles["Heading3"]),
        Paragraph(f"Generated: {generated_at}", styles["Normal"]),
        Paragraph(f"Workspace account: {escape(tenant_id)}", styles["Normal"]),
        Spacer(1, 12),
    ]

    summary_table = Table([
        ["Review status", "Human review required before external reliance"],
        ["Evidence coverage", coverage],
        ["Imported files", str(evidence_count)],
        ["Parsed evidence rows", str(row_count)],
        ["Assurance level", "Advisory operating draft — not certification or regulatory approval"],
    ], colWidths=[130, 390])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor(BRAND_BG)),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(BRAND_GREEN)),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(BRAND_LINE)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 14))

    _section(story, styles, "1. Executive summary")
    report_blocks = [block.strip() for block in (payload.answer or "").split("\n\n") if block.strip()]
    for block in report_blocks or ["No analysis body was provided by AGRO-AI for this report request."]:
        story.append(Paragraph(_safe_paragraph(block), styles["BodyText"]))
        story.append(Spacer(1, 7))

    _section(story, styles, "2. Basis of preparation", _plain(payload.question, 2400))

    _section(story, styles, "3. Evidence register")
    story.append(_evidence_table(payload.uploaded_evidence))
    story.append(Spacer(1, 10))

    _section(story, styles, "4. Compliance and control considerations")
    controls = [
        "Source provenance should remain attached to every recommendation, exception, and exported report.",
        "Field/block mapping, timestamps, units, and water-volume calculations require reviewer validation before external use.",
        "If telemetry, ET, controller, or compliance records are missing, the report should be treated as a readiness draft rather than a final decision record.",
        "Any live integration claim must be supported by a configured connection and recent synced records.",
    ]
    for item in controls:
        story.append(Paragraph(f"• {_safe_paragraph(item)}", styles["BodyText"]))
    story.append(Spacer(1, 8))

    _section(story, styles, "5. Risks, assumptions, and limitations")
    limits = [
        "This report is generated from supplied workspace context and uploaded evidence metadata.",
        "AGRO-AI must not be used to certify compliance, water rights, acreage, yield impact, or cost savings without human review and source validation.",
        "Calculations and charts should be considered preliminary unless the underlying rows include consistent units, dates, field identifiers, and measurement methodology.",
    ]
    for item in limits:
        story.append(Paragraph(f"• {_safe_paragraph(item)}", styles["BodyText"]))
    story.append(Spacer(1, 8))

    _section(story, styles, "6. Management action plan")
    actions = [
        "Confirm source file ownership and operating period.",
        "Validate field/block mapping and unit normalization.",
        "Resolve parser warnings and missing evidence before sending to outside stakeholders.",
        "Approve or reject each recommendation in the workspace decision log.",
    ]
    for index, item in enumerate(actions, start=1):
        story.append(Paragraph(f"{index}. {_safe_paragraph(item)}", styles["BodyText"]))

    if payload.uploaded_evidence:
        _section(story, styles, "Appendix A — imported evidence notes")
        for item in payload.uploaded_evidence[:20]:
            story.append(Paragraph(_safe_paragraph(_upload_line(item)), styles["BodyText"]))
            story.append(Spacer(1, 4))

    doc.build(story, onFirstPage=_draw_brand_header, onLaterPages=_draw_brand_header)
    return buffer.getvalue()


@router.post("/report-pdf")
def report_pdf(
    payload: ReportPdfRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    title = payload.title or "AGRO-AI Operating Report"
    buffer = io.BytesIO(build_report_pdf_bytes(payload, tenant_id))
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_pdf_filename(title)}"'},
    )


@router.post("/report-email")
def report_email(
    payload: ReportEmailRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from app.services.email_delivery import delivery_status, send_email

    recipient = (payload.to_email or user.email or "").strip().lower()
    if not recipient or "@" not in recipient:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A valid recipient email is required")

    title = payload.title or "AGRO-AI Operating Report"
    filename = _pdf_filename(title)
    pdf_content = build_report_pdf_bytes(payload, tenant_id)
    delivery = delivery_status()
    result = send_email(
        to_email=recipient,
        subject=f"{title} — AGRO-AI report",
        text_body=(
            "Attached is the AGRO-AI operating report requested from your workspace.\n\n"
            "This is a generated operating draft. A reviewer should confirm evidence, field mapping, timestamps, and telemetry claims before external use."
        ),
        html_body=(
            "<p>Attached is the AGRO-AI operating report requested from your workspace.</p>"
            "<p><strong>Review note:</strong> This is a generated operating draft. Confirm evidence, field mapping, timestamps, and telemetry claims before external use.</p>"
        ),
        attachments=[{"filename": filename, "content_type": "application/pdf", "data": pdf_content}],
    )
    return {
        "status": "sent" if result.get("ok") else "not_sent",
        "recipient": recipient,
        "filename": filename,
        "email_provider": result.get("provider"),
        "delivery": result,
        "delivery_configured": delivery.get("configured"),
    }
