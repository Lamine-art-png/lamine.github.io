"""Generating a report produces a real, downloadable, tenant-scoped document."""
from datetime import datetime

from app.models.operational_records import GeneratedArtifact
from app.models.saas import Organization, User


def _login(client, db, email, org_name, plan=None):
    client.post("/v1/auth/register", json={"email": email, "password": "strong-password", "name": "Owner", "organization_name": org_name, "workspace_name": "Main", "crop": "Almonds", "region": "California"})
    user = db.query(User).filter(User.email == email).first()
    user.email_verification_status, user.email_verified_at = "verified", datetime.utcnow()
    db.commit()
    body = client.post("/v1/auth/login", json={"email": email, "password": "strong-password"}).json()
    org = db.get(Organization, body["organization"]["id"]) if body.get("organization") else db.query(Organization).filter(Organization.name == org_name).first()
    if plan:
        org.plan, org.subscription_status = plan, "active"
        db.commit()
    return {"Authorization": f"Bearer {body['access_token']}"}, org


def test_free_plan_cannot_generate_reports(client, db):
    headers, _ = _login(client, db, "free-reports@example.com", "Free Reports Farm")
    response = client.post("/v1/reports/generate", headers=headers, json={"report_type": "evidence_summary", "format": "markdown"})
    assert response.status_code == 402


def test_generate_stores_downloadable_report_without_sample_fields(client, db):
    headers, org = _login(client, db, "pro-reports@example.com", "Pro Reports Farm", plan="professional")
    response = client.post("/v1/reports/generate", headers=headers, json={"report_type": "water_agency_packet", "format": "pdf"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "generated" and body["sample_mode"] is True
    assert "Sample Field" not in body["preview"]
    assert "empty workspace" in body["preview"]
    artifact = body["artifact"]
    assert artifact["content_type"] == "application/pdf" and artifact["filename"].endswith(".pdf")
    assert "report" not in artifact["metadata_json"]

    listed = client.get("/v1/reports", headers=headers).json()["reports"]
    assert [row["id"] for row in listed] == [artifact["id"]]

    download = client.get(f"/v1/artifacts/{artifact['id']}/download", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF")

    markdown = client.post("/v1/reports/generate", headers=headers, json={"report_type": "evidence_summary", "format": "markdown"}).json()
    text = client.get(f"/v1/artifacts/{markdown['artifact']['id']}/download", headers=headers)
    assert text.status_code == 200 and text.text.startswith("# AGRO-AI Evidence Summary")
    assert db.query(GeneratedArtifact).filter(GeneratedArtifact.tenant_id == org.id).count() == 2


def test_artifacts_are_tenant_isolated(client, db):
    owner_headers, _ = _login(client, db, "tenant-a@example.com", "Tenant A Farm", plan="professional")
    other_headers, _ = _login(client, db, "tenant-b@example.com", "Tenant B Farm", plan="professional")
    artifact = client.post("/v1/reports/generate", headers=owner_headers, json={"report_type": "evidence_summary", "format": "markdown"}).json()["artifact"]
    assert client.get(f"/v1/artifacts/{artifact['id']}/download", headers=other_headers).status_code == 404
    assert client.get(f"/v1/artifacts/{artifact['id']}", headers=other_headers).status_code == 404
    assert client.get("/v1/reports", headers=other_headers).json()["reports"] == []
