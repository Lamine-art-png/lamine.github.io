from __future__ import annotations

import io
from datetime import datetime

from app.core.security import create_access_token
from app.models.saas import Organization, OrganizationMembership, User, Workspace


def _auth(db, *, email="fi@example.com", org_id="org-fi", workspace_id="ws-fi"):
    user = User(
        id=f"user-{org_id}",
        email=email,
        name="Field User",
        password_hash="test",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    org = Organization(id=org_id, name="Field Farms", slug=org_id, owner_user_id=user.id, plan="pro", subscription_status="active")
    membership = OrganizationMembership(organization_id=org.id, user_id=user.id, role="owner")
    workspace = Workspace(id=workspace_id, organization_id=org.id, name="Command Center", crop="Almonds", region="CA", mode="live")
    db.add_all([user, org, membership, workspace])
    db.commit()
    token = create_access_token({"sub": user.id, "tenant_id": org.id, "org_id": org.id, "role": "owner"})
    return org, workspace, {"Authorization": f"Bearer {token}"}


def _initiate(client, headers, **overrides):
    body = {
        "client_capture_id": overrides.pop("client_capture_id", "cap-1"),
        "idempotency_key": overrides.pop("idempotency_key", "idem-1"),
        "capture_source": "typed",
        "note_text": overrides.pop("note_text", "Irrigation ran 45 minutes on Block A, applied 1200 gallons."),
        "field_name": "North Ranch",
        "block_name": "Block A",
        "crop": "Almonds",
        "latitude": 36.7,
        "longitude": -119.8,
        "location_accuracy_m": 5.0,
    }
    body.update(overrides)
    return client.post("/v1/field-intelligence/captures/initiate", json=body, headers=headers)


def test_capture_lifecycle_typed_note(client, db):
    _, _, headers = _auth(db)
    res = _initiate(client, headers)
    assert res.status_code == 200, res.text
    capture = res.json()["capture"]
    assert capture["status"] == "received"

    done = client.post(f"/v1/field-intelligence/captures/{capture['id']}/complete", json={}, headers=headers)
    assert done.status_code == 200, done.text
    obs = done.json()["observation"]
    assert obs["status"] in {"completed", "needs_review"}
    # deterministic extraction grounded the irrigation measurements
    assert obs["structured"]["event_type"] == "irrigation_event"
    assert obs["structured"]["applied_water_gallons"] == 1200
    assert obs["structured"]["irrigation_duration_minutes"] == 45
    # provenance + processing runs recorded, transcription truthfully skipped (typed)
    assert obs["provenance"]["transcription_status"] == "skipped"
    stages = {run["stage"] for run in obs["processing_runs"]}
    assert stages == {"transcription", "extraction", "correlation"}


def test_idempotent_replay_no_duplicates(client, db):
    _, _, headers = _auth(db)
    first = _initiate(client, headers)
    second = _initiate(client, headers)  # same client_capture_id + idempotency_key
    assert first.json()["capture"]["id"] == second.json()["capture"]["id"]

    cap_id = first.json()["capture"]["id"]
    o1 = client.post(f"/v1/field-intelligence/captures/{cap_id}/complete", json={}, headers=headers).json()["observation"]
    o2 = client.post(f"/v1/field-intelligence/captures/{cap_id}/complete", json={}, headers=headers).json()["observation"]
    assert o1["id"] == o2["id"]  # completing twice returns the same observation

    listing = client.get("/v1/field-intelligence/observations", headers=headers).json()
    assert listing["count"] == 1


def test_tenant_isolation(client, db):
    _auth(db, email="a@example.com", org_id="org-a", workspace_id="ws-a")
    _, _, headers_b = _auth(db, email="b@example.com", org_id="org-b", workspace_id="ws-b")

    # org A creates + completes an observation
    _, _, headers_a = _auth(db, email="a2@example.com", org_id="org-a2", workspace_id="ws-a2")
    cap = _initiate(client, headers_a, client_capture_id="cap-a", idempotency_key="idem-a").json()["capture"]
    obs = client.post(f"/v1/field-intelligence/captures/{cap['id']}/complete", json={}, headers=headers_a).json()["observation"]

    # org B cannot see or fetch it
    assert client.get("/v1/field-intelligence/observations", headers=headers_b).json()["count"] == 0
    assert client.get(f"/v1/field-intelligence/observations/{obs['id']}", headers=headers_b).status_code == 404


def test_sync_batch_partial_success(client, db):
    _, _, headers = _auth(db)
    good = {"client_capture_id": "b1", "idempotency_key": "b1", "note_text": "Pump filter clogged on Block B, urgent."}
    bad = {"idempotency_key": "b2", "note_text": "missing client id"}  # invalid -> 422
    res = client.post("/v1/field-intelligence/sync/batch", json={"captures": [good, bad]}, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["accepted"] == 1
    assert body["failed"] == 1
    statuses = {r["status"] for r in body["results"]}
    assert statuses == {"accepted", "failed"}


def test_correction_and_task_creation(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers, note_text="Broken valve, major leak on Block A").json()["capture"]
    obs = client.post(f"/v1/field-intelligence/captures/{cap['id']}/complete", json={}, headers=headers).json()["observation"]

    patched = client.patch(
        f"/v1/field-intelligence/observations/{obs['id']}",
        json={"corrected_transcript": "Broken valve confirmed, isolated Block A", "severity": "high"},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()["observation"]
    assert body["corrected_transcript"].startswith("Broken valve confirmed")
    actions = {event["action"] for event in body["audit_history"]}
    assert "observation_corrected" in actions

    task_res = client.post(f"/v1/field-intelligence/observations/{obs['id']}/tasks", json={"title": "Repair valve"}, headers=headers)
    assert task_res.status_code == 200, task_res.text
    assert task_res.json()["task"]["title"] == "Repair valve"


def test_correlation_provenance_present(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    obs = client.post(f"/v1/field-intelligence/captures/{cap['id']}/complete", json={}, headers=headers).json()["observation"]
    corr = obs["correlation"]
    assert "time_window" in corr and "freshness_summary" in corr
    assert corr["schema_version"].startswith("field-observation-correlation/")
    assert "explanation" in corr


def test_transcription_unavailable_when_audio_but_no_provider(client, db, monkeypatch):
    _, _, headers = _auth(db)
    # capture claims an audio asset but no provider is configured -> unavailable, never faked
    cap = _initiate(
        client, headers,
        capture_source="voice",
        asset_manifest=[{"kind": "audio", "client_asset_id": "a1", "object_ref": "spool://a1"}],
        note_text=None,
    ).json()["capture"]
    obs = client.post(f"/v1/field-intelligence/captures/{cap['id']}/complete", json={}, headers=headers).json()["observation"]
    assert obs["provenance"]["transcription_status"] == "unavailable"
    assert obs["transcript"] in (None, "")


def test_asset_upload_rejects_wrong_content(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    # a CSV pretending to be audio must be rejected
    files = {"file": ("data.csv", io.BytesIO(b"col1,col2\n1,2\n"), "text/csv")}
    data = {"client_asset_id": "asset-1", "kind": "audio"}
    res = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets", files=files, data=data, headers=headers)
    assert res.status_code == 415, res.text


def test_asset_upload_and_dedup(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    files = {"file": ("photo.png", io.BytesIO(png), "image/png")}
    data = {"client_asset_id": "asset-photo", "kind": "photo"}
    r1 = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets", files=files, data=data, headers=headers)
    assert r1.status_code == 200, r1.text
    files2 = {"file": ("photo.png", io.BytesIO(png), "image/png")}
    r2 = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets", files=files2, data=data, headers=headers)
    assert r2.status_code == 200
    assert r1.json()["asset"]["id"] == r2.json()["asset"]["id"]  # deduped safe replay


def test_unauthenticated_rejected(client, db):
    res = client.get("/v1/field-intelligence/observations")
    assert res.status_code in (401, 403)
