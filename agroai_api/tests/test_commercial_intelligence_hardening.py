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
    for name in ("drain_pending_outbox", "run_connector_object_gc"):
        monkeypatch.setattr(cloudflare_queue, name, lambda **kwargs: {"published": 0})
    for name in ("_drain_webhook_outbox", "_drain_meter_outbox", "_run_platform_api_maintenance", "_run_lifecycle_emails"):
        monkeypatch.setattr(cloudflare_queue, name, lambda: {})
    monkeypatch.setattr("app.services.market_intelligence_cycle.schedule_cycle_once", lambda **kwargs: calls.append(kwargs) or {"status": "ok", "enqueued": 3})
    result = asyncio.run(cloudflare_queue.drain_task_outbox())
    assert result["market_intelligence_cycle"] == {"status": "ok", "enqueued": 3} and calls == [{"trigger": "scheduled"}]
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
        return {"complete": True, "evaluated": 1}

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
    cycle.schedule_cycle(db)
    [job] = _jobs(db)
    assert cycle.process_market_cycle_job(db, job_id=job.id, organization_id=org_id, worker_id="w") == "succeeded"
    db.refresh(job)
    assert job.output_json["providers"]["conab_precos"]["status"] == "ok" and job.output_json["complete"] is True
    assert len(calls) == 1 and calls[0] == [{"commodity": "soybean", "uf": "MT"}]
    events = db.query(MarketMaterialityEvent).filter_by(position_id=position_id).all()
    assert events and events[0].level in {"HIGH", "CRITICAL"}
    assert job.output_json["notifications"]["status"] == "disabled"
    # Shared evidence is fresh: the next organization job does not re-fetch CONAB.
    again = asyncio.run(cycle.run_organization_cycle(db, org_id, time_budget_seconds=60))
    assert again["providers"]["conab_precos"]["status"] == "fresh_enough" and len(calls) == 1


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
