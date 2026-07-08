from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.operational_records import DataSource
from app.services.object_storage import get_object_store


DEFAULT_EXCERPT_CHARS = 4_000
MAX_SOURCE_BYTES = min(int(getattr(settings, "CONNECTOR_MAX_UPLOAD_BYTES", 25_000_000) or 25_000_000), 25_000_000)


def _is_pdf(source: DataSource) -> bool:
    filename = (source.filename or "").lower()
    return filename.endswith(".pdf") or source.content_type == "application/pdf" or source.source_type == "pdf_document"


def _looks_binary(value: str) -> bool:
    if not value:
        return False
    sample = value[:2_000]
    control = sum(1 for char in sample if ord(char) < 32 and char not in "\n\r\t")
    return value.startswith("%PDF") or (len(sample) > 0 and control / len(sample) > 0.03)


def _read_source_bytes(source: DataSource) -> bytes | None:
    location = str(source.storage_path or "")
    if not location:
        return None
    try:
        if "://" in location:
            if not source.connector_connection_id:
                return None
            return get_object_store().read_bytes(
                location,
                max_bytes=MAX_SOURCE_BYTES,
                tenant_id=source.tenant_id,
                connection_id=source.connector_connection_id,
            )
        path = Path(location)
        if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            return None
        return path.read_bytes()
    except Exception:
        return None


def _extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data), strict=False)
        parts: list[str] = []
        total = 0
        for page in reader.pages[:200]:
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            parts.append(text)
            total += len(text)
            if total >= 200_000:
                break
        return "\n\n".join(parts)[:200_000]
    except Exception:
        return ""


def source_text(source: DataSource) -> str:
    """Return bounded, customer-owned source text suitable for intelligence context.

    Uploaded bytes remain in durable storage. This helper only materializes a
    bounded text representation and never exposes the storage URI to the model or
    customer-facing API.
    """
    current = str(source.raw_text or "")
    if _is_pdf(source) and (not current.strip() or _looks_binary(current)):
        data = _read_source_bytes(source)
        if data:
            extracted = _extract_pdf_text(data)
            if extracted:
                return extracted
    return current if not _looks_binary(current) else ""


def source_content_excerpt(source: DataSource, *, max_chars: int = DEFAULT_EXCERPT_CHARS) -> str:
    text = source_text(source).replace("\x00", " ").strip()
    return text[: max(0, max_chars)]


def parsed_rows_preview(source: DataSource, *, limit: int = 12) -> list[dict[str, Any]]:
    metadata = source.metadata_json if isinstance(source.metadata_json, dict) else {}
    rows = metadata.get("parsed_rows") or metadata.get("rows_preview") or []
    if not isinstance(rows, list):
        return []
    return [row for row in rows[:limit] if isinstance(row, dict)]


def content_available(source: DataSource) -> bool:
    """Cheap readiness signal; never downloads an object during library listing."""
    current = str(source.raw_text or "")
    if current.strip() and not _looks_binary(current):
        return True
    if parsed_rows_preview(source, limit=1):
        return True
    # A stored PDF is extractable on demand by source_text() for intelligence.
    return _is_pdf(source) and bool(source.storage_path)
