from __future__ import annotations

import glob
import io
import tempfile
from datetime import datetime

import pytest

from app.core.security import create_access_token
from app.models.field_intelligence import FieldObservation
from app.models.operational_records import EvidenceRecord
from app.models.saas import Organization, OrganizationMembership, User, Workspace
from app.services import field_intelligence as svc
from app.services.object_storage import S3ObjectStore


class FakeStoreClient:
    """In-memory S3-compatible client (mirrors the object-storage test double)."""

    def __init__(self):
        self.items = {}

    def upload_fileobj(self, handle, bucket, key, ExtraArgs=None):
        self.items[(bucket, key)] = (handle.read(), dict((ExtraArgs or {}).get("Metadata") or {}))

    def head_object(self, Bucket, Key):
        body, metadata = self.items[(Bucket, Key)]
        return {"ContentLength": len(body), "Metadata": metadata}

    def get_object(self, Bucket, Key):
        body, metadata = self.items[(Bucket, Key)]
        return {"ContentLength": len(body), "Metadata": metadata, "Body": io.BytesIO(body)}

    def delete_object(self, Bucket, Key):
        self.items.pop((Bucket, Key), None)


@pytest.fixture
def fake_store(monkeypatch):
    client = FakeStoreClient()
    store = S3ObjectStore(bucket="agroai-test", prefix="agroai", client=client)
    monkeypatch.setattr(svc, "get_object_store", lambda **_: store)
    monkeypatch.setattr(svc, "object_storage_configured", lambda: True)
    return store


def _auth(db, *, email="fi@example.com", org_id="org-fi", workspace_id="ws-fi"):
    user = User(
        id=f"user-{org_id}", email=email, name="Field User", password_hash="test",
        email_verification_status="verified", email_verified_at=datetime.utcnow(),
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
        "field_name": "North Ranch", "block_name": "Block A", "crop": "Almonds",
        "latitude": 36.7, "longitude": -119.8, "location_accuracy_m": 5.0,
    }
    body.update(overrides)
    return client.post("/v1/field-intelligence/captures/initiate", json=body, headers=headers)


def _complete(client, headers, capture_id, **payload):
    return client.post(f"/v1/field-intelligence/captures/{capture_id}/complete", json=payload, headers=headers)


def _process(db, headers=None):
    # Drive the durable processing plane directly (the request only stages it).
    return svc.run_field_intelligence_jobs(db, limit=25)


def _fetch(client, headers, observation_id):
    return client.get(f"/v1/field-intelligence/observations/{observation_id}", headers=headers).json()["observation"]


# --------------------------------------------------------------------------- #

def test_capture_lifecycle_typed_note_is_async(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    res = _complete(client, headers, cap["id"])
    assert res.status_code == 202, res.text
    staged = res.json()["observation"]
    assert staged["status"] == "staged"

    _process(db)
    obs = _fetch(client, headers, staged["id"])
    assert obs["status"] in {"completed", "needs_review"}
    assert obs["structured"]["event_type"] == "irrigation_event"
    assert obs["structured"]["applied_water_gallons"] == 1200
    assert obs["provenance"]["transcription_status"] == "skipped"
    assert {r["stage"] for r in obs["processing_runs"]} == {"transcription", "extraction", "correlation"}


def test_idempotent_replay_same_payload_one_observation(client, db):
    _, _, headers = _auth(db)
    first = _initiate(client, headers)
    second = _initiate(client, headers)
    assert first.json()["capture"]["id"] == second.json()["capture"]["id"]
    cap_id = first.json()["capture"]["id"]
    o1 = _complete(client, headers, cap_id).json()["observation"]
    o2 = _complete(client, headers, cap_id).json()["observation"]
    assert o1["id"] == o2["id"]
    _process(db)
    assert client.get("/v1/field-intelligence/observations", headers=headers).json()["count"] == 1


def test_idempotency_conflict_returns_409(client, db):
    _, _, headers = _auth(db)
    _initiate(client, headers, note_text="original text")
    conflict = _initiate(client, headers, note_text="totally different text")  # same key, diff payload
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"


def test_concurrent_complete_unique_constraint(client, db):
    _, ws, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    db.add(FieldObservation(id="obs-x", tenant_id="org-fi", workspace_id=ws.id, capture_session_id=cap["id"], status="staged"))
    db.commit()
    with pytest.raises(Exception):
        db.add(FieldObservation(id="obs-y", tenant_id="org-fi", workspace_id=ws.id, capture_session_id=cap["id"], status="staged"))
        db.commit()
    db.rollback()


def test_tenant_isolation(client, db):
    _, _, headers_a = _auth(db, email="a@example.com", org_id="org-a", workspace_id="ws-a")
    _, _, headers_b = _auth(db, email="b@example.com", org_id="org-b", workspace_id="ws-b")
    cap = _initiate(client, headers_a, client_capture_id="cap-a", idempotency_key="idem-a").json()["capture"]
    obs = _complete(client, headers_a, cap["id"]).json()["observation"]
    _process(db)
    assert client.get("/v1/field-intelligence/observations", headers=headers_b).json()["count"] == 0
    assert client.get(f"/v1/field-intelligence/observations/{obs['id']}", headers=headers_b).status_code == 404


def test_sync_batch_partial_success_and_bounds(client, db):
    _, _, headers = _auth(db)
    good = {"client_capture_id": "b1", "idempotency_key": "b1", "note_text": "Pump filter clogged on Block B, urgent."}
    bad = {"idempotency_key": "b2", "note_text": "missing client id"}
    res = client.post("/v1/field-intelligence/sync/batch", json={"captures": [good, bad]}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["accepted"] == 1 and body["failed"] == 1


def test_correlation_source_mode_and_freshness_not_conflated(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    corr = _fetch(client, headers, obs_id)["correlation"]
    assert "source_mode_summary" in corr and "freshness_summary" in corr
    assert set(corr["source_mode_summary"].keys()) == {"live", "sample", "uploaded"}
    assert set(corr["freshness_summary"].keys()) == {"fresh", "stale", "unavailable"}


def test_correction_and_task_creation(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers, note_text="Broken valve, major leak on Block A").json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    patched = client.patch(
        f"/v1/field-intelligence/observations/{obs_id}",
        json={"corrected_transcript": "Broken valve confirmed", "severity": "high"}, headers=headers,
    )
    assert patched.status_code == 200
    assert "observation_corrected" in {e["action"] for e in patched.json()["observation"]["audit_history"]}
    task = client.post(f"/v1/field-intelligence/observations/{obs_id}/tasks", json={"title": "Repair valve"}, headers=headers)
    assert task.status_code == 200 and task.json()["task"]["title"] == "Repair valve"


def test_evidence_record_feeds_graph(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    records = db.query(EvidenceRecord).filter(EvidenceRecord.evidence_type == "field_observation").all()
    assert len(records) == 1
    assert (records[0].metadata_json or {}).get("observation_id") == obs_id
    assert records[0].id in _fetch(client, headers, obs_id)["evidence_ids"]


# ---- durable object storage ---------------------------------------------- #

def _spool_count():
    return len(glob.glob(f"{tempfile.gettempdir()}/agroai-field-*"))


def test_asset_upload_durable_no_object_storage_503(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    before = _spool_count()
    files = {"file": ("p.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 64), "image/png")}
    res = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                      files=files, data={"client_asset_id": "a1", "kind": "photo"}, headers=headers)
    assert res.status_code == 503  # never claims durability without R2/S3
    assert _spool_count() == before  # orphan-free even on the storage-unavailable path


def test_asset_upload_and_dedup_no_orphan(client, db, fake_store):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    png = b"\x89PNG\r\n\x1a\n" + b"1" * 128
    before = _spool_count()
    r1 = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                     files={"file": ("photo.png", io.BytesIO(png), "image/png")},
                     data={"client_asset_id": "asset-photo", "kind": "photo"}, headers=headers)
    assert r1.status_code == 200, r1.text
    # replay same client asset id -> deduped, no re-upload, no orphan spool
    r2 = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                     files={"file": ("photo.png", io.BytesIO(png), "image/png")},
                     data={"client_asset_id": "asset-photo", "kind": "photo"}, headers=headers)
    assert r1.json()["asset"]["id"] == r2.json()["asset"]["id"]
    assert _spool_count() == before  # no orphan temp files under dedupe
    assert len(fake_store.client.items) == 1  # stored exactly once


def test_asset_wrong_content_rejected_no_orphan(client, db, fake_store):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    before = _spool_count()
    res = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                      files={"file": ("data.csv", io.BytesIO(b"col1,col2\n1,2\n"), "text/csv")},
                      data={"client_asset_id": "asset-1", "kind": "audio"}, headers=headers)
    assert res.status_code == 415
    assert _spool_count() == before
    assert len(fake_store.client.items) == 0


def test_uploaded_audio_is_what_gets_transcribed(client, db, fake_store, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "fake")
    _, _, headers = _auth(db)
    # client manifest lies about the object ref; server must ignore it and use the DB row
    cap = _initiate(client, headers, capture_source="voice", note_text=None,
                    asset_manifest=[{"kind": "audio", "client_asset_id": "aud", "object_ref": "s3://evil/hacked"}]).json()["capture"]
    audio = b"OggS" + b"\x00" * 500  # 504 bytes of "audio"
    up = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                     files={"file": ("v.ogg", io.BytesIO(audio), "audio/ogg")},
                     data={"client_asset_id": "aud", "kind": "audio", "duration_seconds": "3"}, headers=headers)
    assert up.status_code == 200, up.text
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    obs = _fetch(client, headers, obs_id)
    assert obs["provenance"]["transcription_status"] == "completed"
    assert f"of {len(audio)} audio bytes" in obs["transcript"]  # real durable bytes, not manifest ref


def test_transcription_unavailable_without_provider(client, db, fake_store):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers, capture_source="voice", note_text=None).json()["capture"]
    audio = b"OggS" + b"\x00" * 100
    client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                files={"file": ("v.ogg", io.BytesIO(audio), "audio/ogg")},
                data={"client_asset_id": "aud", "kind": "audio"}, headers=headers)
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    obs = _fetch(client, headers, obs_id)
    assert obs["provenance"]["transcription_status"] == "unavailable"
    assert not obs["transcript"]


def test_failed_transcription_can_be_reprocessed(client, db, fake_store, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "fake_fail")
    _, _, headers = _auth(db)
    cap = _initiate(client, headers, capture_source="voice", note_text=None).json()["capture"]
    client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                files={"file": ("v.ogg", io.BytesIO(b"OggS" + b"0" * 50), "audio/ogg")},
                data={"client_asset_id": "aud", "kind": "audio"}, headers=headers)
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    obs = _fetch(client, headers, obs_id)
    assert obs["provenance"]["transcription_status"] == "failed"
    assert not obs["transcript"]
    # now a working provider + reprocess succeeds
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "fake")
    client.post(f"/v1/field-intelligence/observations/{obs_id}/reprocess", headers=headers)
    _process(db)
    assert _fetch(client, headers, obs_id)["provenance"]["transcription_status"] == "completed"


def test_deleted_observation_disables_asset_retrieval_and_removes_object(client, db, fake_store, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "fake")
    _, _, headers = _auth(db)
    cap = _initiate(client, headers, capture_source="voice", note_text=None).json()["capture"]
    up = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                     files={"file": ("v.ogg", io.BytesIO(b"OggS" + b"0" * 40), "audio/ogg")},
                     data={"client_asset_id": "aud", "kind": "audio"}, headers=headers)
    asset_id = up.json()["asset"]["id"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    # retrievable while live
    assert client.get(f"/v1/field-intelligence/assets/{asset_id}/content", headers=headers).status_code == 200
    assert len(fake_store.client.items) == 1
    # delete observation -> retrieval disabled + durable object removed
    assert client.delete(f"/v1/field-intelligence/observations/{obs_id}", headers=headers).status_code == 200
    got = client.get(f"/v1/field-intelligence/assets/{asset_id}/content", headers=headers)
    assert got.status_code in (404, 410)
    assert len(fake_store.client.items) == 0  # R2 object physically removed


def test_asset_retrieval_has_safe_headers(client, db, fake_store):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                files={"file": ("photo.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 32), "image/png")},
                data={"client_asset_id": "asset-photo", "kind": "photo"}, headers=headers)
    asset = client.get(f"/v1/field-intelligence/observations", headers=headers)  # warm
    # fetch the asset id via capture serialization
    from app.models.field_intelligence import FieldObservationAsset
    row = db.query(FieldObservationAsset).first()
    resp = client.get(f"/v1/field-intelligence/assets/{row.id}/content", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in resp.headers["content-disposition"]


def test_unauthenticated_rejected(client, db):
    assert client.get("/v1/field-intelligence/observations").status_code in (401, 403)
