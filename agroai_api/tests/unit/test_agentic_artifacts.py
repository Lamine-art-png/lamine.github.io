from __future__ import annotations

import io
import zipfile

from app.services.agentic_artifacts import build_artifact_bytes


def test_agentic_docx_is_a_real_office_document():
    data, content_type, filename = build_artifact_bytes(
        format_name="docx",
        title="Field Operations Brief",
        question="Summarize the operation.",
        answer="Irrigation pressure is the primary issue. Verify the controller evidence before acting.",
        uploaded_evidence=[{"filename": "controller.csv", "rows_parsed": 12}],
        tenant_id="tenant-1",
    )
    assert filename.endswith(".docx")
    assert content_type.endswith("wordprocessingml.document")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert "word/document.xml" in archive.namelist()


def test_agentic_pptx_is_a_real_powerpoint():
    data, content_type, filename = build_artifact_bytes(
        format_name="pptx",
        title="Field Operations Review",
        question="Build a concise operating presentation.",
        answer=(
            "Water pressure is below the operating target. "
            "The affected block needs a controller check. "
            "Evidence is incomplete for the last irrigation event. "
            "Prioritize verification before changing the schedule. "
            "Create a follow-up task for the field team."
        ),
        uploaded_evidence=[{"filename": "field-log.csv", "rows_parsed": 24}],
        tenant_id="tenant-1",
    )
    assert filename.endswith(".pptx")
    assert content_type.endswith("presentationml.presentation")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert "ppt/presentation.xml" in archive.namelist()
        assert any(name.startswith("ppt/slides/slide") for name in archive.namelist())
