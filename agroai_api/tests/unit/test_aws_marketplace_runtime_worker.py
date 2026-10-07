from app.core.config import settings
from app.services import aws_marketplace_worker
from app.services.aws_marketplace_worker import (
    _event_configuration_valid,
    probe_entitlements_service_once,
    start_aws_marketplace_worker,
)


def test_marketplace_runtime_worker_defaults_to_disabled(monkeypatch):
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_EVENTS_ENABLED", False)
    assert start_aws_marketplace_worker() is None


def test_marketplace_runtime_configuration_accepts_exact_seller_queue(monkeypatch):
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_SELLER_ACCOUNT_ID", "987432215840")
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_REGION", "us-east-1")
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_PRODUCT_CODE", "synthetic-product-code")
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_PRODUCT_ID", "prod-rrjrdndw2eptq")
    monkeypatch.setattr(
        settings,
        "AWS_MARKETPLACE_QUEUE_URL",
        "https://sqs.us-east-1.amazonaws.com/987432215840/agroai-marketplace-events",
    )
    assert _event_configuration_valid() is True


def test_marketplace_runtime_configuration_rejects_cross_account_queue(monkeypatch):
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_SELLER_ACCOUNT_ID", "987432215840")
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_REGION", "us-east-1")
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_PRODUCT_CODE", "synthetic-product-code")
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_PRODUCT_ID", "prod-rrjrdndw2eptq")
    monkeypatch.setattr(
        settings,
        "AWS_MARKETPLACE_QUEUE_URL",
        "https://sqs.us-east-1.amazonaws.com/111111111111/agroai-marketplace-events",
    )
    assert _event_configuration_valid() is False


def test_get_entitlements_probe_calls_real_api_shape(monkeypatch):
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_EVENTS_ENABLED", True)
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_SELLER_ACCOUNT_ID", "987432215840")
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_REGION", "us-east-1")
    monkeypatch.setattr(settings, "AWS_MARKETPLACE_PRODUCT_CODE", "synthetic-product-code")
    monkeypatch.setattr(aws_marketplace_worker, "_credentials_match_seller", lambda: True)

    calls = []

    class FakeEntitlements:
        def get_entitlements(self, **kwargs):
            calls.append(kwargs)
            return {"Entitlements": []}

    def fake_client(name, **kwargs):
        assert name == "marketplace-entitlement"
        assert kwargs["region_name"] == "us-east-1"
        return FakeEntitlements()

    monkeypatch.setattr(aws_marketplace_worker.boto3, "client", fake_client)

    result = probe_entitlements_service_once()

    assert result["status"] == "ok"
    assert result["entitlements_seen"] == 0
    assert calls == [{"ProductCode": "synthetic-product-code", "MaxResults": 1}]
