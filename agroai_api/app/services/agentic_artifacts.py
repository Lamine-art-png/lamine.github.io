from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.api.v1.chat_artifacts import (
    BRAND_GREEN,
    BRAND_LIME,
    BRAND_LOGO_PNG_BASE64,
    BRAND_MUTED,
    ReportPdfRequest,
    build_report_pdf_bytes,
)
from app.models.operational_records import GeneratedArtifact
from app.services.artifact_intelligence import create_artifact_plan
from app.services.object_storage import get_object_store, object_storage_configured


_ARTIFACT_SCOPE = "agentic-artifacts"
_FORMATS = {
    "pdf": ("application/pdf", ".pdf"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}


def _plain(value: Any, limit: int = 12000) -> str:
    return str(value or "").strip()[:limit]


def _filename(title: str, extension: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower() or "agro-ai-artifact"
    return f"{slug[:80]}{extension}"


def _blocks(text: str, *, max_blocks: int = 10) -> list[str]:
    raw = _plain(text, 50000)
    chunks = [part.strip() for part in re.split(r"\n\s*\n|(?<=\.)\s+(?=[A-Z])", raw) if part.strip()]
    return chunks[:max_blocks] or ["No analysis content was supplied."]


def _evidence_lines(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in (items or [])[:20]:
        name = str(item.get("filename") or item.get("name") or item.get("source_type") or "Workspace source")
        rows = item.get("rows_parsed") or item.get("rows")
        bits = [name]
        if rows is not None:
            bits.append(f"{rows} rows")
        warnings = item.get("warnings") or []
        if warnings:
            bits.append(f"{len(warnings)} warning(s)")
        lines.append(" · ".join(bits))
    return lines


def _plan_sections(plan: dict[str, Any], answer: str) -> list[dict[str, Any]]:
    sections = [item for item in (plan.get("sections") or []) if isinstance(item, dict)]
    if sections:
        return sections[:10]
    blocks = _blocks(answer, max_blocks=8)
    return [
        {
            "heading": "Executive summary",
            "summary": blocks[0] if blocks else "",
            "paragraphs": blocks[:3],
            "bullets": [],
            "source_notes": [],
        },
        {
            "heading": "Operating analysis",
            "summary": "",
            "paragraphs": blocks[3:7],
            "bullets": [],
            "source_notes": [],
        },
        {
            "heading": "Recommended next actions",
            "summary": "",
            "paragraphs": [],
            "bullets": blocks[-4:],
            "source_notes": [],
        },
    ]


def _docx_bytes(
    *,
    title: str,
    question: str,
    answer: str,
    evidence: list[dict[str, Any]],
    plan: dict[str, Any],
) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_SECTION
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.68)
    section.bottom_margin = Inches(0.68)
    section.left_margin = Inches(0.78)
    section.right_margin = Inches(0.78)

    header = section.header.paragraphs[0]
    header.style = doc.styles["Normal"]
    try:
        logo_run = header.add_run()
        logo_run.add_picture(io.BytesIO(base64.b64decode(BRAND_LOGO_PNG_BASE64)), width=Inches(0.32))
        brand_run = header.add_run("  AGRO-AI")
    except Exception:
        brand_run = header.add_run("AGRO-AI")
    brand_run.bold = True
    brand_run.font.name = "Glacial Indifference"
    brand_run.font.size = Pt(9.5)
    brand_run.font.color.rgb = RGBColor(13, 43, 30)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(str(plan.get("title") or title))
    run.bold = True
    run.font.name = "Glacial Indifference"
    run.font.size = Pt(28)
    run.font.color.rgb = RGBColor(13, 43, 30)

    subtitle = str(plan.get("subtitle") or "AGRO-AI workspace intelligence").strip()
    sub = doc.add_paragraph(subtitle)
    sub.runs[0].font.name = "Glacial Indifference"
    sub.runs[0].font.size = Pt(10)
    sub.runs[0].font.color.rgb = RGBColor(102, 116, 103)

    summary = str(plan.get("executive_summary") or "").strip()
    if summary:
        callout = doc.add_paragraph()
        callout.paragraph_format.space_before = Pt(8)
        callout.paragraph_format.space_after = Pt(14)
        r = callout.add_run(summary)
        r.font.name = "Arial"
        r.font.size = Pt(12)
        r.bold = True
        r.font.color.rgb = RGBColor(23, 61, 43)

    for item in _plan_sections(plan, answer):
        heading = str(item.get("heading") or "").strip()
        if heading:
            doc.add_heading(heading, level=1)
        summary_text = str(item.get("summary") or "").strip()
        if summary_text:
            p = doc.add_paragraph(summary_text)
            p.runs[0].bold = True
        for paragraph in item.get("paragraphs") or []:
            value = str(paragraph or "").strip()
            if value:
                doc.add_paragraph(value)
        for bullet in item.get("bullets") or []:
            value = str(bullet or "").strip()
            if value:
                doc.add_paragraph(value, style="List Bullet")
        source_notes = [str(value).strip() for value in (item.get("source_notes") or []) if str(value).strip()]
        if source_notes:
            p = doc.add_paragraph("Sources: " + " · ".join(source_notes[:5]))
            p.runs[0].font.size = Pt(8.5)
            p.runs[0].font.color.rgb = RGBColor(102, 116, 103)

    evidence_lines = _evidence_lines(evidence)
    if evidence_lines:
        doc.add_heading("Workspace evidence", level=1)
        for line in evidence_lines[:12]:
            doc.add_paragraph(line, style="List Bullet")

    doc.add_paragraph()
    note = doc.add_paragraph(
        "Generated from authenticated AGRO-AI workspace context. "
        "Evidence gaps, source provenance, and approval boundaries remain authoritative."
    )
    note.runs[0].font.size = Pt(8.5)
    note.runs[0].font.color.rgb = RGBColor(102, 116, 103)

    styles = doc.styles
    for style_name in ["Normal", "Title", "Heading 1", "Heading 2"]:
        style = styles[style_name]
        style.font.name = "Arial"
    styles["Normal"].font.size = Pt(10.5)
    styles["Heading 1"].font.name = "Glacial Indifference"
    styles["Heading 1"].font.color.rgb = RGBColor(13, 43, 30)
    styles["Heading 1"].font.size = Pt(15)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _pptx_bytes(
    *,
    title: str,
    question: str,
    answer: str,
    evidence: list[dict[str, Any]],
    plan: dict[str, Any],
) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(13.333333)
    prs.slide_height = Inches(7.5)

    green = RGBColor(13, 43, 30)
    green2 = RGBColor(31, 94, 66)
    lime = RGBColor(194, 232, 79)
    offwhite = RGBColor(247, 247, 242)
    surface = RGBColor(255, 255, 252)
    muted = RGBColor(101, 119, 107)
    text = RGBColor(19, 43, 31)
    soft = RGBColor(226, 234, 227)
    white = RGBColor(255, 255, 255)
    FONT = "Glacial Indifference"
    BODY_FONT = "Arial"
    logo_bytes = base64.b64decode(BRAND_LOGO_PNG_BASE64)

    def add_text(slide, value, left, top, width, height, *, size=18, bold=False, color=text, font=BODY_FONT, align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP):
        box = slide.shapes.add_textbox(left, top, width, height)
        frame = box.text_frame
        frame.clear()
        frame.word_wrap = True
        frame.margin_left = 0
        frame.margin_right = 0
        frame.margin_top = 0
        frame.margin_bottom = 0
        frame.vertical_anchor = valign
        p = frame.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = str(value or "")
        run.font.name = font
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
        return box

    def rounded_rect(slide, left, top, width, height, fill, line=None, radius=True):
        shape = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
            left, top, width, height,
        )
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
        if line is None:
            shape.line.fill.background()
        else:
            shape.line.color.rgb = line
        return shape

    def brand(slide, *, dark=False, page=None):
        try:
            slide.shapes.add_picture(io.BytesIO(logo_bytes), Inches(0.62), Inches(0.18), height=Inches(0.38))
            text_left = Inches(1.08)
        except Exception:
            text_left = Inches(0.62)
        add_text(slide, "AGRO-AI", text_left, Inches(0.28), Inches(1.6), Inches(0.25), size=9.5, bold=True, color=white if dark else green, font=FONT)
        if page is not None:
            add_text(slide, f"{page:02d}", Inches(12.15), Inches(0.28), Inches(0.5), Inches(0.2), size=8.5, bold=True, color=RGBColor(166, 183, 171) if dark else muted, align=PP_ALIGN.RIGHT)
        line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.62), Inches(7.02), Inches(0.82), Inches(0.045))
        line.fill.solid(); line.fill.fore_color.rgb = lime; line.line.fill.background()

    def background(slide, color):
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = color

    def add_eyebrow(slide, value, *, dark=False):
        if value:
            add_text(slide, str(value).upper(), Inches(0.82), Inches(0.83), Inches(11.4), Inches(0.28), size=9, bold=True, color=lime if dark else green2, font=FONT)

    def add_title(slide, value, *, dark=False, top=1.16, size=27):
        add_text(slide, value, Inches(0.82), Inches(top), Inches(11.55), Inches(0.72), size=size, bold=True, color=white if dark else text, font=FONT)

    def add_bullets(slide, bullets, left, top, width, *, dark=False, max_items=5):
        y = top
        for bullet in [str(x).strip() for x in (bullets or []) if str(x).strip()][:max_items]:
            rounded_rect(slide, left, y + Inches(0.1), Inches(0.09), Inches(0.09), lime, radius=False)
            add_text(slide, bullet, left + Inches(0.28), y, width - Inches(0.28), Inches(0.62), size=14, color=white if dark else RGBColor(43, 67, 53))
            y += Inches(0.75)

    def source_footer(slide, notes, *, dark=False):
        notes = [str(x).strip() for x in (notes or []) if str(x).strip()]
        if notes:
            add_text(slide, "Sources: " + " · ".join(notes[:4]), Inches(0.82), Inches(6.55), Inches(11.4), Inches(0.28), size=7.8, color=RGBColor(176, 194, 182) if dark else muted)

    slides = [item for item in (plan.get("slides") or []) if isinstance(item, dict)]
    if not slides:
        slides = create_artifact_plan(
            format_name="pptx",
            title=title,
            question=question,
            answer=answer,
            evidence=evidence,
            analysis_context={},
        ).get("slides") or []

    for index, item in enumerate(slides[:10], start=1):
        layout = str(item.get("layout") or "thesis")
        dark = layout in {"title", "actions", "closing"}
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        background(slide, green if dark else offwhite)
        brand(slide, dark=dark, page=index)
        add_eyebrow(slide, item.get("eyebrow"), dark=dark)

        if layout == "title":
            add_text(slide, item.get("title") or plan.get("title") or title, Inches(0.82), Inches(1.55), Inches(10.9), Inches(1.65), size=35, bold=True, color=white, font=FONT)
            subtitle = str(plan.get("subtitle") or item.get("body") or "").strip()
            add_text(slide, subtitle, Inches(0.86), Inches(3.55), Inches(9.6), Inches(0.8), size=16, color=RGBColor(211, 226, 216))
            callout = str(item.get("callout") or "").strip()
            if callout:
                rounded_rect(slide, Inches(0.84), Inches(5.35), Inches(4.8), Inches(0.7), RGBColor(28, 66, 49))
                add_text(slide, callout, Inches(1.05), Inches(5.55), Inches(4.35), Inches(0.28), size=10.5, bold=True, color=lime, font=FONT)
            continue

        add_title(slide, item.get("title") or "", dark=dark)

        if layout == "thesis":
            headline = str(item.get("headline") or item.get("body") or "").strip()
            add_text(slide, headline, Inches(0.84), Inches(2.08), Inches(8.15), Inches(1.75), size=28, bold=True, color=text, font=FONT)
            body = str(item.get("body") or "").strip()
            if body and body != headline:
                add_text(slide, body, Inches(0.86), Inches(4.05), Inches(7.8), Inches(1.15), size=14.5, color=RGBColor(64, 85, 71))
            callout = str(item.get("callout") or "").strip()
            if callout:
                rounded_rect(slide, Inches(9.35), Inches(2.0), Inches(3.05), Inches(3.75), surface, soft)
                add_text(slide, "WHAT TO REMEMBER", Inches(9.66), Inches(2.35), Inches(2.4), Inches(0.25), size=8.5, bold=True, color=green2, font=FONT)
                add_text(slide, callout, Inches(9.66), Inches(2.92), Inches(2.35), Inches(2.0), size=16, bold=True, color=text, font=FONT)
            else:
                add_bullets(slide, item.get("bullets"), Inches(9.1), Inches(2.05), Inches(3.2), dark=False, max_items=4)

        elif layout == "two_column":
            rounded_rect(slide, Inches(0.82), Inches(2.03), Inches(5.86), Inches(3.95), surface, soft)
            rounded_rect(slide, Inches(6.93), Inches(2.03), Inches(5.58), Inches(3.95), surface, soft)
            add_text(slide, item.get("left_title") or "What we know", Inches(1.12), Inches(2.38), Inches(5.15), Inches(0.4), size=14, bold=True, color=green, font=FONT)
            add_bullets(slide, item.get("left_points") or item.get("bullets"), Inches(1.12), Inches(2.95), Inches(5.1), max_items=4)
            add_text(slide, item.get("right_title") or "What it means", Inches(7.23), Inches(2.38), Inches(4.95), Inches(0.4), size=14, bold=True, color=green, font=FONT)
            add_bullets(slide, item.get("right_points"), Inches(7.23), Inches(2.95), Inches(4.9), max_items=4)

        elif layout == "metrics":
            metrics = [m for m in (item.get("metrics") or []) if isinstance(m, dict)][:4]
            if not metrics:
                add_bullets(slide, item.get("bullets"), Inches(0.9), Inches(2.05), Inches(11.1), max_items=5)
            else:
                count = len(metrics)
                gap = 0.22
                card_w = (11.55 - gap * (count - 1)) / count
                for i, metric in enumerate(metrics):
                    x = 0.82 + i * (card_w + gap)
                    rounded_rect(slide, Inches(x), Inches(2.15), Inches(card_w), Inches(3.55), surface, soft)
                    add_text(slide, metric.get("value") or "", Inches(x + 0.28), Inches(2.55), Inches(card_w - 0.55), Inches(0.75), size=27, bold=True, color=green, font=FONT)
                    add_text(slide, metric.get("label") or "", Inches(x + 0.28), Inches(3.5), Inches(card_w - 0.55), Inches(0.55), size=12, bold=True, color=text, font=FONT)
                    add_text(slide, metric.get("context") or "", Inches(x + 0.28), Inches(4.25), Inches(card_w - 0.55), Inches(0.85), size=10.5, color=muted)

        elif layout == "evidence":
            rounded_rect(slide, Inches(0.82), Inches(2.02), Inches(8.0), Inches(4.0), surface, soft)
            add_bullets(slide, item.get("bullets"), Inches(1.1), Inches(2.34), Inches(7.35), max_items=5)
            rounded_rect(slide, Inches(9.1), Inches(2.02), Inches(3.4), Inches(4.0), RGBColor(235, 242, 236))
            add_text(slide, "EVIDENCE BOUNDARY", Inches(9.43), Inches(2.37), Inches(2.7), Inches(0.3), size=8.5, bold=True, color=green2, font=FONT)
            callout = item.get("callout") or item.get("headline") or "Use only what the workspace can support."
            add_text(slide, callout, Inches(9.43), Inches(3.0), Inches(2.65), Inches(1.75), size=15, bold=True, color=text, font=FONT)

        elif layout == "timeline":
            points = [str(x).strip() for x in (item.get("bullets") or []) if str(x).strip()][:4]
            if not points:
                points = [str(x).strip() for x in (item.get("left_points") or []) if str(x).strip()][:4]
            y = 3.0
            if points:
                line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1.3), Inches(y + 0.24), Inches(10.5), Inches(0.05))
                line.fill.solid(); line.fill.fore_color.rgb = RGBColor(185, 204, 190); line.line.fill.background()
                step_w = 10.5 / max(1, len(points))
                for i, point in enumerate(points):
                    x = 1.3 + i * step_w
                    rounded_rect(slide, Inches(x), Inches(y), Inches(0.52), Inches(0.52), green, radius=True)
                    add_text(slide, str(i + 1), Inches(x), Inches(y + 0.13), Inches(0.52), Inches(0.2), size=9, bold=True, color=white, align=PP_ALIGN.CENTER)
                    add_text(slide, point, Inches(x - 0.15), Inches(y + 0.85), Inches(step_w - 0.12), Inches(1.15), size=11.5, bold=True, color=text, font=FONT)

        elif layout == "actions":
            add_bullets(slide, item.get("bullets") or item.get("left_points"), Inches(0.95), Inches(2.05), Inches(10.8), dark=True, max_items=5)
            callout = str(item.get("callout") or "").strip()
            if callout:
                add_text(slide, callout, Inches(0.98), Inches(5.88), Inches(10.7), Inches(0.48), size=12, bold=True, color=lime, font=FONT)

        elif layout == "closing":
            headline = item.get("headline") or item.get("callout") or "Turn intelligence into operating work."
            add_text(slide, headline, Inches(0.86), Inches(2.12), Inches(10.7), Inches(1.55), size=30, bold=True, color=white, font=FONT)
            body = str(item.get("body") or "").strip()
            if body:
                add_text(slide, body, Inches(0.9), Inches(4.1), Inches(8.8), Inches(1.0), size=15, color=RGBColor(211, 226, 216))
            add_text(slide, "AGRO-AI ENTERPRISE PORTAL", Inches(0.9), Inches(6.1), Inches(4.0), Inches(0.3), size=9, bold=True, color=lime, font=FONT)

        else:
            add_bullets(slide, item.get("bullets"), Inches(0.9), Inches(2.05), Inches(11.0), max_items=5)

        source_footer(slide, item.get("source_notes"), dark=dark)

    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def build_artifact_bundle(
    *,
    format_name: str,
    title: str,
    question: str,
    answer: str,
    uploaded_evidence: list[dict[str, Any]],
    tenant_id: str,
    analysis_context: dict[str, Any] | None = None,
) -> tuple[bytes, str, str, dict[str, Any]]:
    fmt = str(format_name or "pdf").strip().lower()
    if fmt not in _FORMATS:
        raise ValueError("Unsupported artifact format")
    content_type, extension = _FORMATS[fmt]
    clean_title = _plain(title, 180) or "AGRO-AI Operating Artifact"
    plan = create_artifact_plan(
        format_name=fmt,
        title=clean_title,
        question=_plain(question, 12000),
        answer=_plain(answer, 50000),
        evidence=uploaded_evidence or [],
        analysis_context=analysis_context or {},
    )
    if fmt == "pdf":
        data = build_report_pdf_bytes(
            ReportPdfRequest(
                title=str(plan.get("title") or clean_title),
                question=_plain(question, 12000),
                answer=_plain(answer, 50000),
                uploaded_evidence=uploaded_evidence or [],
            ),
            tenant_id,
        )
    elif fmt == "docx":
        data = _docx_bytes(
            title=clean_title,
            question=_plain(question, 12000),
            answer=_plain(answer, 50000),
            evidence=uploaded_evidence or [],
            plan=plan,
        )
    else:
        data = _pptx_bytes(
            title=clean_title,
            question=_plain(question, 12000),
            answer=_plain(answer, 50000),
            evidence=uploaded_evidence or [],
            plan=plan,
        )
    return data, content_type, _filename(str(plan.get("title") or clean_title), extension), plan

def build_artifact_bytes(
    *,
    format_name: str,
    title: str,
    question: str,
    answer: str,
    uploaded_evidence: list[dict[str, Any]],
    tenant_id: str,
) -> tuple[bytes, str, str]:
    data, content_type, filename, _plan = build_artifact_bundle(
        format_name=format_name,
        title=title,
        question=question,
        answer=answer,
        uploaded_evidence=uploaded_evidence,
        tenant_id=tenant_id,
        analysis_context={},
    )
    return data, content_type, filename


def create_workspace_artifact(
    db: Session,
    *,
    tenant_id: str,
    workspace_id: str | None,
    format_name: str,
    title: str,
    question: str,
    answer: str,
    uploaded_evidence: list[dict[str, Any]] | None = None,
    analysis_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data, content_type, filename, plan = build_artifact_bundle(
        format_name=format_name,
        title=title,
        question=question,
        answer=answer,
        uploaded_evidence=uploaded_evidence or [],
        tenant_id=tenant_id,
        analysis_context=analysis_context or {},
    )
    digest = hashlib.sha256(data).hexdigest()
    storage_path: str | None = None
    body_text: str | None = None
    storage_backend = "database_fallback"
    store = None

    if object_storage_configured():
        store = get_object_store()
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as handle:
            handle.write(data)
            temp_path = handle.name
        try:
            stored = store.put_path(
                temp_path,
                tenant_id=tenant_id,
                connection_id=_ARTIFACT_SCOPE,
                filename=filename,
                content_type=content_type,
                expected_sha256=digest,
                expected_size=len(data),
                pending_registration=True,
            )
            storage_path = stored.uri
            storage_backend = "object_storage"
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
    else:
        body_text = base64.b64encode(data).decode("ascii")

    row = GeneratedArtifact(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        artifact_type=f"agentic_{str(format_name).lower()}",
        title=_plain(title, 220) or "AGRO-AI Workspace Artifact",
        filename=filename,
        content_type=content_type,
        storage_path=storage_path,
        body_text=body_text,
        metadata_json={
            "source": "ask_agro_ai_agent",
            "sha256": digest,
            "size_bytes": len(data),
            "storage_backend": storage_backend,
            "storage_scope": _ARTIFACT_SCOPE,
            "encoding": "base64" if body_text else None,
            "format": str(format_name).lower(),
            "artifact_plan": plan,
            "artifact_model": plan.get("model"),
            "artifact_reasoning_effort": plan.get("reasoning_effort"),
            "artifact_fallback": bool(plan.get("fallback")),
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if store is not None and storage_path:
        store.promote(storage_path, tenant_id=tenant_id, connection_id=_ARTIFACT_SCOPE)

    return {
        "id": row.id,
        "title": row.title,
        "filename": row.filename,
        "content_type": row.content_type,
        "artifact_type": row.artifact_type,
        "workspace_id": row.workspace_id,
        "download_url": f"/v1/agents/artifacts/{row.id}/download",
        "preview": {
            "format": str(format_name).lower(),
            "title": plan.get("title") or row.title,
            "subtitle": plan.get("subtitle") or "",
            "audience": plan.get("audience") or "",
            "objective": plan.get("objective") or "",
            "executive_summary": plan.get("executive_summary") or "",
            "design_direction": plan.get("design_direction") or "",
            "slides": plan.get("slides") or [],
            "sections": plan.get("sections") or [],
        },
        "quality": {
            "model": plan.get("model"),
            "reasoning_effort": plan.get("reasoning_effort"),
            "fallback": bool(plan.get("fallback")),
            "checks": plan.get("quality_checks") or [],
        },
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def read_workspace_artifact_bytes(row: GeneratedArtifact) -> bytes:
    metadata = row.metadata_json or {}
    if row.storage_path:
        store = get_object_store()
        return store.read_bytes(
            row.storage_path,
            max_bytes=max(1, int(metadata.get("size_bytes") or 25 * 1024 * 1024)),
            tenant_id=row.tenant_id,
            connection_id=str(metadata.get("storage_scope") or _ARTIFACT_SCOPE),
        )
    if row.body_text and metadata.get("encoding") == "base64":
        return base64.b64decode(row.body_text.encode("ascii"), validate=True)
    if row.body_text:
        return row.body_text.encode("utf-8")
    raise RuntimeError("Artifact content is unavailable")
