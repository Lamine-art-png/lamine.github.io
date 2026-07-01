"""Ask AGRO-AI memory and artifact routes."""
from __future__ import annotations

import io
import re
from datetime import datetime
from html import escape
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
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


def _draw_brand_header(canvas: Any, doc: Any) -> None:
    from reportlab.lib import colors

    canvas.saveState()
    width, height = doc.pagesize
    canvas.setFillColor(colors.HexColor(BRAND_GREEN))
    canvas.rect(0, height - 38, width, 38, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor(BRAND_LIME))
    canvas.circle(42, height - 19, 12, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor(BRAND_GREEN))
    canvas.circle(47, height - 19, 8, fill=1, stroke=0)
    canvas.setFillColorRGB(1, 1, 1)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(62, height - 24, "AGRO-AI")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(width - 42, height - 23, "Operating Evidence Report")
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
