from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.platform_api import (
    ApiProject,
    PlatformApiUsageEvent,
    PlatformWebhookEndpoint,
    PlatformWebhookEvent,
    PlatformWebhookOutbox,
)
from app.models.platform_product import (
    PlatformApiOperationCost,
    PlatformApiPlan,
    PlatformApiSubscription,
    PlatformCreditReservation,
    PlatformStripeMeterOutbox,
)
from app.models.saas import Organization, User, Workspace
from app.platform_api import stripe_metering, webhook_delivery
from app.platform_api.credits import reserve_credits
from app.platform_api.principal import PlatformPrincipal


POSTGRES_URL = os.getenv("PLATFORM_API_POSTGRES_TEST_URL", "").strip()
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="PLATFORM_API_POSTGRES_TEST_URL is not configured")


def _sessions():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _seed_project(Session):
    db = Session()
    suffix = uuid.uuid4().hex
    user = User(
        email=f"platform-product-concurrency-{suffix}@example.com",
        password_hash="x",
        email_verification_status="verified",
        email_verified_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()
    organization = Organization(
        name="Platform product concurrency",
        slug=f"platform-product-concurrency-{suffix}",
        owner_user_id=user.id,
        plan="enterprise",
        subscription_status="active",
    )
    db.add(organization)
    db.flush()
    workspace = Workspace(organization_id=organization.id, name="Concurrency", mode="evaluation")
    db.add(workspace)
    db.flush()
    project = ApiProject(
        organization_id=organization.id,
        workspace_id=workspace.id,
        name="Concurrency",
        slug=f"concurrency-{suffix}",
        environment="test",
        status="active",
        default_rate_limit_policy={},
        created_by_user_id=user.id,
    )
    db.add(project)
    db.commit()
    db.close()
    return user.id, organization.id, workspace.id, project.id


def _cleanup(
    Session,
    *,
    user_id: str,
    organization_id: str,
    workspace_id: str,
    plan_id: str | None = None,
    cost_id: str | None = None,
):
    db = Session()
    try:
        db.query(Workspace).filter(Workspace.id == workspace_id).delete()
        db.query(Organization).filter(Organization.id == organization_id).delete()
        if plan_id:
            db.query(PlatformApiPlan).filter(PlatformApiPlan.id == plan_id).delete()
        if cost_id:
            db.query(PlatformApiOperationCost).filter(PlatformApiOperationCost.id == cost_id).delete()
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
    finally:
        db.close()


def test_credit_reservations_use_two_sessions_and_cannot_oversubscribe(monkeypatch):
    engine, Session = _sessions()
    user_id, organization_id, workspace_id, project_id = _seed_project(Session)
    db = Session()
    catalog = f"concurrency-{uuid.uuid4().hex}"
    plan = PlatformApiPlan(
        catalog_version=catalog,
        plan_identifier="concurrency",
        display_name="Concurrency",
        status="test",
        active=True,
        currency="USD",
        included_credits=10,
        overages_allowed=False,
        limits_json={},
        support_tier="test",
    )
    cost = PlatformApiOperationCost(
        catalog_version=catalog,
        operation_id="concurrent_operation",
        operation_class="test",
        environment="test",
        credits=6,
        active=True,
        description="Concurrency proof",
    )
    db.add_all([plan, cost])
    db.flush()
    db.add(
        PlatformApiSubscription(
            organization_id=organization_id,
            plan_id=plan.id,
            status="active",
            status_slot="active",
            billing_mode="none",
        )
    )
    db.commit()
    plan_id, cost_id = plan.id, cost.id
    db.close()
    monkeypatch.setattr(settings, "PLATFORM_API_OPERATION_COST_CATALOG_VERSION", catalog)
    monkeypatch.setattr(settings, "PLATFORM_API_USAGE_METERING_ENFORCEMENT_ENABLED", True)
    barrier = threading.Barrier(2)

    def reserve(index: int) -> str:
        session = Session()
        principal = PlatformPrincipal(
            authentication_type="platform_api_key",
            organization_id=organization_id,
            workspace_id=workspace_id,
            api_project_id=project_id,
            environment="test",
            request_id=f"req-credit-{index}",
        )
        try:
            barrier.wait()
            try:
                reserve_credits(
                    session,
                    principal=principal,
                    operation_id="concurrent_operation",
                    logical_operation_id=f"logical-{index}",
                )
                session.commit()
                return "reserved"
            except HTTPException as exc:
                session.rollback()
                assert exc.status_code == 429
                return "denied"
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, (1, 2)))
        verify = Session()
        assert sorted(results) == ["denied", "reserved"]
        assert verify.query(PlatformCreditReservation).filter_by(organization_id=organization_id).count() == 1
        verify.close()
    finally:
        _cleanup(
            Session,
            user_id=user_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            plan_id=plan_id,
            cost_id=cost_id,
        )
        engine.dispose()


class _Publisher:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []
        self.lock = threading.Lock()

    def enqueue(self, job_id: str, tenant_id: str, task_type: str):
        with self.lock:
            self.calls.append((job_id, tenant_id, task_type))
        return job_id


def test_meter_and_webhook_outbox_claims_publish_once_across_two_sessions(monkeypatch):
    engine, Session = _sessions()
    user_id, organization_id, workspace_id, project_id = _seed_project(Session)
    db = Session()
    catalog = f"outbox-{uuid.uuid4().hex}"
    plan = PlatformApiPlan(
        catalog_version=catalog,
        plan_identifier="outbox",
        display_name="Outbox",
        status="test",
        active=True,
        currency="USD",
        included_credits=1,
        overages_allowed=True,
        limits_json={},
        support_tier="test",
    )
    db.add(plan)
    db.flush()
    subscription = PlatformApiSubscription(
        organization_id=organization_id,
        plan_id=plan.id,
        status="active",
        status_slot="active",
        billing_mode="stripe",
        stripe_customer_id="cus_test_concurrency",
    )
    usage = PlatformApiUsageEvent(
        organization_id=organization_id,
        api_project_id=project_id,
        environment="test",
        event_type="api_credit",
        metric="api_credits",
        quantity=1,
        cost_units=1,
        operation="concurrency",
        idempotency_key=f"usage-{uuid.uuid4().hex}",
    )
    db.add_all([subscription, usage])
    db.flush()
    meter = PlatformStripeMeterOutbox(
        organization_id=organization_id,
        subscription_id=subscription.id,
        usage_event_id=usage.id,
        meter_event_identifier=f"meter-{uuid.uuid4().hex}",
        meter_event_name="agroai_api_credits",
        quantity=1,
        status="pending",
    )
    endpoint = PlatformWebhookEndpoint(
        organization_id=organization_id,
        api_project_id=project_id,
        url="https://hooks.example.test/agroai",
        subscribed_event_types=["field.updated"],
        status="active",
        signing_secret_hash="0" * 64,
        signing_secret_prefix="whsec_test",
    )
    event = PlatformWebhookEvent(
        organization_id=organization_id,
        api_project_id=project_id,
        event_type="field.updated",
        version="test",
        payload_json={"synthetic": True},
    )
    db.add_all([meter, endpoint, event])
    db.flush()
    webhook = PlatformWebhookOutbox(
        organization_id=organization_id,
        api_project_id=project_id,
        event_id=event.id,
        endpoint_id=endpoint.id,
        status="pending",
        next_attempt_at=datetime.utcnow(),
    )
    db.add(webhook)
    db.commit()
    meter_id, webhook_id, plan_id = meter.id, webhook.id, plan.id
    db.close()

    meter_publisher = _Publisher()
    webhook_publisher = _Publisher()
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_WEBHOOK_DELIVERY_ENABLED", True)
    monkeypatch.setattr(stripe_metering, "get_task_publisher", lambda: meter_publisher)
    monkeypatch.setattr(webhook_delivery, "get_task_publisher", lambda: webhook_publisher)

    def concurrent_publish(work):
        barrier = threading.Barrier(2)

        def run(_index: int):
            session = Session()
            try:
                barrier.wait()
                return work(session)
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, (1, 2)))

    try:
        meter_results = concurrent_publish(lambda session: stripe_metering.publish_pending_meter_outbox(session, limit=1))
        webhook_results = concurrent_publish(lambda session: webhook_delivery.publish_pending_webhook_outbox(session, limit=1))
        assert sum(item["published"] for item in meter_results) == 1
        assert sum(item["published"] for item in webhook_results) == 1
        assert meter_publisher.calls == [(meter_id, organization_id, stripe_metering.STRIPE_METER_TASK_TYPE)]
        assert webhook_publisher.calls == [(webhook_id, organization_id, webhook_delivery.WEBHOOK_TASK_TYPE)]
    finally:
        _cleanup(
            Session,
            user_id=user_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            plan_id=plan_id,
        )
        engine.dispose()
