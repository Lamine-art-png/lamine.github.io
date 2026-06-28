"""Operator Cockpit endpoints."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_auth_context
from app.db.base import get_db
from app.models.saas import Workspace
from app.services.operator_cockpit import (
    build_context,
    decision_workbench,
    exceptions,
    field_intelligence,
    readiness_summary,
    report_factory,
)


router = APIRouter(tags=["operator-cockpit"])


class WorkbenchRunRequest(BaseModel):
    workspace_id: str | None = None
    field_id: str | None = None
    mode: Literal["daily", "field", "compliance", "irrigation"] = "daily"


class ReportFactoryRequest(BaseModel):
    report_type: Literal[
        "water_use_summary",
        "compliance_packet",
        "exception_report",
        "executive_brief",
        "grower_recommendation",
    ]
    workspace_id: str | None = None
    field_id: str | None = None
    audience: Literal["operator", "owner", "agency", "lender", "investor", "grower"] | None = None


def _require_org(ctx: AuthContext) -> str:
    if not ctx.organization:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization membership required")
    return ctx.organization.id


def _workspace(db: Session, organization_id: str, workspace_id: str | None) -> Workspace | None:
    query = db.query(Workspace).filter(Workspace.organization_id == organization_id)
    if workspace_id:
        workspace = query.filter(Workspace.id == workspace_id).first()
        if not workspace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        return workspace
    return query.order_by(Workspace.created_at.asc()).first()


def _context(db: Session, ctx: AuthContext, workspace_id: str | None = None):
    organization_id = _require_org(ctx)
    return build_context(db, organization_id, _workspace(db, organization_id, workspace_id))


def _lines(title: str, rows: list) -> list[str]:
    output = [title]
    if not rows:
        return output + ["None listed."]
    for row in rows:
        if isinstance(row, dict):
            output.append(str(row.get("title") or row.get("recommendation") or row.get("summary") or row.get("field_name") or row.get("id") or row))
        else:
            output.append(str(row))
    return output


def _factory_pdf_bytes(report: dict) -> bytes:
    sections = [
        [report.get("title", "AGRO-AI Report"), f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z"],
        ["Executive Summary", report.get("executive_summary", "No executive summary generated.")],
        _lines("Key Findings", report.get("key_findings") or []),
        _lines("Field Summary", report.get("field_summary") or []),
        _lines("Exceptions", report.get("exceptions") or []),
        _lines("Decisions", report.get("decisions") or []),
        _lines("Missing Evidence", report.get("missing_evidence") or []),
        _lines("Evidence Appendix", report.get("evidence_appendix") or []),
    ]
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ModuleNotFoundError:
        lines = [str(item) for section in sections for item in section]
        return _minimal_pdf_bytes(lines)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    _width, height = letter
    y = height - 54

    def draw(line: str, *, bold: bool = False) -> None:
        nonlocal y
        if y < 54:
            pdf.showPage()
            y = height - 54
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", 12 if bold else 9)
        clean = line.replace("\n", " ").strip()
        for chunk in [clean[i : i + 105] for i in range(0, len(clean), 105)] or [""]:
            pdf.drawString(54, y, chunk)
            y -= 14

    for section in sections:
        heading, *body = section
        draw(str(heading), bold=True)
        for item in body:
            draw(str(item))
        y -= 8

    pdf.save()
    return buffer.getvalue()


def _minimal_pdf_bytes(lines: list[str]) -> bytes:
    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content_lines = ["BT", "/F1 10 Tf", "54 738 Td"]
    for line in lines[:48]:
        for chunk in [line[i : i + 90] for i in range(0, len(line), 90)] or [""]:
            content_lines.append(f"({esc(chunk)}) Tj")
            content_lines.append("0 -14 Td")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", "replace")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode() + b" >> stream\n" + stream + b"\nendstream endobj\n",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_at = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode())
    return bytes(pdf)


@router.get("/readiness/summary")
def get_readiness_summary(
    workspace_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return readiness_summary(_context(db, ctx, workspace_id))


@router.get("/fields/intelligence")
def get_fields_intelligence(
    workspace_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return field_intelligence(_context(db, ctx, workspace_id))


@router.get("/exceptions")
def get_exceptions(
    workspace_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return exceptions(_context(db, ctx, workspace_id))


@router.get("/decisions/workbench")
def get_decision_workbench(
    workspace_id: str | None = Query(default=None),
    field_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return decision_workbench(_context(db, ctx, workspace_id), field_id=field_id)


@router.post("/decisions/workbench/run")
def run_decision_workbench(
    payload: WorkbenchRunRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return decision_workbench(_context(db, ctx, payload.workspace_id), mode=payload.mode, field_id=payload.field_id)


@router.post("/reports/factory")
def create_factory_report(
    payload: ReportFactoryRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> dict:
    return report_factory(
        _context(db, ctx, payload.workspace_id),
        report_type=payload.report_type,
        audience=payload.audience,
        field_id=payload.field_id,
    )


@router.post("/reports/factory/pdf")
def create_factory_report_pdf(
    payload: ReportFactoryRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> Response:
    result = report_factory(
        _context(db, ctx, payload.workspace_id),
        report_type=payload.report_type,
        audience=payload.audience,
        field_id=payload.field_id,
    )
    report = result["report"]
    filename = f"agro-ai-{payload.report_type}.pdf"
    return Response(
        content=_factory_pdf_bytes(report),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
