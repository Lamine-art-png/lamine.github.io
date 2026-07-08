from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.source_library import list_source_library, source_public
from app.db.base import Base
from app.models.operational_records import DataSource, EvidenceRecord
from app.models.saas import Organization, User
from app.services.intelligence_context import _source_rows
from app.services.source_content import source_content_excerpt


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    owner = User(id="owner-source-test", email="owner-source@example.com", password_hash="x")
    db.add(owner)
    db.flush()
    db.add(
        Organization(
            id="org-source-test",
            name="Source Test Org",
            slug="source-test-org",
            owner_user_id=owner.id,
            plan="free",
        )
    )
    db.commit()
    return db


def test_source_public_hides_storage_location_and_exposes_customer_state():
    source = DataSource(
        id="source-safe",
        tenant_id="org-source-test",
        provider="manual_csv",
        source_type="telemetry_csv",
        filename="field-log.csv",
        content_type="text/csv",
        storage_path="s3://private-bucket/org-source-test/object.csv",
        raw_text="field,flow\nNorth,42\n",
        content_sha256="a" * 64,
        metadata_json={"rows_parsed": 1, "warnings": []},
        status="parsed",
    )

    public = source_public(source, evidence_count=3)

    assert public["filename"] == "field-log.csv"
    assert public["evidence_count"] == 3
    assert public["durable_stored"] is True
    assert public["checksum_verified"] is True
    assert public["intelligence_ready"] is True
    assert "storage_path" not in public
    assert "raw_text" not in public


def test_source_library_lists_original_upload_and_linked_evidence():
    db = _session()
    try:
        source = DataSource(
            id="source-listed",
            tenant_id="org-source-test",
            provider="manual_csv",
            source_type="telemetry_csv",
            filename="meter-readings.csv",
            content_type="text/csv",
            storage_path="/tmp/meter-readings.csv",
            raw_text="field,flow\nNorth,42\n",
            metadata_json={"rows_parsed": 1},
            status="parsed",
        )
        db.add(source)
        db.flush()
        db.add(
            EvidenceRecord(
                id="evidence-linked",
                tenant_id="org-source-test",
                data_source_id=source.id,
                evidence_type="uploaded_record",
                title="North reading",
                summary="Flow 42",
                value_json={"field": "North", "flow": 42},
                confidence=0.8,
                quality_status="usable",
                citation_label="manual_csv:meter-readings.csv:row-1",
                metadata_json={},
            )
        )
        db.commit()

        response = list_source_library(tenant_id="org-source-test", db=db)
        item = response["sources"][0]
        assert item["filename"] == "meter-readings.csv"
        assert item["evidence_count"] == 1
        assert item["intelligence_ready"] is True
        assert "storage_path" not in item
    finally:
        db.close()


def test_pdf_source_text_is_extracted_from_stored_upload(tmp_path):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, "North field irrigation allocation is 42 acre-feet")
    pdf.save()
    path = tmp_path / "allocation.pdf"
    path.write_bytes(buffer.getvalue())

    source = DataSource(
        id="source-pdf",
        tenant_id="org-source-test",
        provider="manual_csv",
        source_type="pdf_document",
        filename="allocation.pdf",
        content_type="application/pdf",
        storage_path=str(path),
        raw_text="%PDF binary placeholder",
        metadata_json={},
        status="parsed_with_warnings",
    )

    excerpt = source_content_excerpt(source, max_chars=2_000)
    assert "North field irrigation allocation" in excerpt
    assert "42 acre-feet" in excerpt


def test_intelligence_source_context_contains_bounded_uploaded_content():
    source = DataSource(
        id="source-context",
        tenant_id="org-source-test",
        provider="manual_csv",
        source_type="telemetry_csv",
        filename="field-log.csv",
        content_type="text/csv",
        storage_path="/tmp/field-log.csv",
        raw_text="field,flow_gpm\nNorth,42\nSouth,37\n",
        metadata_json={"rows_parsed": 2, "parsed_rows": [{"field": "North", "flow_gpm": "42"}]},
        status="parsed",
    )
    ctx = SimpleNamespace(sources=[source], organization_id="org-source-test", workspace_id=None)

    rows, citations = _source_rows(ctx, source_limit=5)

    assert rows[0]["filename"] == "field-log.csv"
    assert "North,42" in rows[0]["content_excerpt"]
    assert rows[0]["parsed_rows_preview"][0]["field"] == "North"
    assert citations[0].source_id == "source-context"
    assert citations[0].title == "field-log.csv"
