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

    def put_object(self, Bucket, Key, Body, ContentType=None):
        body = Body if isinstance(Body, bytes) else bytes(Body)
        self.items[(Bucket, Key)] = (body, {})

    def list_objects_v2(self, Bucket, Prefix="", MaxKeys=1000, ContinuationToken=None):
        keys = sorted(k for (b, k) in self.items if b == Bucket and k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys[:MaxKeys]]}

    def head_object(self, Bucket, Key):
        body, metadata = self.items[(Bucket, Key)]
        return {"ContentLength": len(body), "Metadata": metadata}

    def get_object(self, Bucket, Key, Range=None):
        body, metadata = self.items[(Bucket, Key)]
        if Range:
            import re as _re
            m = _re.fullmatch(r"bytes=(\d+)-(\d+)", Range)
            if m:
                start, end = int(m.group(1)), int(m.group(2))
                body = body[start:end + 1]
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


def _ogg_crc_table() -> list[int]:
    table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if r & 0x80000000 else (r << 1) & 0xFFFFFFFF
        table.append(r)
    return table


_OGG_CRC_TABLE = _ogg_crc_table()


def _ogg_crc(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _OGG_CRC_TABLE[((crc >> 24) & 0xFF) ^ byte]
    return crc


def _ogg_opus(seconds: float = 3.0, pad: int = 64) -> bytes:
    """Synthesize a minimal, structurally valid Ogg Opus stream.

    Real media inspection (and the bounded ffprobe verifier) parses container
    tracks and checks page CRCs, so tests must upload genuinely valid
    containers: a BOS page with an OpusHead, an OpusTags page, and an EOS page
    whose granule position encodes the duration.
    """
    import struct as _struct

    def page(header_type: int, granule: int, seq: int, payload: bytes) -> bytes:
        lacing = []
        remaining = len(payload)
        while remaining >= 255:
            lacing.append(255)
            remaining -= 255
        lacing.append(remaining)
        raw = (
            b"OggS" + bytes([0, header_type]) + _struct.pack("<q", granule)
            + _struct.pack("<I", 1) + _struct.pack("<I", seq) + _struct.pack("<I", 0)
            + bytes([len(lacing)]) + bytes(lacing) + payload
        )
        return raw[:22] + _struct.pack("<I", _ogg_crc(raw)) + raw[26:]

    head = b"OpusHead" + bytes([1, 1]) + _struct.pack("<H", 0) + _struct.pack("<I", 48000) + _struct.pack("<h", 0) + b"\x00"
    tags = b"OpusTags" + _struct.pack("<I", 0) + _struct.pack("<I", 0)
    audio = b"\x00" * max(pad, 1)
    return page(0x02, 0, 0, head) + page(0x00, 0, 1, tags) + page(0x04, int(seconds * 48000), 2, audio)


def _ebml_el(element_id: int, payload: bytes) -> bytes:
    """Encode one EBML element (id bytes as-is, size as a marked vint)."""
    id_bytes = element_id.to_bytes((element_id.bit_length() + 7) // 8, "big")
    for length in range(1, 9):
        if len(payload) < (1 << (7 * length)) - 1:
            size = ((1 << (8 * length - length)) | len(payload)).to_bytes(length, "big")
            return id_bytes + size + payload
    raise ValueError("payload too large for EBML vint")


def _ebml_uint(value: int) -> bytes:
    return value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")


def _webm(actual_seconds: float, declared_seconds: float | None, *, video: bool = False) -> bytes:
    """Build a real, demuxable WebM.

    ``declared_seconds=None`` mirrors a MediaRecorder capture (no Duration
    element); a mismatching ``declared_seconds`` forges the header claim while
    the clusters carry ``actual_seconds`` of real packets.
    """
    import struct as _struct

    header = _ebml_el(
        0x1A45DFA3,
        _ebml_el(0x4286, _ebml_uint(1)) + _ebml_el(0x42F7, _ebml_uint(1))
        + _ebml_el(0x42F2, _ebml_uint(4)) + _ebml_el(0x42F3, _ebml_uint(8))
        + _ebml_el(0x4282, b"webm") + _ebml_el(0x4287, _ebml_uint(2)) + _ebml_el(0x4285, _ebml_uint(2)),
    )
    info_children = _ebml_el(0x2AD7B1, _ebml_uint(1_000_000))
    if declared_seconds is not None:
        info_children += _ebml_el(0x4489, _struct.pack(">d", declared_seconds * 1000.0))
    info = _ebml_el(0x1549A966, info_children)
    if video:
        track = _ebml_el(
            0xAE,
            _ebml_el(0xD7, _ebml_uint(1)) + _ebml_el(0x73C5, _ebml_uint(1)) + _ebml_el(0x83, _ebml_uint(1))
            + _ebml_el(0x86, b"V_VP8")
            + _ebml_el(0xE0, _ebml_el(0xB0, _ebml_uint(16)) + _ebml_el(0xBA, _ebml_uint(16))),
        )
    else:
        track = _ebml_el(
            0xAE,
            _ebml_el(0xD7, _ebml_uint(1)) + _ebml_el(0x73C5, _ebml_uint(1)) + _ebml_el(0x83, _ebml_uint(2))
            + _ebml_el(0x86, b"A_OPUS")
            + _ebml_el(0x63A2, b"OpusHead" + bytes([1, 1]) + _struct.pack("<H", 0)
                       + _struct.pack("<I", 48000) + _struct.pack("<h", 0) + b"\x00")
            + _ebml_el(0xE1, _ebml_el(0xB5, _struct.pack(">f", 48000.0)) + _ebml_el(0x9F, _ebml_uint(1))),
        )
    tracks = _ebml_el(0x1654AE6B, track)
    clusters = b""
    step_ms = 20 if not video else 40
    second = 0
    while second < actual_seconds:
        blocks = b""
        for ms in range(0, 1000, step_ms):
            if second + ms / 1000.0 >= actual_seconds:
                break
            blocks += _ebml_el(0xA3, b"\x81" + _struct.pack(">h", ms) + b"\x80" + b"\xfc\xff\xfe")
        clusters += _ebml_el(0x1F43B675, _ebml_el(0xE7, _ebml_uint(second * 1000)) + blocks)
        second += 1
    return header + _ebml_el(0x18538067, info + tracks + clusters)


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
    from app.services.field_intelligence_worker import drain_until_empty
    return drain_until_empty(db)


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
    # structurally valid but reuses the same key with a different payload -> per-item conflict
    conflict = {"client_capture_id": "b2", "idempotency_key": "b1", "note_text": "different content"}
    res = client.post("/v1/field-intelligence/sync/batch", json={"captures": [good, conflict]}, headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["accepted"] == 1 and body["failed"] == 1
    # a structurally invalid item (same model + constraints) rejects the batch
    malformed = client.post("/v1/field-intelligence/sync/batch",
                            json={"captures": [{"idempotency_key": "x", "note_text": "no client id"}]}, headers=headers)
    assert malformed.status_code == 422


def test_correlation_source_mode_and_freshness_not_conflated(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    corr = _fetch(client, headers, obs_id)["correlation"]
    assert "source_mode_summary" in corr and "freshness_summary" in corr
    assert {"live", "sample", "uploaded", "unavailable", "unknown"}.issubset(corr["source_mode_summary"].keys())
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
    # a manifest smuggling an object_ref (or any unknown key) is rejected outright
    sneaky = _initiate(client, headers, capture_source="voice", note_text=None,
                       asset_manifest=[{"kind": "audio", "client_asset_id": "aud",
                                        "content_type": "audio/ogg", "object_ref": "s3://evil/hacked"}])
    assert sneaky.status_code == 422
    cap = _initiate(client, headers, capture_source="voice", note_text=None,
                    asset_manifest=[{"kind": "audio", "client_asset_id": "aud", "content_type": "audio/ogg"}]).json()["capture"]
    audio = _ogg_opus(seconds=3.0, pad=500)
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
    audio = _ogg_opus(seconds=2.0, pad=100)
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
                files={"file": ("v.ogg", io.BytesIO(_ogg_opus(pad=50)), "audio/ogg")},
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
                     files={"file": ("v.ogg", io.BytesIO(_ogg_opus(pad=40)), "audio/ogg")},
                     data={"client_asset_id": "aud", "kind": "audio"}, headers=headers)
    asset_id = up.json()["asset"]["id"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    # retrievable while live
    assert client.get(f"/v1/field-intelligence/assets/{asset_id}/content", headers=headers).status_code == 200
    assert len(fake_store.client.items) == 1
    # delete observation -> retrieval disabled immediately (before worker runs)
    assert client.delete(f"/v1/field-intelligence/observations/{obs_id}", headers=headers).status_code == 200
    got = client.get(f"/v1/field-intelligence/assets/{asset_id}/content", headers=headers)
    assert got.status_code in (404, 410)
    assert len(fake_store.client.items) == 1  # not yet physically deleted (durable job pending)
    # worker performs the durable R2 deletion
    svc.run_field_intelligence_deletions(db)
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


# ---- item 2: complete idempotency fingerprint --------------------------- #

def test_idempotency_conflict_on_workspace_metadata_assignee_manifest(client, db):
    _, ws, headers = _auth(db)
    ws2 = Workspace(id="ws-fi-2", organization_id="org-fi", name="Second", crop="Grapes", region="CA", mode="live")
    db.add(ws2); db.commit()
    _initiate(client, headers, client_capture_id="cc", idempotency_key="k1", assignee="alice", metadata={"a": 1})
    # differing dimensions each conflict under the same key
    assert _initiate(client, headers, client_capture_id="cc", idempotency_key="k1", assignee="bob", metadata={"a": 1}).status_code == 409
    assert _initiate(client, headers, client_capture_id="cc", idempotency_key="k1", assignee="alice", metadata={"a": 2}).status_code == 409
    assert _initiate(client, headers, client_capture_id="cc", idempotency_key="k1", assignee="alice", metadata={"a": 1}, workspace_id="ws-fi-2").status_code == 409
    assert _initiate(client, headers, client_capture_id="cc", idempotency_key="k1", assignee="alice", metadata={"a": 1},
                     asset_manifest=[{"client_asset_id": "z", "kind": "photo", "content_type": "image/png"}]).status_code == 409
    # identical replay still returns the same capture
    again = _initiate(client, headers, client_capture_id="cc", idempotency_key="k1", assignee="alice", metadata={"a": 1})
    assert again.status_code == 200


# ---- item 3: strict asset idempotency ----------------------------------- #

def test_asset_idempotency_conflict(client, db, fake_store):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    png1 = b"\x89PNG\r\n\x1a\n" + b"A" * 40
    png2 = b"\x89PNG\r\n\x1a\n" + b"B" * 80
    r1 = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                     files={"file": ("p.png", io.BytesIO(png1), "image/png")},
                     data={"client_asset_id": "same", "kind": "photo"}, headers=headers)
    assert r1.status_code == 200
    # same id, different content -> conflict (does not silently discard)
    r2 = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                     files={"file": ("p.png", io.BytesIO(png2), "image/png")},
                     data={"client_asset_id": "same", "kind": "photo"}, headers=headers)
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "asset_idempotency_conflict"
    # same id, same content -> idempotent replay
    r3 = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                     files={"file": ("p.png", io.BytesIO(png1), "image/png")},
                     data={"client_asset_id": "same", "kind": "photo"}, headers=headers)
    assert r3.status_code == 200 and r3.json()["asset"]["id"] == r1.json()["asset"]["id"]


# ---- item 4: compensating upload leaves no orphan R2 object ------------- #

def _real_ctx(db, org_id="org-fi", user_id="user-org-fi"):
    from app.api.deps import AuthContext
    user = db.get(User, user_id)
    org = db.get(Organization, org_id)
    membership = (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.organization_id == org_id, OrganizationMembership.user_id == user_id)
        .first()
    )
    return AuthContext(user=user, organization=org, membership=membership)


def test_compensating_upload_deletes_orphan_on_registration_failure(client, db, fake_store, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    from app.services import field_intelligence as s

    Ctx = lambda: _real_ctx(db)  # noqa: E731
    real_commit = db.commit

    def boom_commit():
        raise IntegrityError("insert", {}, Exception("dup"))
    monkeypatch.setattr(db, "commit", boom_commit)
    spool = __import__("tempfile").NamedTemporaryFile(prefix="agroai-field-", delete=False)
    spool.write(b"\x89PNG\r\n\x1a\n" + b"C" * 32); spool.flush(); spool.close()
    import hashlib
    sha = hashlib.sha256(open(spool.name, "rb").read()).hexdigest()
    with __import__("pytest").raises(Exception):
        s.register_asset(db, Ctx(), cap["id"], client_asset_id="race", kind="photo", content_type="image/png",
                         filename="p.png", content_sha256=sha, size_bytes=41, duration_seconds=None, spool_path=spool.name)
    monkeypatch.setattr(db, "commit", real_commit)
    db.rollback()
    assert len(fake_store.client.items) == 0  # uploaded object was compensated (no orphan)
    __import__("os").unlink(spool.name)


# ---- item 5: durable deletion never confirms without physical delete ---- #

def test_deletion_stays_pending_until_storage_confirms(client, db, fake_store, monkeypatch):
    from app.models.field_intelligence import FieldObservationAsset
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    up = client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                     files={"file": ("p.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"D" * 32), "image/png")},
                     data={"client_asset_id": "a", "kind": "photo"}, headers=headers)
    asset_id = up.json()["asset"]["id"]
    assert client.delete(f"/v1/field-intelligence/assets/{asset_id}", headers=headers).status_code == 200
    # storage unavailable -> object cannot be confirmed deleted -> stays pending
    monkeypatch.setattr(svc, "object_storage_configured", lambda: False)
    svc.run_field_intelligence_deletions(db)
    db.expire_all()
    assert db.get(FieldObservationAsset, asset_id).status == "pending_deletion"
    assert len(fake_store.client.items) == 1  # never claimed deleted without confirmation
    # storage back -> worker confirms + marks deleted (clear the retry backoff window)
    from app.models.operational_records import IngestionJob
    job = db.query(IngestionJob).filter(IngestionJob.job_type == "field_intelligence_asset_delete").first()
    job.next_attempt_at = datetime.utcnow()
    db.commit()
    monkeypatch.setattr(svc, "object_storage_configured", lambda: True)
    svc.run_field_intelligence_deletions(db)
    db.expire_all()
    assert db.get(FieldObservationAsset, asset_id).status == "deleted"
    assert len(fake_store.client.items) == 0


# ---- item 6: append-only audit ------------------------------------------ #

def test_append_only_audit_events(client, db):
    from app.models.field_intelligence import FieldObservationAuditEvent
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    rows = db.query(FieldObservationAuditEvent).filter(FieldObservationAuditEvent.observation_id == obs_id).all()
    actions = {r.action for r in rows}
    assert {"capture_created", "extraction_completed", "correlation_completed", "evidence_linked"}.issubset(actions)
    before = len(rows)
    client.patch(f"/v1/field-intelligence/observations/{obs_id}", json={"severity": "high"}, headers=headers)
    after = db.query(FieldObservationAuditEvent).filter(FieldObservationAuditEvent.observation_id == obs_id).count()
    assert after > before  # append-only: events only ever added


# ---- item 7: retryable transcription auto-retries ----------------------- #

def test_retryable_transcription_does_not_complete_job(client, db, fake_store, monkeypatch):
    from app.services import field_transcription as ft
    from app.models.operational_records import IngestionJob
    ft.reset_fake_retry_state()
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "fake_retry")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_FAKE_RETRY_FAILS", 1)
    _, _, headers = _auth(db)
    cap = _initiate(client, headers, capture_source="voice", note_text=None).json()["capture"]
    client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                files={"file": ("v.ogg", io.BytesIO(_ogg_opus(pad=40)), "audio/ogg")},
                data={"client_asset_id": "aud", "kind": "audio"}, headers=headers)
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)  # first attempt fails retryably; job must NOT complete
    assert _fetch(client, headers, obs_id)["status"] not in {"completed", "needs_review"}
    job = db.query(IngestionJob).filter(IngestionJob.job_type == "field_intelligence_process").first()
    assert job.status == "queued" and job.attempt_count >= 1
    # simulate backoff elapsed -> second attempt succeeds
    job.next_attempt_at = datetime.utcnow()
    db.commit()
    _process(db)
    assert _fetch(client, headers, obs_id)["provenance"]["transcription_status"] == "completed"


# ---- item 8: worker drains a 50-item batch without more traffic --------- #

def test_worker_drains_50_item_batch(client, db):
    _, _, headers = _auth(db)
    captures = [{"client_capture_id": f"c{i}", "idempotency_key": f"c{i}", "note_text": f"Note {i} on Block A"} for i in range(50)]
    res = client.post("/v1/field-intelligence/sync/batch", json={"captures": captures}, headers=headers)
    assert res.json()["accepted"] == 50
    from app.services.field_intelligence_worker import drain_until_empty
    drain_until_empty(db)  # the scheduled worker, driven directly (no user traffic)
    rows = client.get("/v1/field-intelligence/observations?limit=500", headers=headers).json()["observations"]
    assert len(rows) == 50
    assert all(o["status"] in {"completed", "needs_review"} for o in rows)


# ---- item 12: PATCH cannot reach destructive/internal status ------------ #

def test_patch_status_deleted_rejected(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    r = client.patch(f"/v1/field-intelligence/observations/{obs_id}", json={"status": "deleted"}, headers=headers)
    assert r.status_code in (400, 422)
    # observation is still present (not bypass-deleted)
    assert client.get(f"/v1/field-intelligence/observations/{obs_id}", headers=headers).status_code == 200


# ---- item 13: untranscribed blank recording is not usable evidence ------ #

def test_blank_recording_not_usable_evidence(client, db, fake_store):
    from app.models.operational_records import EvidenceRecord
    _, _, headers = _auth(db)
    cap = _initiate(client, headers, capture_source="voice", note_text=None).json()["capture"]
    client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                files={"file": ("v.ogg", io.BytesIO(_ogg_opus(pad=30)), "audio/ogg")},
                data={"client_asset_id": "aud", "kind": "audio"}, headers=headers)
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)  # disabled provider -> unavailable, no confirmed text
    rec = db.query(EvidenceRecord).filter(EvidenceRecord.evidence_type == "field_observation").first()
    assert rec is not None
    assert rec.quality_status == "unusable"
    assert rec.confidence == 0.0  # actual 0.0 preserved, never coerced to 0.5


# ---- item 14: correction reprocesses downstream ------------------------- #

def test_correction_enqueues_reprocess(client, db):
    from app.models.operational_records import IngestionJob
    _, _, headers = _auth(db)
    cap = _initiate(client, headers, note_text="vague").json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    client.patch(f"/v1/field-intelligence/observations/{obs_id}",
                 json={"corrected_transcript": "Irrigation ran 30 minutes applied 900 gallons on Block A"}, headers=headers)
    jobs = db.query(IngestionJob).filter(IngestionJob.job_type == "field_intelligence_process").all()
    active = [j for j in jobs if j.status in ("queued", "running") and (j.input_json or {}).get("observation_id") == obs_id]
    assert len(active) == 1  # exactly one active reprocess (deduped)
    _process(db)
    obs = _fetch(client, headers, obs_id)
    assert "reprocess_requested" in {e["action"] for e in obs["audit_history"]}
    assert obs["structured"]["applied_water_gallons"] == 900  # refreshed extraction


# ---- item 15: streaming range retrieval --------------------------------- #

def test_asset_range_retrieval(client, db, fake_store):
    from app.models.field_intelligence import FieldObservationAsset
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    payload = b"\x89PNG\r\n\x1a\n" + bytes(range(0, 200)) [:120]
    client.post(f"/v1/field-intelligence/captures/{cap['id']}/assets",
                files={"file": ("p.png", io.BytesIO(payload), "image/png")},
                data={"client_asset_id": "a", "kind": "photo"}, headers=headers)
    row = db.query(FieldObservationAsset).first()
    resp = client.get(f"/v1/field-intelligence/assets/{row.id}/content", headers={**headers, "Range": "bytes=0-9"})
    assert resp.status_code == 206
    assert resp.headers["content-range"].startswith("bytes 0-9/")
    assert resp.headers["accept-ranges"] == "bytes"
    assert len(resp.content) == 10


# ---- item 11: same-org / different-workspace isolation ------------------ #

def test_workspace_isolation_same_org(client, db):
    _, ws1, headers = _auth(db)
    ws2 = Workspace(id="ws-iso-2", organization_id="org-fi", name="W2", crop="Grapes", region="CA", mode="live")
    db.add(ws2); db.commit()
    cap = _initiate(client, headers, workspace_id=ws1.id).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    in_ws2 = client.get(f"/v1/field-intelligence/observations?workspace_id={ws2.id}", headers=headers).json()
    assert all(o["id"] != obs_id for o in in_ws2["observations"])  # ws1 observation not visible under ws2
