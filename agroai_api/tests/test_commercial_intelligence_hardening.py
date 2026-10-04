"""Release-hardening regressions for Commercial Intelligence.

Each test pins one production gap found in review:
1. contract-currency FX demand and contract-level data health;
4. durable scheduled cycle on the existing job queue (crash, retry, single-flight);
5. fair oldest-due scheduling across organizations;
6. bounded cryptographic provider demand identity;
7. alert delivery attempts recorded separately from success;
8. append-only upstream revision history.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import chain, repeat
from types import SimpleNamespace

import pytest

from app.models.market_intelligence import (
    MarketAlertDelivery,
    MarketContractPosition,
    MarketCycleOrganizationState,
    MarketDataPoint,
    MarketDataPointRevision,
    MarketMaterialityEvent,
    MarketPosition,
    MarketProviderRun,
)
from app.models.operational_records import IngestionJob
from app.models.saas import UserPreference
from app.models.task_outbox import TaskOutbox
from app.services import market_data_plane as plane
from app.services import market_intelligence_cycle as cycle
from app.services import market_intelligence_refresh as refresh_module
from app.services.market_data_adapters import ADAPTERS, BCBPtaxSeries, ECBReferenceRatesSeries, SeriesPoint
from app.services.market_intelligence import compute_position
from app.services.market_materiality import evaluate, evidence_states, record_snapshot
from tests.test_commercial_intelligence_global import (  # noqa: F401 - no_network is an autouse fixture
    NOW,
    act_as,
    identity,
    no_network,
    seed,
    series_point,
)

# Captured at import, before the autouse fixture stubs it out for other tests.
REAL_ENSURE_POSITION_EVIDENCE = refresh_module.ensure_position_evidence


def _position(db, org, *, name="Soy", country="BR", commodity="soybean", reporting="BRL", price_currency="BRL", price="140",
              region="MT", metadata=None, updated_at=None):
    row = MarketPosition(
        organization_id=org.id, position_key=f"{name}-{org.id}", name=name, commodity=commodity, season="2027",
        country_code=country, region=region, local_currency=price_currency, reporting_currency=reporting,
        quantity_unit="saca_60kg", expected_production=Decimal("10000"), inventory_quantity=Decimal("0"),
        production_cost_per_unit=Decimal("100"), current_realizable_price=Decimal(price) if price else None,
        price_currency=price_currency, metadata_json={"price_policy": "manual", **(metadata or {})},
    )
    if updated_at is not None:
        row.updated_at = updated_at
    db.add(row)
    db.commit()
    return row


def _contract(db, position, *, code, currency, price="25", quantity="2000", status="active", fx=None):
    row = MarketContractPosition(
        organization_id=position.organization_id, position_id=position.id, contract_code=code, status=status,
        quantity=Decimal(quantity), quantity_unit="saca_60kg", price=Decimal(price), currency=currency,
        fx_rate_to_reporting=Decimal(fx) if fx else None, metadata_json={},
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# 1. Contract-currency FX
# ---------------------------------------------------------------------------


def test_foreign_contract_currency_creates_shared_fx_demand_even_when_price_and_reporting_match(db):
    _, org, _ = identity(db, "fx-demand")
    position = _position(db, org)  # BRL price, BRL reporting
    assert "bcb_ptax" not in plane.demand_set(db) and "fx_reference" not in plane.demand_set(db)
    _contract(db, position, code="USD-1", currency="USD")
    demand = plane.demand_set(db)
    assert demand["bcb_ptax"] == [{}] and demand["fx_reference"] == [{}]
    # Closed contracts carry no exposure and create no demand.
    db.query(MarketContractPosition).update({MarketContractPosition.status: "fulfilled"})
    db.commit()
    assert "bcb_ptax" not in plane.demand_set(db)
    assert plane.position_fx_currencies(position, []) == set()


def test_cost_currency_in_a_third_currency_creates_fx_demand(db):
    _, org, _ = identity(db, "fx-cost")
    _position(db, org, reporting="USD", price_currency="USD", country="US", commodity="corn", region="Iowa",
              metadata={"cost_currency": "EUR"})
    assert plane.demand_set(db)["fx_reference"] == [{}]


def test_foreign_contract_fx_comes_from_the_real_ingestion_path_without_seeded_fx(db, monkeypatch):
    _, org, _ = identity(db, "fx-ingest")
    position = _position(db, org)
    contract = _contract(db, position, code="USD-2", currency="USD", price="25", quantity="2000")
    assert db.query(MarketDataPoint).count() == 0  # nothing pre-seeded
    stamp = datetime.utcnow().strftime("%Y-%m-%d 13:00:00.000")
    monkeypatch.setitem(ADAPTERS, "bcb_ptax", BCBPtaxSeries(fetch_text=lambda url, timeout: json.dumps({"value": [
        {"cotacaoCompra": 5.10, "cotacaoVenda": 5.20, "dataHoraCotacao": stamp}]})))
    today = datetime.utcnow().strftime("%Y-%m-%d")
    xml = ('<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">'
           f'<Cube><Cube time="{today}"><Cube currency="USD" rate="1.08"/><Cube currency="BRL" rate="5.62"/></Cube></Cube></gesmes:Envelope>')
    monkeypatch.setitem(ADAPTERS, "fx_reference", ECBReferenceRatesSeries(fetch_text=lambda url, timeout: xml))
    monkeypatch.setattr(refresh_module, "ensure_position_evidence", REAL_ENSURE_POSITION_EVIDENCE)

    before = compute_position(position, [contract]).payload
    assert "contract_fx" in before["missing_inputs"] and before["projected_margin"] is None

    result = asyncio.run(refresh_module.refresh_position_market_data(db, position, trigger="test"))
    assert result["providers"]["bcb_ptax"]["status"] == "ok"
    db.refresh(contract)
    assert contract.fx_rate_to_reporting == Decimal("5.2000000000")  # PTAX sell, governed
    assert contract.metadata_json["fx_state"] == "DELAYED" and contract.metadata_json["fx_source"].startswith("data_plane:")
    assert result["contract_fx"] == [{"contract_id": contract.id, "contract_code": "USD-2", "currency": "USD", "outcome": "updated",
                                      "state": "DELAYED", "method": contract.metadata_json["fx_source"].removeprefix("data_plane:")}]
    after = compute_position(position, [contract]).payload
    assert "contract_fx" not in after["missing_inputs"]
    assert after["locked_revenue"] == "260000.00"  # 2000 x 25 USD x 5.20
    assert evidence_states(db, position, [contract])["contract_fx:USD-2"] == "DELAYED"


def test_missing_contract_fx_is_explicit_in_data_health_and_blocks_commercial_alerts(db, client):
    user, org, membership = identity(db, "fx-health")
    position = _position(db, org)
    contract = _contract(db, position, code="EUR-1", currency="EUR")
    asyncio.run(refresh_module.refresh_position_market_data(db, position, ingest_missing=False))
    db.refresh(contract)
    assert contract.metadata_json["fx_state"] == "UNAVAILABLE" and contract.fx_rate_to_reporting is None
    states = evidence_states(db, position, [contract])
    assert states["contract_fx:EUR-1"] == "UNAVAILABLE"
    act_as(user, org, membership)
    home = client.get("/v1/market-intelligence/home").json()
    [health] = home["data_health"]["positions_with_stale_or_missing_evidence"]
    assert health["degraded_evidence"] == {"contract_fx:EUR-1": "UNAVAILABLE"}
    assert home["status"] == "review"
    # A material price move is computed but not emitted while a contract conversion is unavailable.
    reference, _ = record_snapshot(db, position, [contract], now=datetime.utcnow() - timedelta(hours=30))
    position.current_realizable_price = Decimal("110")
    db.commit()
    current, _ = record_snapshot(db, position, [contract])
    commercial = [r for r in evaluate(reference, current) if r.kind == "commercial_change"]
    assert all(not r.emit and r.suppressed_reason == "evidence_not_fresh" for r in commercial)


def test_customer_contract_fx_is_kept_and_reported_manual_when_no_governed_rate(db):
    _, org, _ = identity(db, "fx-manual")
    position = _position(db, org)
    contract = _contract(db, position, code="KES-1", currency="KES", fx="0.04")
    result = asyncio.run(refresh_module.refresh_position_market_data(db, position, ingest_missing=False))
    db.refresh(contract)
    assert contract.fx_rate_to_reporting == Decimal("0.0400000000") and contract.metadata_json["fx_state"] == "MANUAL"
    assert result["contract_fx"][0]["outcome"] == "kept_customer_rate"
    assert evidence_states(db, position, [contract])["contract_fx:KES-1"] == "MANUAL"


# ---------------------------------------------------------------------------
# 6. Provider demand identity
# ---------------------------------------------------------------------------


def test_demand_identity_is_bounded_order_independent_and_collision_free():
    adapter = ADAPTERS["conab_precos"]
    selectors = [{"commodity": "soybean", "uf": uf} for uf in ("MT", "PR", "GO", "MS", "RS", "BA", "MG", "SP", "TO", "MA")] * 3
    key, labels = plane.demand_identity(adapter, selectors)
    assert key == plane.demand_identity(adapter, list(reversed(selectors)))[0]
    assert key.startswith("sha256:") and len(key) == 71
    assert labels == sorted({adapter.demand_key(s) for s in selectors})
    # Two large demand sets sharing a 400-character prefix used to collide under truncation.
    base = [{"commodity": "soybean", "uf": f"X{index:03d}"} for index in range(60)]
    first, _ = plane.demand_identity(adapter, base + [{"commodity": "soybean", "uf": "ZZ1"}])
    second, _ = plane.demand_identity(adapter, base + [{"commodity": "soybean", "uf": "ZZ2"}])
    assert first != second


def test_provider_run_records_hash_and_readable_trace(db):
    class Fixture(BCBPtaxSeries):
        async def collect(self, selectors):
            return []

    adapter = Fixture()
    asyncio.run(plane.ingest(db, "bcb_ptax", [{}], trigger="test", adapter=adapter))
    run = db.query(MarketProviderRun).one()
    assert run.demand_key == plane.demand_identity(adapter, [{}])[0]
    assert run.trace_json["demand_labels"] == [adapter.demand_key({})] and run.trace_json["selector_count"] == 1


# ---------------------------------------------------------------------------
# 8. Revision history
# ---------------------------------------------------------------------------


def test_upstream_corrections_append_an_unbounded_audit_history(db):
    point = series_point("hist:a", "100", provider="eu_agrifood", commodity="wheat", country="FR")
    seed(db, point)
    for index, value in enumerate(("101", "99.5", "102", "103", "104", "105", "106", "107", "108", "109", "110", "111"), start=1):
        seed(db, SeriesPoint(descriptor=point.descriptor, observed_at=point.observed_at, value=Decimal(value), retrieved_at=NOW + timedelta(minutes=index)))
    stored = db.query(MarketDataPoint).one()
    history = db.query(MarketDataPointRevision).filter_by(point_id=stored.id).order_by(MarketDataPointRevision.revision).all()
    assert [h.revision for h in history] == list(range(1, 13))  # beyond any small ring buffer
    assert history[0].previous_value == Decimal("100") and history[-1].new_value == Decimal("111") == stored.value
    assert all(a.new_value == b.previous_value and a.new_content_hash == b.previous_content_hash for a, b in zip(history, history[1:]))
    assert int(stored.revision) == 12 and "revisions" not in (stored.quality_json or {})


def test_revision_rows_link_to_the_provider_run_that_observed_the_correction(db):
    point = series_point("hist:b", "50", provider="eu_agrifood", commodity="wheat", country="FR")
    seed(db, point)

    class Correcting(BCBPtaxSeries):
        provider_id = "eu_agrifood"

        async def collect(self, selectors):
            return [SeriesPoint(descriptor=point.descriptor, observed_at=point.observed_at, value=Decimal("51"), retrieved_at=NOW)]

        def configured(self):
            return True

    asyncio.run(plane.ingest(db, "eu_agrifood", [{"commodity": "wheat", "member_state": "FR"}], adapter=Correcting()))
    run = db.query(MarketProviderRun).one()
    [revision] = db.query(MarketDataPointRevision).all()
    assert revision.provider_run_id == run.id and revision.new_value == Decimal("51")


# ---------------------------------------------------------------------------
# 4. Durable cycle
# ---------------------------------------------------------------------------


@pytest.fixture
def no_heartbeat(monkeypatch):
    monkeypatch.setattr(cycle, "job_lease_heartbeat", lambda **kwargs: nullcontext())


def _jobs(db):
    return db.query(IngestionJob).filter(IngestionJob.job_type == cycle.TASK_TYPE).all()


def test_schedule_writes_durable_jobs_and_outbox_rows_once_per_slot(db):
    _, org_a, _ = identity(db, "sched-a")
    _, org_b, _ = identity(db, "sched-b")
    _position(db, org_a)
    _position(db, org_b)
    first = cycle.schedule_cycle(db)
    assert first["status"] == "ok" and first["enqueued"] == 2
    jobs = _jobs(db)
    assert {job.tenant_id for job in jobs} == {org_a.id, org_b.id} and {job.status for job in jobs} == {"queued"}
    outbox = db.query(TaskOutbox).filter(TaskOutbox.task_type == cycle.TASK_TYPE).all()
    assert {row.job_id for row in outbox} == {job.id for job in jobs} and {row.status for row in outbox} == {"pending"}
    # Concurrent or repeated scheduling never duplicates an open job.
    again = cycle.schedule_cycle(db)
    assert again["enqueued"] == 0 and len(_jobs(db)) == 2
    assert db.get(MarketCycleOrganizationState, org_a.id).last_status == "queued"


def test_drain_endpoint_schedules_synchronously_without_background_tasks(monkeypatch):
    from app.api.v1 import cloudflare_queue

    calls = []
    monkeypatch.setattr(cloudflare_queue, "queue_configured", lambda: True)
    monkeypatch.setattr(cloudflare_queue, "run_connector_object_gc", lambda **kwargs: {"deleted": 0})
    for name in ("_drain_webhook_outbox", "_drain_meter_outbox", "_run_platform_api_maintenance", "_run_lifecycle_emails"):
        monkeypatch.setattr(cloudflare_queue, name, lambda: {})
    published = []
    monkeypatch.setattr(cloudflare_queue, "drain_pending_outbox", lambda **kwargs: published.append(kwargs) or {"published": 3, "failed": 0})
    monkeypatch.setattr("app.services.market_intelligence_cycle.schedule_cycle_once", lambda **kwargs: calls.append(kwargs) or {"status": "ok", "enqueued": 3, "batch": 200})
    result = asyncio.run(cloudflare_queue.drain_task_outbox())
    assert calls == [{"trigger": "scheduled"}]
    # Jobs scheduled in this pass are published in this pass, with their own bound.
    assert published[-1] == {"limit": 200, "task_types": (cycle.TASK_TYPE,)}
    assert result["market_intelligence_cycle"] == {"status": "ok", "enqueued": 3, "batch": 200, "published": {"published": 3, "failed": 0}}
    import inspect

    assert "background" not in inspect.signature(cloudflare_queue.drain_task_outbox).parameters


def test_crashed_cycle_job_is_redelivered_and_completed_by_another_worker(db, monkeypatch, no_heartbeat):
    _, org, _ = identity(db, "crash")
    _position(db, org)
    cycle.schedule_cycle(db)
    [job] = _jobs(db)
    outbox = db.query(TaskOutbox).filter_by(job_id=job.id).one()
    outbox.status, outbox.updated_at = "published", datetime.utcnow() - timedelta(minutes=30)
    db.commit()
    # Worker A claims the job and dies without completing (deploy/restart).
    claimed = cycle._claim(db, job_id=job.id, tenant_id=org.id, worker_id="worker-a")
    assert claimed is not None and claimed.status == "running"
    # While the lease is live, a redelivery cannot run it twice.
    assert cycle.process_market_cycle_job(db, job_id=job.id, organization_id=org.id, worker_id="worker-b") == "deferred"
    assert cycle.recover_stale_jobs(db) == 0
    db.query(IngestionJob).filter_by(id=job.id).update({IngestionJob.lease_expires_at: datetime.utcnow() - timedelta(minutes=1)})
    db.commit()
    assert cycle.recover_stale_jobs(db) == 1
    db.refresh(outbox)
    assert outbox.status == "pending"  # the outbox republishes it
    ran = []

    async def fake_cycle(db_, organization_id, **kwargs):
        ran.append(organization_id)
        return {"complete": True, "evaluated": 1, "shared_ingestion_complete": True}

    monkeypatch.setattr(cycle, "run_organization_cycle", fake_cycle)
    assert cycle.process_market_cycle_job(db, job_id=job.id, organization_id=org.id, worker_id="worker-b") == "succeeded"
    db.refresh(job)
    assert job.status == "succeeded" and job.attempt_count == 2 and ran == [org.id]
    state = db.get(MarketCycleOrganizationState, org.id)
    assert state.last_status == "succeeded" and state.last_completed_at is not None and state.consecutive_failures == 0
    # A duplicate delivery of a finished job is acknowledged without re-running.
    assert cycle.process_market_cycle_job(db, job_id=job.id, organization_id=org.id, worker_id="worker-c") == "succeeded"
    assert ran == [org.id]


def test_failed_cycle_job_retries_with_backoff_then_fails_visibly(db, monkeypatch, no_heartbeat):
    _, org, _ = identity(db, "retry")
    _position(db, org)
    cycle.schedule_cycle(db)
    [job] = _jobs(db)

    async def boom(*args, **kwargs):
        raise RuntimeError("provider outage")

    monkeypatch.setattr(cycle, "run_organization_cycle", boom)
    statuses = []
    for _ in range(job.max_attempts):
        statuses.append(cycle.process_market_cycle_job(db, job_id=job.id, organization_id=org.id, worker_id="w"))
        db.refresh(job)
        if job.status == "retrying":
            assert job.next_attempt_at > datetime.utcnow()
            # Not due yet: a redelivery is deferred, not run.
            assert cycle.process_market_cycle_job(db, job_id=job.id, organization_id=org.id, worker_id="w") == "deferred"
            job.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
    assert statuses == ["retrying"] * (job.max_attempts - 1) + ["failed"]
    assert job.status == "failed" and "provider outage" in job.error
    state = db.get(MarketCycleOrganizationState, org.id)
    assert state.last_status == "failed" and state.consecutive_failures == job.max_attempts
    # A failed job is no longer open, so the organization is scheduled again next tick.
    assert cycle.schedule_cycle(db, now=datetime.utcnow() + timedelta(hours=1))["enqueued"] == 1


def test_disabled_cycle_schedules_nothing(db, monkeypatch):
    _, org, _ = identity(db, "disabled")
    _position(db, org)
    monkeypatch.setenv("MARKET_INTELLIGENCE_CYCLE_ENABLED", "false")
    assert cycle.schedule_cycle(db) == {"status": "disabled"}
    assert _jobs(db) == []


def test_organization_cycle_ingests_shared_evidence_once_and_alerts(db, client, monkeypatch, no_heartbeat):
    from tests.test_commercial_intelligence_global import CONAB_FIXTURE, _age_snapshots, _brazil_position, seed_fx
    from app.services.market_data_adapters import CONABWeeklyPricesSeries

    seed_fx(db)
    created = _brazil_position(client, db, "cycle-job")
    position_id = created["id"]
    org_id = db.get(MarketPosition, position_id).organization_id
    _age_snapshots(db, position_id)
    calls = []

    class FixtureConab(CONABWeeklyPricesSeries):
        async def collect(self, selectors):
            calls.append(selectors)
            line = "SOJA ;EM GRÃOS ;1;MT ;CENTRO-OESTE ;2026;10;{} - {} ;1;PREÇO RECEBIDO P/ PR;1,95\n"
            day = datetime.utcnow().strftime("%d-%m-%Y")
            return self._parse(iter([CONAB_FIXTURE[0], line.format(day, day)]), {("soybean", "MT")}, datetime.now(timezone.utc))

    monkeypatch.setitem(ADAPTERS, "conab_precos", FixtureConab())
    for provider_id in ("fx_reference", "bcb_ptax"):
        monkeypatch.setattr(ADAPTERS[provider_id], "configured", lambda: False)
    demand_builds = []
    real_demand_set = cycle.plane.demand_set
    monkeypatch.setattr(cycle.plane, "demand_set", lambda db_, **kw: demand_builds.append(1) or real_demand_set(db_, **kw))
    cycle.schedule_cycle(db)
    [job] = _jobs(db)
    assert cycle.process_market_cycle_job(db, job_id=job.id, organization_id=org_id, worker_id="w") == "succeeded"
    db.refresh(job)
    assert job.output_json["providers"]["conab_precos"]["status"] == "ok" and job.output_json["complete"] is True
    assert len(calls) == 1 and calls[0] == [{"commodity": "soybean", "uf": "MT"}]
    events = db.query(MarketMaterialityEvent).filter_by(position_id=position_id).all()
    assert events and events[0].level in {"HIGH", "CRITICAL"}
    assert job.output_json["notifications"]["status"] == "disabled"
    # Every other organization job of the slot skips shared ingestion entirely:
    # no global demand rebuild, no provider call.
    again = asyncio.run(cycle.run_organization_cycle(db, org_id, time_budget_seconds=60, slot=job.input_json["slot"]))
    assert again["providers"] == {"status": "already_ingested_this_slot"} and len(calls) == 1 and len(demand_builds) == 1
    # The next slot re-checks freshness: CONAB is still fresh, so it is not re-fetched.
    later = asyncio.run(cycle.run_organization_cycle(db, org_id, time_budget_seconds=60, slot="next-slot"))
    assert later["providers"]["conab_precos"]["status"] == "fresh_enough" and len(calls) == 1 and len(demand_builds) == 2
    assert "__cycle_slot__" not in plane.provider_health(db)


# ---------------------------------------------------------------------------
# 5. Fair scheduling
# ---------------------------------------------------------------------------


def test_bounded_scheduling_serves_every_organization_oldest_due_first(db, monkeypatch, no_heartbeat):
    orgs = []
    for index in range(5):
        _, org, _ = identity(db, f"fair-{index}")
        _position(db, org)
        orgs.append(org.id)

    async def quick(db_, organization_id, **kwargs):
        return {"complete": True}

    monkeypatch.setattr(cycle, "run_organization_cycle", quick)
    served: list[list[str]] = []
    clock = datetime.utcnow()
    for tick in range(3):
        now = clock + timedelta(hours=tick)
        cycle.schedule_cycle(db, now=now, batch=2)
        # The drain publishes what it admitted in the same pass.
        db.query(TaskOutbox).filter(TaskOutbox.task_type == cycle.TASK_TYPE).update({TaskOutbox.status: "published"})
        db.commit()
        batch = [job for job in _jobs(db) if job.status == "queued"]
        served.append(sorted(job.tenant_id for job in batch))
        for job in batch:
            assert cycle.process_market_cycle_job(db, job_id=job.id, organization_id=job.tenant_id, worker_id="w") == "succeeded"
            state = db.get(MarketCycleOrganizationState, job.tenant_id)
            state.last_completed_at = now
            db.commit()
    assert [len(batch) for batch in served] == [2, 2, 2]
    assert not set(served[0]) & set(served[1]), "never-run organizations go before anyone runs twice"
    remaining = set(orgs) - set(served[0]) - set(served[1])
    assert len(remaining) == 1 and remaining <= set(served[2]), "every organization is served before any is served twice"
    # The sixth slot goes to an organization that completed longest ago (tick 0).
    assert set(served[2]) - remaining <= set(served[0])


def test_large_organization_progresses_oldest_positions_first_under_a_time_budget(db, monkeypatch):
    _, org, _ = identity(db, "budget")
    base = datetime.utcnow() - timedelta(days=1)
    rows = [_position(db, org, name=f"P{index}", updated_at=base + timedelta(minutes=index)) for index in range(4)]
    seen = []

    async def fake_refresh(db_, position, **kwargs):
        seen.append(position.name)
        position.updated_at = datetime.utcnow()

    monkeypatch.setattr(cycle, "refresh_position_market_data", fake_refresh)
    monkeypatch.setattr(cycle, "evaluate_position", lambda db_, position: {"events_created": []})
    # Budget allows two positions per run (the module clock only; asyncio keeps the real one).
    clock = {"ticks": None}
    monkeypatch.setattr(cycle, "time", SimpleNamespace(monotonic=lambda: next(clock["ticks"])))
    clock["ticks"] = chain([0, 0], repeat(100))
    first = asyncio.run(cycle.evaluate_organization(db, org.id, deadline=50))
    clock["ticks"] = chain([0, 0], repeat(100))
    second = asyncio.run(cycle.evaluate_organization(db, org.id, deadline=50))
    assert seen == ["P0", "P1", "P2", "P3"], "the next run continues with the least recently refreshed positions"
    assert first["complete"] is False and first["evaluated"] == 2 and second["evaluated"] == 2
    assert {row.name for row in rows} == set(seen)


# ---------------------------------------------------------------------------
# 7. Alert delivery
# ---------------------------------------------------------------------------


def _urgent_event(db, org, position, *, level="HIGH"):
    event = MarketMaterialityEvent(
        organization_id=org.id, position_id=position.id, dedupe_key=f"d-{position.id}-{level}", kind="commercial_change", level=level,
        status="open", title_key="market.materiality.commercial_change", reasons_json=[], impact_json={}, data_quality_json={},
        methodology_version="test", notified_json={},
    )
    db.add(event)
    db.commit()
    return event


def test_failed_alert_email_is_retried_not_marked_delivered(db, monkeypatch):
    user, org, _ = identity(db, "alert-retry")
    event = _urgent_event(db, org, _position(db, org))
    monkeypatch.setenv("MARKET_INTELLIGENCE_ALERT_EMAILS_ENABLED", "true")
    outcomes = iter([{"ok": False, "reason": "smtp_timeout"}, {"ok": True}])
    sent = []
    monkeypatch.setattr("app.services.email_delivery.send_email", lambda **kwargs: sent.append(kwargs["to_email"]) or next(outcomes))
    now = datetime.utcnow()
    first = cycle.deliver_alerts(db, org.id, now=now)
    [delivery] = db.query(MarketAlertDelivery).filter_by(event_id=event.id).all()
    assert first["retrying"] == 1 and first["delivered"] == 0
    assert (delivery.status, delivery.attempts, delivery.delivered_at, delivery.last_error) == ("retrying", 1, None, "smtp_timeout")
    assert delivery.next_attempt_at > now
    assert cycle.deliver_alerts(db, org.id, now=now + timedelta(minutes=1))["status"] == "nothing_due"
    second = cycle.deliver_alerts(db, org.id, now=delivery.next_attempt_at + timedelta(seconds=1))
    db.refresh(delivery)
    assert second["delivered"] == 1 and delivery.status == "delivered" and delivery.attempts == 2 and delivery.delivered_at is not None
    assert sent == [user.email, user.email]
    assert cycle.deliver_alerts(db, org.id, now=delivery.next_attempt_at or datetime.utcnow() + timedelta(days=1))["status"] == "nothing_due"


def test_alert_email_attempts_are_bounded(db, monkeypatch):
    _, org, _ = identity(db, "alert-bounded")
    _urgent_event(db, org, _position(db, org), level="CRITICAL")
    monkeypatch.setenv("MARKET_INTELLIGENCE_ALERT_EMAILS_ENABLED", "true")

    def raising(**kwargs):
        raise ConnectionError("provider down")

    monkeypatch.setattr("app.services.email_delivery.send_email", raising)
    now = datetime.utcnow()
    for _ in range(cycle.MAX_EMAIL_ATTEMPTS + 2):
        cycle.deliver_alerts(db, org.id, now=now)
        now += timedelta(days=1)
    [delivery] = db.query(MarketAlertDelivery).all()
    assert (delivery.status, delivery.attempts, delivery.delivered_at) == ("failed", cycle.MAX_EMAIL_ATTEMPTS, None)
    assert delivery.last_error == "ConnectionError"


def test_unsupported_recipient_language_is_an_explicit_deferral_never_english(db, monkeypatch):
    user, org, _ = identity(db, "alert-lang")
    db.add(UserPreference(user_id=user.id, locale="ja"))
    db.commit()
    _urgent_event(db, org, _position(db, org))
    monkeypatch.setenv("MARKET_INTELLIGENCE_ALERT_EMAILS_ENABLED", "true")
    sent = []
    monkeypatch.setattr("app.services.email_delivery.send_email", lambda **kwargs: sent.append(kwargs) or {"ok": True})
    result = cycle.deliver_alerts(db, org.id)
    [delivery] = db.query(MarketAlertDelivery).all()
    assert sent == [] and delivery.status == "deferred_unsupported_language" and delivery.language == "ja" and delivery.attempts == 0
    assert result["deferred_unsupported_language"] == 1


def test_alert_emails_stay_off_unless_explicitly_enabled(db, monkeypatch):
    _, org, _ = identity(db, "alert-off")
    _urgent_event(db, org, _position(db, org))
    monkeypatch.delenv("MARKET_INTELLIGENCE_ALERT_EMAILS_ENABLED", raising=False)
    assert cycle.deliver_alerts(db, org.id) == {"status": "disabled"}
    assert db.query(MarketAlertDelivery).count() == 0


def test_outbox_publish_can_be_scoped_to_cycle_jobs(db, monkeypatch):
    from app.services import task_outbox_service

    _, org, _ = identity(db, "scoped-publish")
    _position(db, org)
    cycle.schedule_cycle(db)
    other = IngestionJob(tenant_id=org.id, job_type="connector_provider_sync", status="queued", input_json={}, output_json={}, attempt_count=0, max_attempts=5)
    db.add(other)
    db.flush()
    db.add(TaskOutbox(job_id=other.id, tenant_id=org.id, task_type="connector_provider_sync", payload_json={}, status="pending", publish_attempts=0))
    db.commit()
    sent = []

    class Publisher:
        def enqueue(self, job_id, tenant_id, task_type):
            sent.append(task_type)

    monkeypatch.setattr(task_outbox_service, "get_task_publisher", lambda: Publisher())
    assert task_outbox_service.publish_pending_outbox(db, limit=10, task_types=(cycle.TASK_TYPE,)) == {"published": 1, "failed": 0}
    assert sent == [cycle.TASK_TYPE]
    assert db.query(TaskOutbox).filter_by(task_type="connector_provider_sync").one().status == "pending"


def test_cycle_job_for_a_disabled_cycle_completes_without_running(db, monkeypatch, no_heartbeat):
    _, org, _ = identity(db, "skip-disabled")
    _position(db, org)
    cycle.schedule_cycle(db)
    [job] = _jobs(db)
    ran = []

    async def should_not_run(*args, **kwargs):
        ran.append(1)
        return {"complete": True}

    monkeypatch.setattr(cycle, "run_organization_cycle", should_not_run)
    monkeypatch.setenv("MARKET_INTELLIGENCE_CYCLE_ENABLED", "false")
    assert cycle.process_market_cycle_job(db, job_id=job.id, organization_id=org.id, worker_id="w") == "succeeded"
    db.refresh(job)
    assert job.output_json == {"status": "skipped"} and ran == []


# ---------------------------------------------------------------------------
# Review findings (PR #528)
# ---------------------------------------------------------------------------


def test_distinct_usda_quotes_in_one_report_are_separate_series_not_revisions(db):
    from app.services.market_data_adapters import USDAMyMarketNewsSeries

    report = json.dumps({"results": [
        {"commodity": "Yellow Corn", "grade": "US #2", "price_unit": "$/bu", "avg_price": "4.21", "report_date": "10/01/2026", "location": "Central Iowa"},
        {"commodity": "Yellow Corn", "grade": "US #3", "price_unit": "$/bu", "avg_price": "4.05", "report_date": "10/01/2026", "location": "Central Iowa"},
        {"commodity": "Yellow Corn", "grade": "US #2", "delivery_period": "Nov", "price_unit": "$/bu", "avg_price": "4.30", "report_date": "10/01/2026", "location": "Central Iowa"},
    ]})
    adapter = USDAMyMarketNewsSeries(api_key="k", fetch_text=lambda url, headers, timeout: report)
    points = asyncio.run(adapter.collect([{"commodity": "corn", "region": "Iowa"}]))
    assert len({p.descriptor.series_key for p in points}) == 3
    stats = plane.persist_points(db, points)
    db.commit()
    assert (stats.inserted, stats.revised) == (3, 0) and db.query(MarketDataPointRevision).count() == 0
    again = asyncio.run(adapter.collect([{"commodity": "corn", "region": "Iowa"}]))
    assert {p.descriptor.series_key for p in again} == {p.descriptor.series_key for p in points}  # stable identity


def test_observation_window_is_partitioned_per_position(db):
    from app.api.v1.market_intelligence import _position_payloads
    from app.models.market_intelligence import MarketObservation

    _, org, _ = identity(db, "obs-window")
    busy = _position(db, org, name="Busy")
    quiet = _position(db, org, name="Quiet")
    now = datetime.utcnow()
    for index in range(250):  # more than the old global limit (100 x 2 positions)
        db.add(MarketObservation(organization_id=org.id, position_id=busy.id, evidence_id=f"busy-{index}", observation_type="cash_price",
                                 provider="customer", source_name="Customer", source_status="MANUAL", value=Decimal("1"), unit="saca_60kg",
                                 currency="BRL", observed_at=now - timedelta(minutes=index), retrieved_at=now, quality_json={}, licensing_json={}, metadata_json={}))
    for index in range(3):
        db.add(MarketObservation(organization_id=org.id, position_id=quiet.id, evidence_id=f"quiet-{index}", observation_type="cash_price",
                                 provider="customer", source_name="Customer", source_status="MANUAL", value=Decimal("1"), unit="saca_60kg",
                                 currency="BRL", observed_at=now - timedelta(days=10, minutes=index), retrieved_at=now, quality_json={}, licensing_json={}, metadata_json={}))
    db.commit()
    payloads = {item["name"]: item for item in _position_payloads(db, org.id, [busy, quiet])}
    assert payloads["Quiet"]["data_health"]["status"] != "missing"
    assert len(payloads["Quiet"]["data_health"].get("sources") or []) >= 1


def test_clearing_manual_inputs_clears_the_manual_evidence_claim(client, db):
    user, org, membership = identity(db, "clear-manual")
    act_as(user, org, membership)
    position = _position(db, org, reporting="USD", price_currency="BRL", metadata={})
    patch = lambda body: client.patch(f"/v1/market-intelligence/positions/{position.id}", json=body)
    assert patch({"current_realizable_price": "130", "fx_rate_to_reporting": "0.19"}).status_code == 200
    db.refresh(position)
    assert position.metadata_json["price_state"] == "MANUAL" and position.metadata_json["fx_state"] == "MANUAL"
    assert patch({"current_realizable_price": None, "fx_rate_to_reporting": None}).status_code == 200
    db.refresh(position)
    metadata = position.metadata_json
    assert metadata["price_policy"] == "automatic" and metadata["price_state"] == "UNAVAILABLE"
    assert "price_source" not in metadata and "fx_state" not in metadata and "fx_source" not in metadata
    assert evidence_states(db, position, []) == {"price": "UNAVAILABLE", "fx": "UNAVAILABLE"}
    contract = _contract(db, position, code="USD-9", currency="USD", fx="5.1")
    client.patch(f"/v1/market-intelligence/contracts/{contract.id}", json={"fx_rate_to_reporting": "5.2"})
    client.patch(f"/v1/market-intelligence/contracts/{contract.id}", json={"fx_rate_to_reporting": None})
    db.refresh(contract)
    assert contract.fx_rate_to_reporting is None and "fx_state" not in (contract.metadata_json or {})


def test_archived_fields_do_not_count_toward_linked_acreage(client, db):
    from app.models.saas import ManagedEntity

    user, org, membership = identity(db, "archived-field")
    act_as(user, org, membership)
    position = _position(db, org)
    active = ManagedEntity(organization_id=org.id, entity_type="platform_field", display_name="North", status="active", metadata_json={"area_hectares": 100})
    archived = ManagedEntity(organization_id=org.id, entity_type="platform_field", display_name="South", status="active", metadata_json={"area_hectares": 50})
    db.add_all([active, archived])
    db.commit()
    linked = client.put(f"/v1/market-intelligence/positions/{position.id}/fields", json={"field_ids": [active.id, archived.id]}).json()
    assert linked["linked_area_hectares"] == "150"
    archived.status = "archived"
    db.commit()
    estimate = client.post(f"/v1/market-intelligence/positions/{position.id}/yield-estimates", json={"yield_per_area": "50", "quantity_unit": "saca"}).json()
    assert Decimal(estimate["expected_production"]) == Decimal("5000")  # 100 ha only, not 150
    fields = {item["name"]: item for item in estimate.get("fields", [])} if estimate.get("fields") else {}
    if fields:
        assert fields["South"]["counted"] is False and fields["South"]["reason"] == "inactive"


def test_risk_with_horizon_equal_to_history_is_insufficient_not_an_error():
    from app.services.market_risk import MIN_OBSERVATIONS, historical_move_statistics

    values = [Decimal(100 + index) for index in range(MIN_OBSERVATIONS)]
    result = historical_move_statistics(values, horizon_periods=MIN_OBSERVATIONS, frequency="weekly")
    assert result["status"] == "insufficient_history" and result["horizon_periods"] == MIN_OBSERVATIONS
    assert historical_move_statistics(values + [Decimal(130)] * 20, horizon_periods=4, frequency="weekly")["status"] != "insufficient_history"


# ---------------------------------------------------------------------------
# Final audit (PR #528)
# ---------------------------------------------------------------------------


def _physical_series(series_key, value, *, provider, commodity, country, market, unit, currency, price_basis=None, metadata=None, days_ago=1):
    from app.services.market_data_adapters import SeriesDescriptor

    descriptor = SeriesDescriptor(
        provider=provider, series_key=series_key, source_name=f"{provider} test", observation_type="physical_price", commodity=commodity,
        country_code=country, region=None, market_name=market, price_basis=price_basis, unit=unit, currency=currency, frequency="weekly",
        freshness_max_age_minutes=14 * 1440, last_known_max_age_minutes=30 * 1440, licensing=PUBLIC_LICENCE, metadata=metadata or {},
    )
    return SeriesPoint(descriptor=descriptor, observed_at=NOW - timedelta(days=days_ago), value=Decimal(value), retrieved_at=NOW)


from tests.test_commercial_intelligence_global import PUBLIC as PUBLIC_LICENCE  # noqa: E402


def test_usda_grades_and_delivery_periods_are_never_medianed_into_one_price(db, client):
    from app.services.market_data_adapters import USDAMyMarketNewsSeries

    report = json.dumps({"results": [
        {"commodity": "Yellow Corn", "grade": "US #2", "price_unit": "$/bu", "avg_price": "4.21", "report_date": datetime.utcnow().strftime("%m/%d/%Y"), "location": "Central Iowa"},
        {"commodity": "Yellow Corn", "grade": "US #3", "price_unit": "$/bu", "avg_price": "4.05", "report_date": datetime.utcnow().strftime("%m/%d/%Y"), "location": "Central Iowa"},
        {"commodity": "Yellow Corn", "grade": "US #2", "delivery_period": "Nov", "price_unit": "$/bu", "avg_price": "4.30", "report_date": datetime.utcnow().strftime("%m/%d/%Y"), "location": "Central Iowa"},
    ]})
    points = asyncio.run(USDAMyMarketNewsSeries(api_key="k", fetch_text=lambda url, headers, timeout: report).collect([{"commodity": "corn", "region": "Iowa"}]))
    assert len(points) == 3
    seed(db, *points)
    user, org, membership = identity(db, "usda-grades")
    position = _position(db, org, country="US", commodity="corn", reporting="USD", price_currency="USD", price=None, region="Central Iowa",
                         metadata={"price_policy": "automatic"})
    position.quantity_unit = "bushel"
    db.commit()
    resolution = plane.resolve_physical_price(db, position)
    assert resolution.price is None and resolution.state == "SELECTION_REQUIRED" and resolution.reason == "heterogeneous_candidates"
    candidates = resolution.trace["candidates"]
    assert len(candidates) == 3 and len({json.dumps(c["signature"], sort_keys=True) for c in candidates}) == 3
    assert {c["signature"]["product"]["quote"].get("grade") for c in candidates} == {"US #2", "US #3"}
    result = asyncio.run(refresh_module.refresh_position_market_data(db, position, ingest_missing=False))
    db.refresh(position)
    assert result["price"]["outcome"] == "selection_required" and position.current_realizable_price is None  # no synthetic 4.21 median
    assert position.metadata_json["price_state"] == "SELECTION_REQUIRED"
    assert evidence_states(db, position, [])["price"] == "SELECTION_REQUIRED"
    act_as(user, org, membership)
    grade2 = next(c for c in candidates if c["signature"]["product"]["quote"] == {"grade": "US #2"})
    chosen = client.put(f"/v1/market-intelligence/positions/{position.id}/price-source", json={"series_key": grade2["series_key"]}).json()
    assert chosen["price"]["method"] == "customer_selected_series" and Decimal(chosen["position"]["current_realizable_price"]) == Decimal("4.21")
    assert client.put(f"/v1/market-intelligence/positions/{position.id}/price-source", json={"series_key": "usda_mymarketnews:invented"}).status_code == 422


def test_previously_automated_price_is_withdrawn_when_quotes_become_heterogeneous(db):
    _, org, _ = identity(db, "withdraw")
    seed(db, _physical_series("eu_agrifood:FR:BLT:rouen:delivered", "244.36", provider="eu_agrifood", commodity="wheat", country="FR", market="Rouen",
                              unit="tonne", currency="EUR", price_basis="Delivered Rouen", metadata={"product_label": "Breadmaking wheat"}))
    position = _position(db, org, country="FR", commodity="wheat", reporting="EUR", price_currency="EUR", price=None, region="Rouen",
                         metadata={"price_policy": "automatic"})
    position.quantity_unit = "tonne"
    db.commit()
    asyncio.run(refresh_module.refresh_position_market_data(db, position, ingest_missing=False))
    db.refresh(position)
    assert position.current_realizable_price == Decimal("244.36000000")
    seed(db, _physical_series("eu_agrifood:FR:FEED:rouen:delivered", "205.10", provider="eu_agrifood", commodity="wheat", country="FR", market="Rouen",
                              unit="tonne", currency="EUR", price_basis="Delivered Rouen", metadata={"product_label": "Feed wheat"}))
    result = asyncio.run(refresh_module.refresh_position_market_data(db, position, ingest_missing=False))
    db.refresh(position)
    assert result["price"]["outcome"] == "selection_required" and position.current_realizable_price is None


@pytest.mark.parametrize("variant", ["product", "stage"])
def test_eu_breadmaking_vs_feed_wheat_or_stages_at_one_market_require_selection(db, variant):
    _, org, _ = identity(db, f"eu-{variant}")
    if variant == "product":
        rows = [("BLT", "Breadmaking wheat", "Delivered Rouen", "244.36"), ("FEED", "Feed wheat", "Delivered Rouen", "205.10")]
    else:
        rows = [("BLT", "Breadmaking wheat", "Delivered Rouen", "244.36"), ("BLT", "Breadmaking wheat", "FOB Rouen", "238.00")]
    seed(db, *[_physical_series(f"eu_agrifood:FR:{code}:rouen:{fold_stage}", value, provider="eu_agrifood", commodity="wheat", country="FR",
                                market="Rouen", unit="tonne", currency="EUR", price_basis=stage, metadata={"product_label": label})
               for (code, label, stage, value), fold_stage in zip(rows, ["a", "b"])])
    position = _position(db, org, country="FR", commodity="wheat", reporting="EUR", price_currency="EUR", price=None, region="Rouen",
                         metadata={"price_policy": "automatic"})
    position.quantity_unit = "tonne"
    db.commit()
    resolution = plane.resolve_physical_price(db, position)
    assert resolution.price is None and resolution.state == "SELECTION_REQUIRED"
    assert sorted(Decimal(c["value"]) for c in resolution.trace["candidates"]) == sorted(Decimal(r[3]) for r in rows)  # provenance kept, nothing blended


def test_identical_quotes_are_the_only_ones_ever_aggregated(db):
    _, org, _ = identity(db, "identical")
    same = {"product_label": "Breadmaking wheat"}
    seed(db, *[_physical_series(f"eu_agrifood:FR:BLT:rouen:{suffix}", value, provider="eu_agrifood", commodity="wheat", country="FR", market="Rouen",
                                unit="tonne", currency="EUR", price_basis="Delivered Rouen", metadata=same) for suffix, value in (("x", "240"), ("y", "250"))])
    position = _position(db, org, country="FR", commodity="wheat", reporting="EUR", price_currency="EUR", price=None, region="Rouen",
                         metadata={"price_policy": "automatic"})
    position.quantity_unit = "tonne"
    db.commit()
    resolution = plane.resolve_physical_price(db, position)
    assert resolution.method == "median_of_identical_quotes" and resolution.price == Decimal("245.00000000")


def test_concurrent_workers_wait_for_the_slot_ingestion_barrier(db, monkeypatch, no_heartbeat):
    import threading

    from sqlalchemy.orm import sessionmaker

    from app.services.market_data_adapters import CONABWeeklyPricesSeries
    from tests.test_commercial_intelligence_global import CONAB_FIXTURE

    _, org_a, _ = identity(db, "barrier-a")
    _, org_b, _ = identity(db, "barrier-b")
    _position(db, org_a, name="A")
    _position(db, org_b, name="B")
    started, release = threading.Event(), threading.Event()

    class SlowConab(CONABWeeklyPricesSeries):
        async def collect(self, selectors):
            started.set()
            await asyncio.to_thread(release.wait, 20)
            line = "SOJA ;EM GRÃOS ;1;MT ;CENTRO-OESTE ;2026;10;{} - {} ;1;PREÇO RECEBIDO P/ PR;2,40\n"
            day = datetime.utcnow().strftime("%d-%m-%Y")
            return self._parse(iter([CONAB_FIXTURE[0], line.format(day, day)]), {("soybean", "MT")}, datetime.now(timezone.utc))

    monkeypatch.setitem(ADAPTERS, "conab_precos", SlowConab())
    for provider_id in ("fx_reference", "bcb_ptax"):
        monkeypatch.setattr(ADAPTERS[provider_id], "configured", lambda: False)
    evaluated: list[tuple[str, int]] = []
    real_evaluate = cycle.evaluate_organization

    async def spy_evaluate(db_, organization_id, **kwargs):
        points = db_.query(MarketDataPoint).count()
        evaluated.append((organization_id, points))
        return await real_evaluate(db_, organization_id, **kwargs)

    monkeypatch.setattr(cycle, "evaluate_organization", spy_evaluate)
    cycle.schedule_cycle(db)
    jobs = {job.tenant_id: job.id for job in _jobs(db)}
    Session = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)
    results: dict[str, str] = {}

    def worker(org_id: str, name: str) -> None:
        session = Session()
        try:
            results[name] = cycle.process_market_cycle_job(session, job_id=jobs[org_id], organization_id=org_id, worker_id=name)
        finally:
            session.close()

    thread_a = threading.Thread(target=worker, args=(org_a.id, "worker-a"))
    thread_a.start()
    assert started.wait(10), "worker A must be ingesting"
    thread_b = threading.Thread(target=worker, args=(org_b.id, "worker-b"))
    thread_b.start()
    thread_b.join(20)
    # B ran while A held the slot: it deferred, evaluated nothing, and its job is re-queued without a counted attempt.
    assert results["worker-b"] == "deferred" and evaluated == []
    db.expire_all()
    job_b = db.get(IngestionJob, jobs[org_b.id])
    assert (job_b.status, job_b.attempt_count, job_b.input_json["slot_deferrals"]) == ("queued", 0, 1)
    assert db.get(MarketCycleOrganizationState, org_b.id).last_completed_at is None
    release.set()
    thread_a.join(20)
    assert results["worker-a"] == "succeeded" and evaluated[0][0] == org_a.id and evaluated[0][1] >= 1
    db.query(IngestionJob).filter_by(id=jobs[org_b.id]).update({IngestionJob.next_attempt_at: datetime.utcnow() - timedelta(seconds=1)})
    db.commit()
    worker(org_b.id, "worker-b2")
    assert results["worker-b2"] == "succeeded"
    assert evaluated[-1] == (org_b.id, evaluated[0][1])  # B evaluated only after A's ingestion landed
    db.expire_all()
    assert db.get(IngestionJob, jobs[org_b.id]).output_json["providers"] == {"status": "already_ingested_this_slot"}
    assert db.query(MarketProviderRun).filter(MarketProviderRun.provider == "conab_precos").count() == 1  # contention is not a provider run


def test_deferrals_are_bounded(db, monkeypatch, no_heartbeat):
    _, org, _ = identity(db, "bounded-defer")
    _position(db, org)
    cycle.schedule_cycle(db)
    [job] = _jobs(db)

    async def busy(db_, slot, **kwargs):
        return {"status": "in_progress_elsewhere"}

    monkeypatch.setattr(cycle, "ingest_once_per_slot", busy)
    monkeypatch.setattr(cycle, "evaluate_organization", lambda *a, **k: asyncio.sleep(0, result={"positions": 0, "evaluated": 0, "failed": 0, "complete": True, "events_created": []}))
    for _ in range(cycle.MAX_SLOT_DEFERRALS):
        assert cycle.process_market_cycle_job(db, job_id=job.id, organization_id=org.id, worker_id="w") == "deferred"
        db.query(IngestionJob).filter_by(id=job.id).update({IngestionJob.next_attempt_at: datetime.utcnow() - timedelta(seconds=1)})
        db.commit()
    assert cycle.process_market_cycle_job(db, job_id=job.id, organization_id=org.id, worker_id="w") == "succeeded"
    db.refresh(job)
    assert job.output_json["shared_ingestion_complete"] is False and db.get(MarketCycleOrganizationState, org.id).last_status == "partial"


def test_tick_budget_covers_recovered_and_new_jobs_and_all_admitted_are_published(db, monkeypatch):
    from app.services import task_outbox_service

    orgs = []
    for index in range(4):
        _, org, _ = identity(db, f"budget-{index}")
        _position(db, org)
        orgs.append(org.id)
    start = datetime.utcnow() - timedelta(hours=2)
    # Ticks earlier: A and B were scheduled, published, and their workers died mid-run.
    cycle.schedule_cycle(db, now=start, batch=2)
    stale = _jobs(db)
    assert len(stale) == 2
    for job in stale:
        job.status, job.lease_expires_at, job.worker_id = "running", start, "dead"
    db.query(TaskOutbox).update({TaskOutbox.status: "published", TaskOutbox.updated_at: start})
    db.commit()
    result = cycle.schedule_cycle(db, now=datetime.utcnow(), batch=3)
    assert (result["recovered"], result["enqueued"], result["already_pending"]) == (2, 1, 0)  # 2 + 1 == budget 3
    sent = []

    class Publisher:
        def enqueue(self, job_id, tenant_id, task_type):
            sent.append(tenant_id)

    monkeypatch.setattr(task_outbox_service, "get_task_publisher", lambda: Publisher())
    published = task_outbox_service.publish_pending_outbox(db, limit=result["batch"], task_types=(cycle.TASK_TYPE,))
    assert published == {"published": 3, "failed": 0} and len(sent) == 3
    assert db.query(TaskOutbox).filter(TaskOutbox.task_type == cycle.TASK_TYPE, TaskOutbox.status == "pending").count() == 0
    # The organization beyond the budget was not admitted (no outbox row), so nothing admitted waits for the next cron.
    assert len(_jobs(db)) == 3
    # A backlog of publishable rows counts against the next tick's budget.
    db.query(TaskOutbox).update({TaskOutbox.status: "pending", TaskOutbox.next_attempt_at: None})
    db.commit()
    assert cycle.schedule_cycle(db, batch=3) == {"status": "ok", "enqueued": 0, "recovered": 0, "already_pending": 3, "batch": 3}
