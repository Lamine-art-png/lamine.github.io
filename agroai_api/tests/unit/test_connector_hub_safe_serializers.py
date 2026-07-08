from app.api.v1.connector_hub import _job_customer_safe, _safe_public_value
from app.models.operational_records import IngestionJob


def test_safe_public_value_removes_private_paths_uris_and_credentials():
    payload = {
        "filename": "allocation.pdf",
        "object_uri": "s3://private-bucket/object.pdf",
        "nested": {
            "storage_path": "/srv/private/object.pdf",
            "api_key": "secret-value",
            "rows_parsed": 4,
        },
    }

    safe = _safe_public_value(payload)

    assert safe == {"filename": "allocation.pdf", "nested": {"rows_parsed": 4}}


def test_job_customer_safe_never_returns_object_store_location():
    job = IngestionJob(
        id="job-safe-response",
        tenant_id="org-safe",
        job_type="connector_ingest_object",
        status="queued",
        input_json={
            "filename": "allocation.pdf",
            "object_uri": "s3://private-bucket/object.pdf",
            "content_sha256": "a" * 64,
        },
        output_json={
            "data_source_id": "source-safe",
            "storage_path": "/srv/private/object.pdf",
            "rows_parsed": 3,
        },
    )

    public = _job_customer_safe(job)

    assert public["input_json"]["filename"] == "allocation.pdf"
    assert public["output_json"]["rows_parsed"] == 3
    assert "object_uri" not in public["input_json"]
    assert "storage_path" not in public["output_json"]
