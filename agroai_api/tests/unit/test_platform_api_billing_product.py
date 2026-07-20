from __future__ import annotations

from datetime import datetime, timedelta

from app.api.v1 import platform_billing
from app.core.config import settings
from app.core.security import create_access_token
from app.models.platform_product import (
    PlatformApiPlan,
    PlatformApiSubscription,
    PlatformCheckoutIdempotency,
    PlatformRequestLog,
    PlatformStripeEvent,
    PlatformStripeMeterOutbox,
)
from app.platform_api import stripe_metering
from app.platform_api.maintenance import enforce_request_log_retention, expire_payment_grace_periods
from tests.unit.test_platform_api_foundation import _project_and_key


def _developer_plan(db) -> PlatformApiPlan:
    row = PlatformApiPlan(
        catalog_version=settings.PLATFORM_API_PLAN_CATALOG_VERSION,
        plan_identifier="developer",
        display_name="Developer",
        status="private_preview",
        active=True,
        currency="USD",
        monthly_price_cents=14900,
        annual_price_cents=143000,
        included_credits=250000,
        overage_price_per_1000_cents=75,
        overages_allowed=True,
        limits_json={"projects": 3},
        support_tier="email",
        stripe_monthly_price_config_key="PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID",
        stripe_annual_price_config_key="PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_PRICE_ID",
        stripe_overage_price_config_key="PLATFORM_API_STRIPE_DEVELOPER_OVERAGE_PRICE_ID",
    )
    db.add(row)
    db.commit()
    return row


def _enable_checkout(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_BILLING_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_CHECKOUT_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_SECRET_KEY", "sk_test_platform_api")
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_DEVELOPER_MONTHLY_PRICE_ID", "price_server_monthly")
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_DEVELOPER_ANNUAL_PRICE_ID", "price_server_annual")
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_DEVELOPER_OVERAGE_PRICE_ID", "price_server_overage")


def test_checkout_uses_only_server_catalog_prices_and_includes_metered_overage(client, db, monkeypatch):
    user, organization, *_ = _project_and_key(db)
    organization.verification_status = "approved"
    plan = _developer_plan(db)
    _enable_checkout(monkeypatch)
    captured: dict = {}

    monkeypatch.setattr(
        platform_billing.stripe.Customer,
        "create",
        lambda **kwargs: {"id": "cus_platform_api"},
    )

    def create_checkout(**kwargs):
        captured.update(kwargs)
        return {"id": "cs_test", "url": "https://checkout.stripe.test/session"}

    monkeypatch.setattr(platform_billing.stripe.checkout.Session, "create", create_checkout)
    headers = {
        "Authorization": f"Bearer {create_access_token({'sub': user.id})}",
        "Idempotency-Key": "checkout-1",
    }
    response = client.post(
        "/v1/platform/developer/billing/checkout",
        headers=headers,
        json={"plan": "developer", "billing_interval": "monthly"},
    )

    assert response.status_code == 200
    assert captured["line_items"] == [
        {"price": "price_server_monthly", "quantity": 1},
        {"price": "price_server_overage"},
    ]
    assert captured["metadata"]["organization_id"] == organization.id
    assert captured["metadata"]["api_plan_id"] == plan.id
    assert db.query(PlatformApiSubscription).filter_by(organization_id=organization.id).one().stripe_price_id == "price_server_monthly"

    manipulated = client.post(
        "/v1/platform/developer/billing/checkout",
        headers={**headers, "Idempotency-Key": "checkout-2"},
        json={"plan": "developer", "billing_interval": "monthly", "price_id": "price_attacker"},
    )
    assert manipulated.status_code == 422


def test_checkout_idempotency_is_local_payload_bound_and_organization_scoped(
    client,
    db,
    monkeypatch,
):
    first_user, first_org, *_ = _project_and_key(db)
    second_user, second_org, *_ = _project_and_key(db)
    first_org.verification_status = second_org.verification_status = "approved"
    _developer_plan(db)
    _enable_checkout(monkeypatch)
    checkout_calls: list[dict] = []
    customer_counter = iter(("cus_first", "cus_second"))

    monkeypatch.setattr(
        platform_billing.stripe.Customer,
        "create",
        lambda **_kwargs: {"id": next(customer_counter)},
    )

    def create_checkout(**kwargs):
        checkout_calls.append(kwargs)
        ordinal = len(checkout_calls)
        return {
            "id": f"cs_test_{ordinal}",
            "url": f"https://checkout.stripe.test/session/{ordinal}",
        }

    monkeypatch.setattr(
        platform_billing.stripe.checkout.Session,
        "create",
        create_checkout,
    )
    payload = {"plan": "developer", "billing_interval": "monthly"}
    first_headers = {
        "Authorization": f"Bearer {create_access_token({'sub': first_user.id})}",
        "Idempotency-Key": "shared-client-key",
    }
    second_headers = {
        "Authorization": f"Bearer {create_access_token({'sub': second_user.id})}",
        "Idempotency-Key": "shared-client-key",
    }

    first = client.post(
        "/v1/platform/developer/billing/checkout",
        headers=first_headers,
        json=payload,
    )
    replay = client.post(
        "/v1/platform/developer/billing/checkout",
        headers=first_headers,
        json=payload,
    )
    conflict = client.post(
        "/v1/platform/developer/billing/checkout",
        headers=first_headers,
        json={"plan": "developer", "billing_interval": "annual"},
    )
    other_org = client.post(
        "/v1/platform/developer/billing/checkout",
        headers=second_headers,
        json=payload,
    )

    assert first.status_code == replay.status_code == other_org.status_code == 200
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
    assert len(checkout_calls) == 2
    assert checkout_calls[0]["idempotency_key"] != "shared-client-key"
    assert (
        checkout_calls[0]["idempotency_key"]
        != checkout_calls[1]["idempotency_key"]
    )
    assert (
        db.query(PlatformCheckoutIdempotency)
        .filter_by(client_key="shared-client-key", status="completed")
        .count()
        == 2
    )


def test_api_billing_webhook_is_separate_signed_deduplicated_and_order_safe(client, db, monkeypatch):
    _user, organization, *_ = _project_and_key(db)
    plan = _developer_plan(db)
    subscription = PlatformApiSubscription(
        organization_id=organization.id,
        plan_id=plan.id,
        status="active",
        status_slot="active",
        billing_mode="stripe",
        stripe_customer_id="cus_platform",
        stripe_subscription_id="sub_platform",
    )
    db.add(subscription)
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_BILLING_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_WEBHOOK_SECRET", "whsec_platform_api")

    current = {
        "id": "evt_current",
        "type": "customer.subscription.updated",
        "created": 2_000_000_000,
        "livemode": False,
        "data": {
            "object": {
                "object": "subscription",
                "id": "sub_platform",
                "customer": "cus_platform",
                "status": "past_due",
                "metadata": {
                    "organization_id": organization.id,
                    "api_subscription_id": subscription.id,
                    "billing_product": "platform_api",
                },
            }
        },
    }
    monkeypatch.setattr(platform_billing.stripe.Webhook, "construct_event", lambda *_args, **_kwargs: current)
    response = client.post(
        "/v1/platform/billing/stripe-webhook",
        headers={"Stripe-Signature": "valid"},
        content=b"{}",
    )
    assert response.json()["status"] == "processed"
    db.refresh(subscription)
    assert subscription.status == "past_due"

    duplicate = client.post(
        "/v1/platform/billing/stripe-webhook",
        headers={"Stripe-Signature": "valid"},
        content=b"{}",
    )
    assert duplicate.json()["status"] == "duplicate"
    assert db.query(PlatformStripeEvent).filter_by(stripe_event_id="evt_current").count() == 1

    older = {
        **current,
        "id": "evt_older",
        "created": 1_999_999_000,
        "data": {"object": {**current["data"]["object"], "status": "active"}},
    }
    monkeypatch.setattr(platform_billing.stripe.Webhook, "construct_event", lambda *_args, **_kwargs: older)
    ignored = client.post(
        "/v1/platform/billing/stripe-webhook",
        headers={"Stripe-Signature": "valid"},
        content=b"{}",
    )
    assert ignored.json()["status"] == "ignored_out_of_order"
    db.refresh(subscription)
    assert subscription.status == "past_due"


def test_portal_and_unrelated_invoice_events_never_mutate_api_subscription(
    client,
    db,
    monkeypatch,
):
    _user, organization, *_ = _project_and_key(db)
    plan = _developer_plan(db)
    organization.stripe_customer_id = "cus_shared"
    subscription = PlatformApiSubscription(
        organization_id=organization.id,
        plan_id=plan.id,
        status="active",
        status_slot="active",
        billing_mode="stripe",
        stripe_customer_id="cus_shared",
        stripe_subscription_id="sub_platform_api",
    )
    db.add(subscription)
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_BILLING_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_MODE", "test")
    monkeypatch.setattr(
        settings,
        "PLATFORM_API_STRIPE_WEBHOOK_SECRET",
        "whsec_platform_api",
    )

    portal_event = {
        "id": "evt_portal_subscription",
        "type": "customer.subscription.updated",
        "created": 2_000_000_100,
        "livemode": False,
        "data": {
            "object": {
                "object": "subscription",
                "id": "sub_portal",
                "customer": "cus_shared",
                "status": "past_due",
                "metadata": {
                    "organization_id": organization.id,
                    "billing_product": "enterprise_portal",
                },
            }
        },
    }
    monkeypatch.setattr(
        platform_billing.stripe.Webhook,
        "construct_event",
        lambda *_args, **_kwargs: portal_event,
    )
    ignored = client.post(
        "/v1/platform/billing/stripe-webhook",
        headers={"Stripe-Signature": "valid"},
        content=b"portal",
    )
    assert ignored.json()["status"] == "ignored_non_platform_api"
    db.refresh(subscription)
    assert subscription.status == "active"
    assert (
        db.query(PlatformStripeEvent)
        .filter_by(
            stripe_event_id="evt_portal_subscription",
            status="ignored_non_platform_api",
        )
        .count()
        == 1
    )

    unrelated_invoice = {
        "id": "evt_unrelated_invoice",
        "type": "invoice.payment_failed",
        "created": 2_000_000_200,
        "livemode": False,
        "data": {
            "object": {
                "object": "invoice",
                "id": "in_unrelated",
                "customer": "cus_shared",
                "subscription": "sub_unrelated",
                "metadata": {
                    "organization_id": organization.id,
                    "billing_product": "platform_api",
                },
            }
        },
    }
    monkeypatch.setattr(
        platform_billing.stripe.Webhook,
        "construct_event",
        lambda *_args, **_kwargs: unrelated_invoice,
    )
    unrelated = client.post(
        "/v1/platform/billing/stripe-webhook",
        headers={"Stripe-Signature": "valid"},
        content=b"invoice",
    )
    assert unrelated.json()["status"] == "ignored_non_platform_api"
    db.refresh(subscription)
    assert subscription.status == "active"
    assert (
        db.query(PlatformStripeEvent)
        .filter_by(
            stripe_event_id="evt_unrelated_invoice",
            status="ignored_non_platform_api",
        )
        .count()
        == 1
    )


def test_meter_export_is_idempotent_and_never_exports_twice(db, monkeypatch):
    _user, organization, _workspace, _project, *_ = _project_and_key(db)
    plan = _developer_plan(db)
    subscription = PlatformApiSubscription(
        organization_id=organization.id,
        plan_id=plan.id,
        status="active",
        status_slot="active",
        billing_mode="stripe",
        stripe_customer_id="cus_platform",
    )
    db.add(subscription)
    db.flush()
    outbox = PlatformStripeMeterOutbox(
        organization_id=organization.id,
        subscription_id=subscription.id,
        usage_event_id="usage-logical-1",
        meter_event_identifier="agroai-logical-usage-1",
        meter_event_name="agroai_api_credits",
        quantity=25,
        status="queued",
    )
    db.add(outbox)
    db.commit()
    outbox_id = outbox.id
    organization_id = organization.id
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_METER_EXPORT_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_SECRET_KEY", "sk_test_platform_api")
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_METER_EVENT_NAME", "agroai_api_credits")
    monkeypatch.setattr(settings, "PLATFORM_API_STRIPE_METER_ID", "mtr_platform")
    monkeypatch.setattr(stripe_metering, "SessionLocal", lambda: db)
    calls: list[dict] = []

    def export(**kwargs):
        calls.append(kwargs)
        return type("MeterEvent", (), {"livemode": False})()

    monkeypatch.setattr(stripe_metering.stripe.billing.MeterEvent, "create", export)
    assert stripe_metering.process_meter_export_task(
        outbox_id=outbox_id,
        organization_id=organization_id,
        worker_id="worker-1",
    ) == "succeeded"
    assert stripe_metering.process_meter_export_task(
        outbox_id=outbox_id,
        organization_id=organization_id,
        worker_id="worker-2",
    ) == "exported"
    assert len(calls) == 1
    assert calls[0]["identifier"] == "agroai-logical-usage-1"
    assert calls[0]["payload"] == {"stripe_customer_id": "cus_platform", "value": "25"}


def test_active_plan_limit_cannot_be_bypassed_by_broader_enrollment(client, db, monkeypatch):
    user, organization, *_ = _project_and_key(db)
    organization.verification_status = "approved"
    plan = _developer_plan(db)
    plan.limits_json = {"projects": 1}
    db.add(
        PlatformApiSubscription(
            organization_id=organization.id,
            plan_id=plan.id,
            status="active",
            status_slot="active",
            billing_mode="stripe",
        )
    )
    db.commit()
    monkeypatch.setattr(settings, "PLATFORM_API_DEVELOPER_CONTROL_PLANE_ENABLED", True)
    monkeypatch.setattr(settings, "PLATFORM_API_TEST_PROJECTS_ENABLED", True)

    response = client.post(
        "/v1/platform/developer/projects",
        headers={"Authorization": f"Bearer {create_access_token({'sub': user.id})}"},
        json={"name": "Second project", "slug": "second-project", "environment": "test"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "platform_resource_limit_reached"
    assert response.json()["limit"] == 1


def test_payment_grace_expiration_and_plan_request_log_retention_are_deterministic(db):
    _user, organization, _workspace, project, *_ = _project_and_key(db)
    plan = _developer_plan(db)
    plan.limits_json = {"request_log_retention_days": 1}
    subscription = PlatformApiSubscription(
        organization_id=organization.id,
        plan_id=plan.id,
        status="past_due",
        status_slot="active",
        billing_mode="stripe",
        grace_ends_at=datetime.utcnow() - timedelta(minutes=1),
    )
    db.add(subscription)
    db.add_all(
        [
            PlatformRequestLog(
                organization_id=organization.id,
                api_project_id=project.id,
                request_id="req-expired",
                method="GET",
                operation_id="fields.list",
                status_code=200,
                latency_ms=10,
                environment="test",
                created_at=datetime.utcnow() - timedelta(days=2),
            ),
            PlatformRequestLog(
                organization_id=organization.id,
                api_project_id=project.id,
                request_id="req-current",
                method="GET",
                operation_id="fields.list",
                status_code=200,
                latency_ms=10,
                environment="test",
                created_at=datetime.utcnow(),
            ),
        ]
    )
    db.commit()

    assert expire_payment_grace_periods(db) == 1
    assert enforce_request_log_retention(db) == 1
    db.commit()

    db.refresh(subscription)
    assert subscription.status == "unpaid"
    assert db.query(PlatformRequestLog).filter_by(organization_id=organization.id).one().request_id == "req-current"
