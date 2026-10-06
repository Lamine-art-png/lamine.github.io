"""Operator proof of the live Commercial Intelligence cycle.

The proof is printed in public workflow logs, so besides its verdicts these
tests pin that no tenant identifier or commercial content can reach it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import cloudflare_queue
from app.models.operational_records import IngestionJob
from app.models.task_outbox import TaskOutbox
from app.services import market_intelligence_cycle as cycle
from app.services.market_cycle_proof import cycle_proof
from tests.test_commercial_intelligence_global import identity, no_network  # noqa: F401 - autouse fixture
from tests.test_commercial_intelligence_hardening import _position, no_heartbeat  # noqa: F401 - fixture


def _run_scheduled_cycle(db, monkeypatch):
    async def shared_ingestion(db_, **kwargs):
        return {"ecb_reference_rates": {"status": "ok"}, "usda_mmn": {"status": "not_configured"}}

    monkeypatch.setattr(cycle, "ingest_due_demands", shared_ingestion)
    assert cycle.schedule_cycle(db)["status"] == "ok"
    for job in db.query(IngestionJob).filter(IngestionJob.job_type == cycle.TASK_TYPE).all():
        db.query(TaskOutbox).filter_by(job_id=job.id).update({TaskOutbox.status: "published", TaskOutbox.published_at: datetime.utcnow()})
        db.commit()
        cycle.process_market_cycle_job(db, job_id=job.id, organization_id=job.tenant_id, worker_id="proof-test")


def test_no_active_position_is_reported_truthfully_never_as_success(db):
    proof = cycle_proof(db)
    assert proof["verdict"] == "NO_ELIGIBLE_POSITION"
    assert proof["eligibility"] == {"eligible_organizations": 0, "eligible_positions": 0}


def test_scheduled_but_unrun_cycle_is_pending(db):
    _, org, _ = identity(db, "proof-pending")
    _position(db, org)
    cycle.schedule_cycle(db)
    proof = cycle_proof(db)
    assert proof["verdict"] == "PENDING" and proof["jobs"]["scheduled"] == 1 and proof["jobs"]["published"] == 0
    assert proof["evaluation"]["organizations_evaluated"] == 0


def test_real_cycle_proves_publication_shared_ingestion_and_evaluation(db, monkeypatch, no_heartbeat):
    _, org_a, _ = identity(db, "proof-a")
    _, org_b, _ = identity(db, "proof-b")
    _position(db, org_a)
    _position(db, org_b, name="Corn", commodity="corn")
    _run_scheduled_cycle(db, monkeypatch)
    proof = cycle_proof(db)
    assert proof["verdict"] == "PASS", proof["reasons"]
    assert proof["jobs"]["scheduled"] == 2 and proof["jobs"]["published"] == 2 and proof["jobs"]["succeeded"] == 2
    assert proof["evaluation"]["organizations_evaluated"] == 2
    assert proof["evaluation"]["evaluations_without_completed_shared_ingestion"] == 0
    assert proof["evaluation"]["evaluations_without_slot_marker"] == 0
    assert proof["latest_slot"]["shared_ingestion_complete"] is True
    assert proof["latest_slot"]["provider_status_counts"] == {"ok": 1, "not_configured": 1}


def test_evaluation_without_completed_shared_ingestion_fails_the_proof(db, monkeypatch, no_heartbeat):
    _, org, _ = identity(db, "proof-stale")
    _position(db, org)
    _run_scheduled_cycle(db, monkeypatch)
    job = db.query(IngestionJob).filter(IngestionJob.job_type == cycle.TASK_TYPE).one()
    job.output_json = {**job.output_json, "shared_ingestion_complete": False}
    db.commit()
    proof = cycle_proof(db)
    assert proof["verdict"] == "FAIL"
    assert "evaluation_without_completed_shared_ingestion" in proof["reasons"]


def test_shared_ingestion_incomplete_is_counted_not_passed(db, monkeypatch, no_heartbeat):
    _, org, _ = identity(db, "proof-incomplete")
    _position(db, org)
    cycle.schedule_cycle(db)
    job = db.query(IngestionJob).filter(IngestionJob.job_type == cycle.TASK_TYPE).one()
    job.status, job.output_json = "succeeded", {"status": cycle.SHARED_INGESTION_INCOMPLETE, "evaluated": 0, "shared_ingestion_complete": False}
    db.commit()
    proof = cycle_proof(db)
    assert proof["verdict"] == "PENDING" and proof["jobs"]["shared_ingestion_incomplete"] == 1


def test_failed_cycle_job_fails_the_proof(db):
    _, org, _ = identity(db, "proof-failed")
    _position(db, org)
    cycle.schedule_cycle(db)
    db.query(IngestionJob).filter(IngestionJob.job_type == cycle.TASK_TYPE).update({IngestionJob.status: "failed"})
    db.commit()
    proof = cycle_proof(db)
    assert proof["verdict"] == "FAIL" and "cycle_jobs_failed" in proof["reasons"]


def test_window_excludes_older_cycles_and_is_bounded(db, monkeypatch, no_heartbeat):
    _, org, _ = identity(db, "proof-window")
    _position(db, org)
    _run_scheduled_cycle(db, monkeypatch)
    assert cycle_proof(db, since=datetime.utcnow() + timedelta(minutes=1))["jobs"]["scheduled"] == 0
    bounded = cycle_proof(db, since=datetime(2000, 1, 1))
    assert datetime.fromisoformat(bounded["window_start"].rstrip("Z")) > datetime.utcnow() - timedelta(hours=49)


def test_proof_never_contains_tenant_identifiers_or_commercial_content(db, monkeypatch, no_heartbeat):
    user, org, _ = identity(db, "proof-private")
    position = _position(db, org, name="Secret Soy Lot", price="187.43")
    _run_scheduled_cycle(db, monkeypatch)
    job = db.query(IngestionJob).filter(IngestionJob.job_type == cycle.TASK_TYPE).one()
    rendered = json.dumps(cycle_proof(db))
    for private in (org.id, org.name, user.id, user.email, position.id, position.name, job.id, "187.43", "soybean", "BRL", "MT"):
        assert private and private not in rendered


def test_proof_route_requires_the_queue_token(monkeypatch):
    app = FastAPI()
    app.include_router(cloudflare_queue.router, prefix="/v1")
    monkeypatch.setattr(cloudflare_queue.settings, "CLOUDFLARE_QUEUE_CONSUMER_TOKEN", "consumer-test-value")
    client = TestClient(app)
    assert client.get("/v1/internal/queue/market-cycle/proof").status_code == 401
    assert client.get("/v1/internal/queue/market-cycle/proof", headers={"Authorization": "Bearer wrong"}).status_code == 401
