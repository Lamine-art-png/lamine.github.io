"""Export renderers for compliance evidence packages."""
from __future__ import annotations

import csv
import html
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any


def render_csv(package: dict[str, Any]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["section", "id", "field", "value", "truth_label", "source", "method"])
    for measurement in package["measurements"]:
        writer.writerow(["measurement", measurement["id"], "value", measurement["value"], measurement["truth_label"], measurement.get("source_system"), measurement.get("method")])
    for budget in package["water_budgets"]:
        writer.writerow(["water_budget", budget["id"], "remaining_balance_af", budget["remaining_balance_af"], "calculated", "AGRO-AI", "allocation_minus_extraction"])
    for row in package["reconciliation"]:
        writer.writerow(["reconciliation", row["id"], "variance_af", row.get("variance_af"), row.get("truth_labels", {}).get("variance_af", "calculated"), "AGRO-AI", "recommendation_to_application"])
    return out.getvalue().encode("utf-8")


def _sheet_xml(rows: list[list[Any]]) -> str:
    body = []
    for idx, row in enumerate(rows, start=1):
        cells = []
        for col_idx, value in enumerate(row):
            col = chr(ord("A") + col_idx)
            text = html.escape("" if value is None else str(value))
            cells.append(f'<c r="{col}{idx}" t="inlineStr"><is><t>{text}</t></is></c>')
        body.append(f'<row r="{idx}">{"".join(cells)}</row>')
    return '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(body) + '</sheetData></worksheet>'


def render_xlsx(package: dict[str, Any]) -> bytes:
    sheets = {
        "sheet1.xml": [["AGRO-AI Compliance Export", package["id"]], ["Workflow", package["workflow_type"]], ["Disclaimer", package["disclaimer"]]],
        "sheet2.xml": [["id", "type", "value", "unit", "truth_label", "source"]] + [[m["id"], m["measurement_type"], m["value"], m["unit"], m["truth_label"], m["source_system"]] for m in package["measurements"]],
        "sheet3.xml": [["id", "allocation_af", "extraction_af", "remaining_balance_af", "threshold_status"]] + [[b["id"], b["allocation_af"], b["extraction_af"], b["remaining_balance_af"], b["threshold_status"]] for b in package["water_budgets"]],
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        zf.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/></Relationships>')
        zf.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Cover" sheetId="1" r:id="rId1"/><sheet name="Measurements" sheetId="2" r:id="rId2"/><sheet name="Water Budgets" sheetId="3" r:id="rId3"/></sheets></workbook>')
        for name, rows in sheets.items():
            zf.writestr(f"xl/worksheets/{name}", _sheet_xml(rows))
    return out.getvalue()


def render_pdf(package: dict[str, Any]) -> bytes:
    lines = [
        "AGRO-AI Compliance Evidence Package",
        f"Export ID: {package['id']}",
        f"Workflow: {package['workflow_type']}",
        f"Readiness: {package['readiness']['readiness_status']} ({package['readiness']['readiness_percentage']}%)",
        "",
        "Disclaimer:",
        package["disclaimer"],
        "",
        "Methodology:",
        package["methodology"],
        "",
        "Generated: " + datetime.now(timezone.utc).isoformat(),
    ]
    stream_lines = ["BT", "/F1 14 Tf", "50 760 Td"]
    first = True
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:100]
        if first:
            stream_lines.append(f"({escaped}) Tj")
            first = False
        else:
            stream_lines.append(f"0 -18 Td ({escaped}) Tj")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> endobj\n",
        f"5 0 obj << /Length {len(stream)} >> stream\n".encode("ascii") + stream + b"\nendstream endobj\n",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(out.tell())
        out.write(obj)
    xref = out.tell()
    out.write(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        out.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.write(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii"))
    return out.getvalue()


def render_export_content(package: dict[str, Any], export_type: str) -> tuple[bytes, str, str]:
    stem = f"agro-ai-{package['workflow_type']}-{package['id']}"
    if export_type == "csv":
        return render_csv(package), "text/csv", f"{stem}.csv"
    if export_type == "xlsx":
        return render_xlsx(package), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{stem}.xlsx"
    if export_type == "pdf":
        return render_pdf(package), "application/pdf", f"{stem}.pdf"
    return json.dumps(package, indent=2, sort_keys=True).encode("utf-8"), "application/json", f"{stem}.json"
