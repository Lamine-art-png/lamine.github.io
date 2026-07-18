"""Regression coverage for the fourth Field Intelligence hardening pass.

Covers:
* unusable / unconfirmed evidence exclusion from AGRO-AI consumers (item 2)
* retry-attempt provenance persisted across rollback (item 3)
* durable asset-upload compensation with orphan cleanup (item 4)
* shared-object deletion race -> exactly one physical delete (item 5)
* backend job lease heartbeats during slow processing (item 6)
* workspace-access + role enforcement on direct-ID routes (item 7)
* server-side commercial capability + storage quota enforcement (item 8)
* full evidence refresh after transcript correction (item 12)
"""
from __future__ import annotations

import io
import threading
import time
from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.models.field_intelligence import (
    FieldObservation,
    FieldObservationAsset,
    FieldObservationAuditEvent,
    FieldObservationProcessingRun,
)
from app.models.operational_records import EvidenceRecord, IngestionJob
from app.models.saas import EntitlementOverride, Organization, OrganizationMembership, User, Workspace
from app.services import field_intelligence as svc
from app.services.object_storage import S3ObjectStore

from tests.unit.test_field_intelligence import (  # reuse the shared harness
    FakeStoreClient,
    _auth,
    _complete,
    _initiate,
    _process,
    _real_ctx,
)


@pytest.fixture
def fake_store(monkeypatch):
    client = FakeStoreClient()
    store = S3ObjectStore(bucket="agroai-test", prefix="agroai", client=client)
    monkeypatch.setattr(svc, "get_object_store", lambda **_: store)
    monkeypatch.setattr(svc, "object_storage_configured", lambda: True)
    return store


def _upload(client, headers, cap_id, *, client_asset_id="a1", kind="photo", body=None, filename="p.png",
            content_type="image/png"):
    body = body if body is not None else b"\x89PNG\r\n\x1a\n" + b"0" * 64
    return client.post(
        f"/v1/field-intelligence/captures/{cap_id}/assets",
        files={"file": (filename, io.BytesIO(body), content_type)},
        data={"client_asset_id": client_asset_id, "kind": kind},
        headers=headers,
    )


# --------------------------------------------------------------------------- #
# Item 2 — unusable evidence must not reach AGRO-AI consumers
# --------------------------------------------------------------------------- #

def test_blank_recording_absent_from_cockpit_and_ask_context(client, db, fake_store):
    from app.services.operator_cockpit import build_context, report_factory
    org, _, headers = _auth(db)
    cap = _initiate(client, headers, capture_source="voice", note_text=None).json()["capture"]
    _upload(client, headers, cap["id"], client_asset_id="aud", kind="audio",
            body=b"OggS" + b"\x00" * 40, filename="v.ogg", content_type="audio/ogg")
    _complete(client, headers, cap["id"])
    _process(db)  # no transcription provider -> blank, unusable evidence

    record = db.query(EvidenceRecord).filter(EvidenceRecord.evidence_type == "field_observation").one()
    assert record.quality_status == "unusable"

    # Default cockpit context (Ask AGRO-AI, Reports, Readiness, Decision
    # Workbench, citations all consume it) excludes the unusable record.
    ctx = build_context(db, org.id)
    assert all(row.id != record.id for row in ctx.evidence)
    report = report_factory(ctx, report_type="executive_brief")
    appendix_ids = {row.get("id") for row in report.get("evidence_appendix", [])}
    assert record.id not in appendix_ids

    # Review-mode consumers can opt in and must see the quality status.
    review_ctx = build_context(db, org.id, include_unusable=True)
    included = [row for row in review_ctx.evidence if row.id == record.id]
    assert included and included[0].quality_status == "unusable"


def test_blank_recording_absent_from_ask_agro_ai_intelligence_context(client, db, fake_store):
    from app.services.intelligence_context import build_intelligence_context
    org, _, headers = _auth(db)
    cap = _initiate(client, headers, capture_source="voice", note_text=None).json()["capture"]
    _upload(client, headers, cap["id"], client_asset_id="aud", kind="audio",
            body=b"OggS" + b"\x00" * 40, filename="v.ogg", content_type="audio/ogg")
    _complete(client, headers, cap["id"])
    _process(db)

    record = db.query(EvidenceRecord).filter(EvidenceRecord.evidence_type == "field_observation").one()
    context = build_intelligence_context(db=db, tenant_id=org.id)
    evidence_ids = {row.get("id") for row in context["evidence_context"].evidence if isinstance(row, dict)}
    assert record.id not in evidence_ids
    citation_ids = {c.source_id for c in context["citations"]}
    assert record.id not in citation_ids


def test_usable_evidence_present_in_ask_context_with_quality_status(client, db, fake_store):
    from app.services.intelligence_context import build_intelligence_context
    org, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    _complete(client, headers, cap["id"])
    _process(db)
    record = db.query(EvidenceRecord).filter(EvidenceRecord.evidence_type == "field_observation").one()
    assert record.quality_status in {"usable", "needs_review"}
    context = build_intelligence_context(db=db, tenant_id=org.id)
    rows = [row for row in context["evidence_context"].evidence
            if isinstance(row, dict) and row.get("id") == record.id]
    assert rows and rows[0]["quality_status"] == record.quality_status


def test_correlation_ignores_unusable_evidence(client, db, fake_store):
    org, _, headers = _auth(db)
    # Seed an unusable evidence record in the correlation window.
    db.add(EvidenceRecord(
        id="ev-unusable", tenant_id=org.id, evidence_type="telemetry", title="Blank capture",
        summary="", confidence=0.0, quality_status="unusable", occurred_at=datetime.utcnow(),
        citation_label="Blank capture",
    ))
    db.commit()
    cap = _initiate(client, headers).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    obs = db.get(FieldObservation, obs_id)
    related = {row["evidence_id"] for row in (obs.correlation_json or {}).get("related_evidence", [])}
    assert "ev-unusable" not in related


# --------------------------------------------------------------------------- #
# Item 12 — transcript correction fully refreshes the evidence record
# --------------------------------------------------------------------------- #

def test_transcript_correction_fully_refreshes_evidence(client, db):
    from app.services.intelligence_context import build_intelligence_context
    org, _, headers = _auth(db)
    original = "Irrigation ran 45 minutes on Block A, applied 1200 gallons."
    cap = _initiate(client, headers, note_text=original).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)

    corrected = "Fertilizer application of 300 pounds on Block B completed."
    res = client.patch(
        f"/v1/field-intelligence/observations/{obs_id}",
        json={"corrected_transcript": corrected, "field_name": "South Ranch", "block_name": "Block B"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    _process(db)  # correction re-runs the pipeline

    record = db.query(EvidenceRecord).filter(EvidenceRecord.evidence_type == "field_observation").one()
    obs = db.get(FieldObservation, obs_id)
    assert record.source_excerpt == corrected
    assert "45 minutes" not in (record.source_excerpt or "")
    assert "45 minutes" not in (record.summary or "")
    assert record.title.startswith("South Ranch")
    assert record.field_id == obs.field_id
    assert record.block_id == obs.block_id
    assert record.occurred_at == obs.occurred_at
    assert record.confidence == obs.confidence
    assert record.value_json == (obs.structured_json or {})
    assert (record.metadata_json or {}).get("provenance") == obs.provenance_json
    assert record.quality_status in {"usable", "needs_review"}

    # Ask AGRO-AI sees only the corrected text.
    context = build_intelligence_context(db=db, tenant_id=org.id)
    rows = [row for row in context["evidence_context"].evidence
            if isinstance(row, dict) and row.get("id") == record.id]
    assert rows
    assert corrected[:50] in (rows[0].get("source_excerpt") or "")
    assert "45 minutes" not in (rows[0].get("source_excerpt") or "")
    assert "45 minutes" not in (rows[0].get("summary") or "")


def test_non_transcript_patch_refreshes_evidence_metadata(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    client.patch(
        f"/v1/field-intelligence/observations/{obs_id}",
        json={"field_name": "Renamed Ranch", "severity": "high"}, headers=headers,
    )
    record = db.query(EvidenceRecord).filter(EvidenceRecord.evidence_type == "field_observation").one()
    assert record.title.startswith("Renamed Ranch")
    assert record.quality_status != "unusable"  # typed note text still counts as confirmed


# --------------------------------------------------------------------------- #
# Item 3 — retry-attempt provenance survives the rollback
# --------------------------------------------------------------------------- #

def test_retry_attempt_provenance_persisted(client, db, fake_store, monkeypatch):
    from app.services import field_transcription as ft
    ft.reset_fake_retry_state()
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "fake_retry")
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_FAKE_RETRY_FAILS", 1)
    _, _, headers = _auth(db)
    cap = _initiate(client, headers, capture_source="voice", note_text=None).json()["capture"]
    _upload(client, headers, cap["id"], client_asset_id="aud", kind="audio",
            body=b"OggS" + b"\x00" * 40, filename="v.ogg", content_type="audio/ogg")
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    _process(db)  # first attempt fails retryably and is requeued

    runs = (
        db.query(FieldObservationProcessingRun)
        .filter(FieldObservationProcessingRun.observation_id == obs_id)
        .filter(FieldObservationProcessingRun.stage == "transcription")
        .filter(FieldObservationProcessingRun.status == "failed")
        .all()
    )
    assert runs, "the attempted transcription run must survive the rollback"
    failed = runs[0]
    assert failed.provider == "fake_retry"
    assert failed.attempt_count >= 1
    assert failed.output_json.get("disposition") == "retryable"
    assert failed.output_json.get("retryable") is True
    assert failed.output_json.get("http_classification") == "http_503_retryable"
    assert failed.error and "503" in failed.error

    audits = (
        db.query(FieldObservationAuditEvent)
        .filter(FieldObservationAuditEvent.observation_id == obs_id)
        .filter(FieldObservationAuditEvent.action == "processing_attempt_failed")
        .all()
    )
    assert audits and audits[0].details_json.get("stage") == "transcription"

    # backoff elapsed -> retry succeeds and provenance of both attempts remains
    job = db.query(IngestionJob).filter(IngestionJob.job_type == "field_intelligence_process").first()
    job.next_attempt_at = datetime.utcnow()
    db.commit()
    _process(db)
    statuses = {
        run.status
        for run in db.query(FieldObservationProcessingRun)
        .filter(FieldObservationProcessingRun.observation_id == obs_id)
        .filter(FieldObservationProcessingRun.stage == "transcription")
        .all()
    }
    assert statuses == {"failed", "completed"}


def test_terminal_attempt_records_terminal_disposition(client, db):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]
    job = db.query(IngestionJob).filter(IngestionJob.job_type == "field_intelligence_process").first()
    job.attempt_count = job.max_attempts
    db.commit()
    svc._fail_or_retry(db, job.id, RuntimeError("pipeline exploded"))
    run = (
        db.query(FieldObservationProcessingRun)
        .filter(FieldObservationProcessingRun.observation_id == obs_id)
        .filter(FieldObservationProcessingRun.status == "failed")
        .one()
    )
    assert run.output_json.get("disposition") == "terminal"
    assert db.get(FieldObservation, obs_id).status == "failed"
    assert db.get(IngestionJob, job.id).status == "failed"


# --------------------------------------------------------------------------- #
# Item 4 — durable compensation: R2 ok, DB fails, compensation fails once,
# cleanup worker later removes the object
# --------------------------------------------------------------------------- #

def test_failed_compensation_stages_orphan_cleanup_and_worker_removes_object(client, db, fake_store, monkeypatch):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    ctx = _real_ctx(db)

    # DB registration fails once (a non-IntegrityError database failure).
    real_commit = db.commit
    state = {"fail_commits": 1, "fail_deletes": 1}

    def flaky_commit():
        if state["fail_commits"] > 0:
            state["fail_commits"] -= 1
            raise RuntimeError("db_connection_lost")
        return real_commit()

    real_delete = fake_store.client.delete_object

    def flaky_delete(Bucket, Key):
        if state["fail_deletes"] > 0:
            state["fail_deletes"] -= 1
            raise RuntimeError("r2_delete_unavailable")
        return real_delete(Bucket, Key)

    monkeypatch.setattr(db, "commit", flaky_commit)
    monkeypatch.setattr(fake_store.client, "delete_object", flaky_delete)

    import hashlib as _hashlib, tempfile as _tempfile
    body = b"\x89PNG\r\n\x1a\n" + b"Z" * 32
    spool = _tempfile.NamedTemporaryFile(prefix="agroai-field-", delete=False)
    spool.write(body); spool.flush(); spool.close()
    with pytest.raises(RuntimeError):
        svc.register_asset(
            db, ctx, cap["id"], client_asset_id="orphan", kind="photo", content_type="image/png",
            filename="p.png", content_sha256=_hashlib.sha256(body).hexdigest(),
            size_bytes=len(body), duration_seconds=None, spool_path=spool.name,
        )
    monkeypatch.setattr(db, "commit", real_commit)

    # Upload happened, compensation failed once -> object still there, cleanup staged.
    assert len(fake_store.client.items) == 1
    jobs = db.query(IngestionJob).filter(IngestionJob.job_type == svc.ORPHAN_CLEANUP_JOB_TYPE).all()
    assert len(jobs) == 1, "a durable orphan-cleanup job must be staged when compensation fails"

    # The cleanup worker later removes the object (idempotently).
    result = svc.run_field_intelligence_orphan_cleanup(db)
    assert result["cleaned"] == 1
    assert len(fake_store.client.items) == 0
    assert db.get(IngestionJob, jobs[0].id).status == "completed"
    # replay is a no-op
    assert svc.run_field_intelligence_orphan_cleanup(db)["cleaned"] == 0


def test_orphan_cleanup_leaves_referenced_objects_alone(client, db, fake_store):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    up = _upload(client, headers, cap["id"])
    assert up.status_code == 200
    asset = db.query(FieldObservationAsset).one()
    svc._stage_orphan_cleanup_job(db, asset.tenant_id, asset.capture_session_id, asset.object_ref)
    result = svc.run_field_intelligence_orphan_cleanup(db)
    assert result["cleaned"] == 1  # job completes but the live object is preserved
    assert len(fake_store.client.items) == 1


# --------------------------------------------------------------------------- #
# Item 5 — concurrent deletion of assets sharing one object_ref
# --------------------------------------------------------------------------- #

def test_shared_object_concurrent_deletion_exactly_one_physical_delete(client, db, fake_store, monkeypatch):
    _, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    body = b"\x89PNG\r\n\x1a\n" + b"S" * 64
    r1 = _upload(client, headers, cap["id"], client_asset_id="s1", body=body)
    r2 = _upload(client, headers, cap["id"], client_asset_id="s2", body=body)
    assert r1.status_code == 200 and r2.status_code == 200
    a1, a2 = r1.json()["asset"]["id"], r2.json()["asset"]["id"]
    assert a1 != a2
    rows = {row.id: row for row in db.query(FieldObservationAsset).all()}
    assert rows[a1].object_ref == rows[a2].object_ref  # dedupe shares the object
    assert len(fake_store.client.items) == 1

    assert client.delete(f"/v1/field-intelligence/assets/{a1}", headers=headers).status_code == 200
    assert client.delete(f"/v1/field-intelligence/assets/{a2}", headers=headers).status_code == 200

    delete_calls = []
    real_delete = fake_store.client.delete_object

    def slow_counted_delete(Bucket, Key):
        delete_calls.append((Bucket, Key))
        time.sleep(0.05)  # widen the race window
        return real_delete(Bucket, Key)

    monkeypatch.setattr(fake_store.client, "delete_object", slow_counted_delete)

    SessionFactory = sessionmaker(bind=db.get_bind())
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def worker(name):
        session = SessionFactory()
        try:
            barrier.wait(timeout=5)
            svc.run_field_intelligence_deletions(session, worker_id=name)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors

    db.expire_all()
    assert len(delete_calls) == 1, f"exactly one physical deletion expected, got {len(delete_calls)}"
    assert len(fake_store.client.items) == 0
    assert db.get(FieldObservationAsset, a1).status == "deleted"
    assert db.get(FieldObservationAsset, a2).status == "deleted"
    jobs = db.query(IngestionJob).filter(IngestionJob.job_type == svc.ASSET_DELETE_JOB_TYPE).all()
    assert all(job.status == "completed" for job in jobs)


# --------------------------------------------------------------------------- #
# Item 6 — job lease heartbeat during processing beyond PROCESS_LEASE_SECONDS
# --------------------------------------------------------------------------- #

def test_lease_heartbeat_prevents_reclaim_during_slow_processing(client, db, fake_store, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.FIELD_TRANSCRIPTION_PROVIDER", "fake")
    monkeypatch.setattr(svc, "PROCESS_LEASE_SECONDS", 1)
    _, _, headers = _auth(db)
    cap = _initiate(client, headers, capture_source="voice", note_text=None).json()["capture"]
    _upload(client, headers, cap["id"], client_asset_id="aud", kind="audio",
            body=b"OggS" + b"\x00" * 40, filename="v.ogg", content_type="audio/ogg")
    obs_id = _complete(client, headers, cap["id"]).json()["observation"]["id"]

    real_transcribe = svc.transcribe_audio

    def slow_transcribe(**kwargs):
        time.sleep(2.5)  # well past PROCESS_LEASE_SECONDS
        return real_transcribe(**kwargs)

    monkeypatch.setattr(svc, "transcribe_audio", slow_transcribe)

    results = {}

    def run_worker_a():
        results["a"] = svc.run_field_intelligence_jobs(db, worker_id="worker-a")

    thread = threading.Thread(target=run_worker_a)
    thread.start()
    time.sleep(1.6)  # original lease would have expired without heartbeats

    SessionFactory = sessionmaker(bind=db.get_bind())
    session_b = SessionFactory()
    try:
        results["b"] = svc.run_field_intelligence_jobs(session_b, worker_id="worker-b")
    finally:
        session_b.close()
    thread.join(timeout=30)

    assert results["b"]["processed"] == 0 and results["b"]["failed"] == 0, \
        "a second worker must not reclaim a heartbeating job"
    assert results["a"]["processed"] == 1
    db.expire_all()
    job = db.query(IngestionJob).filter(IngestionJob.job_type == "field_intelligence_process").one()
    assert job.status == "completed"
    assert job.last_heartbeat_at is not None
    obs = db.get(FieldObservation, obs_id)
    assert obs.status in {"completed", "needs_review"}
    runs = db.query(FieldObservationProcessingRun).filter(
        FieldObservationProcessingRun.observation_id == obs_id,
        FieldObservationProcessingRun.stage == "transcription",
        FieldObservationProcessingRun.status == "completed",
    ).count()
    assert runs == 1, "the job must be processed exactly once"


# --------------------------------------------------------------------------- #
# Item 7 — workspace access + roles on direct-ID routes
# --------------------------------------------------------------------------- #

def _same_org_member(db, org_id, *, email, role):
    user = User(
        id=f"user-{email}", email=email, name=email, password_hash="test",
        email_verification_status="verified", email_verified_at=datetime.utcnow(),
    )
    db.add(user)
    db.add(OrganizationMembership(organization_id=org_id, user_id=user.id, role=role))
    db.commit()
    token = create_access_token({"sub": user.id, "tenant_id": org_id, "org_id": org_id, "role": role})
    return {"Authorization": f"Bearer {token}"}


def test_viewer_role_denied_on_direct_id_mutations(client, db, fake_store):
    org, ws, owner_headers = _auth(db)
    viewer_headers = _same_org_member(db, org.id, email="viewer@example.com", role="viewer")
    cap = _initiate(client, owner_headers, workspace_id=ws.id).json()["capture"]
    up = _upload(client, owner_headers, cap["id"])
    asset_id = up.json()["asset"]["id"]
    obs_id = _complete(client, owner_headers, cap["id"]).json()["observation"]["id"]
    _process(db)

    # same-org viewer can read...
    assert client.get(f"/v1/field-intelligence/observations/{obs_id}", headers=viewer_headers).status_code == 200
    # ...but every direct-ID mutation is denied server-side.
    assert client.patch(f"/v1/field-intelligence/observations/{obs_id}",
                        json={"severity": "high"}, headers=viewer_headers).status_code == 403
    assert client.post(f"/v1/field-intelligence/observations/{obs_id}/reprocess",
                       headers=viewer_headers).status_code == 403
    assert client.post(f"/v1/field-intelligence/observations/{obs_id}/tasks",
                       json={"title": "x"}, headers=viewer_headers).status_code == 403
    assert client.delete(f"/v1/field-intelligence/observations/{obs_id}",
                         headers=viewer_headers).status_code == 403
    assert client.delete(f"/v1/field-intelligence/assets/{asset_id}",
                         headers=viewer_headers).status_code == 403
    # viewers cannot create captures either
    denied = _initiate(client, viewer_headers, client_capture_id="cv", idempotency_key="cv")
    assert denied.status_code == 403
    # nothing was mutated
    db.expire_all()
    assert db.get(FieldObservation, obs_id).status != "deleted"
    assert db.get(FieldObservationAsset, asset_id).status == "stored"


def test_operator_can_write_but_not_destroy(client, db, fake_store):
    org, ws, owner_headers = _auth(db)
    op_headers = _same_org_member(db, org.id, email="op@example.com", role="operator")
    cap = _initiate(client, op_headers, workspace_id=ws.id).json()["capture"]
    obs_id = _complete(client, op_headers, cap["id"]).json()["observation"]["id"]
    _process(db)
    assert client.patch(f"/v1/field-intelligence/observations/{obs_id}",
                        json={"severity": "high"}, headers=op_headers).status_code == 200
    # destructive actions require owner/admin
    assert client.delete(f"/v1/field-intelligence/observations/{obs_id}", headers=op_headers).status_code == 403
    assert client.delete(f"/v1/field-intelligence/observations/{obs_id}", headers=owner_headers).status_code == 200


def test_foreign_workspace_direct_id_access_denied(client, db):
    """A user whose organization does not own the record's workspace is denied
    on the direct-ID route even though list filtering never runs."""
    org_a, ws_a, headers_a = _auth(db, email="wa@example.com", org_id="org-wa", workspace_id="ws-wa")
    _org_b, _ws_b, headers_b = _auth(db, email="wb@example.com", org_id="org-wb", workspace_id="ws-wb")
    cap = _initiate(client, headers_a, workspace_id=ws_a.id).json()["capture"]
    obs_id = _complete(client, headers_a, cap["id"]).json()["observation"]["id"]
    _process(db)
    assert client.get(f"/v1/field-intelligence/observations/{obs_id}", headers=headers_b).status_code == 404
    assert client.patch(f"/v1/field-intelligence/observations/{obs_id}",
                        json={"severity": "high"}, headers=headers_b).status_code == 404
    assert client.get(f"/v1/field-intelligence/captures/{cap['id']}", headers=headers_b).status_code == 404


# --------------------------------------------------------------------------- #
# Item 8 — server-side commercial capabilities and quotas
# --------------------------------------------------------------------------- #

def _lock_feature(db, org_id, feature_key, value):
    db.add(EntitlementOverride(organization_id=org_id, feature_key=feature_key, value_json={"value": value}))
    db.commit()


def test_voice_capability_enforced_server_side(client, db):
    org, _, headers = _auth(db)
    _lock_feature(db, org.id, "field_intelligence.voice", "locked")
    res = _initiate(client, headers, capture_source="voice", note_text=None)
    assert res.status_code == 402
    assert res.json()["detail"]["feature"] == "field_intelligence.voice"
    # typed capture still allowed
    ok = _initiate(client, headers, client_capture_id="c2", idempotency_key="c2")
    assert ok.status_code == 200


def test_offline_sync_capability_enforced_server_side(client, db):
    org, _, headers = _auth(db)
    _lock_feature(db, org.id, "field_intelligence.offline_sync", "locked")
    res = client.post("/v1/field-intelligence/sync/batch",
                      json={"captures": [{"client_capture_id": "s1", "idempotency_key": "s1", "note_text": "x"}]},
                      headers=headers)
    assert res.status_code == 402
    assert res.json()["detail"]["feature"] == "field_intelligence.offline_sync"


def test_map_capability_enforced_server_side(client, db):
    org, _, headers = _auth(db)
    _lock_feature(db, org.id, "field_intelligence.map", "locked")
    res = client.get("/v1/field-intelligence/map", headers=headers)
    assert res.status_code == 402


def test_capture_capability_enforced_server_side(client, db):
    org, _, headers = _auth(db)
    _lock_feature(db, org.id, "field_intelligence.capture", "locked")
    assert _initiate(client, headers).status_code == 402


def test_storage_quota_enforced_before_upload(client, db, fake_store):
    org, _, headers = _auth(db)
    cap = _initiate(client, headers).json()["capture"]
    _lock_feature(db, org.id, "quota.field_intelligence.storage_mb", 0)
    res = _upload(client, headers, cap["id"])
    assert res.status_code == 402
    assert res.json()["detail"]["code"] == "storage_quota_exceeded"
    assert len(fake_store.client.items) == 0  # rejected before any durable write
