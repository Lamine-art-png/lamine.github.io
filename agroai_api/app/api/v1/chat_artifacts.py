"""Ask AGRO-AI memory and artifact routes."""
from __future__ import annotations

import io
from datetime import datetime
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


class PersistMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    output: str | None = Field(default=None, max_length=50000)


class ReportPdfRequest(BaseModel):
    title: str | None = None
    question: str = "AGRO-AI report"
    answer: str = ""
    uploaded_evidence: list[dict[str, Any]] = Field(default_factory=list)


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


def _upload_line(item: dict[str, Any]) -> str:
    filename = _plain(item.get("filename") or item.get("name"), 160)
    file_type = _plain(item.get("file_type") or item.get("source_type") or item.get("content_type"), 80)
    rows = item.get("rows_parsed") or item.get("rows")
    columns = item.get("columns") or []
    bits = [filename, file_type]
    if rows is not None:
        bits.append(f"rows={rows}")
    if columns:
        bits.append("columns=" + ", ".join(str(col) for col in columns[:12]))
    return " - ".join(bit for bit in bits if bit)


@router.post("/report-pdf")
def report_pdf(
    payload: ReportPdfRequest,
    tenant_id: str = Depends(require_current_tenant_id),
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    title = payload.title or "AGRO-AI Operating Report"
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title=title)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    story.append(Paragraph(f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z", styles["Normal"]))
    story.append(Paragraph(f"Workspace account: {tenant_id}", styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Request", styles["Heading2"]))
    story.append(Paragraph(_plain(payload.question, 1600), styles["BodyText"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph("AGRO-AI analysis", styles["Heading2"]))
    report_text = payload.answer or "No report body was provided."
    for block in report_text.split("\n\n"):
        safe = block.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        story.append(Paragraph(safe, styles["BodyText"]))
        story.append(Spacer(1, 8))
    if payload.uploaded_evidence:
        story.append(Paragraph("Imported files", styles["Heading2"]))
        for item in payload.uploaded_evidence[:10]:
            story.append(Paragraph(_upload_line(item), styles["BodyText"]))
            story.append(Spacer(1, 4))
    doc.build(story)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=agroai-operating-report.pdf"},
    )
