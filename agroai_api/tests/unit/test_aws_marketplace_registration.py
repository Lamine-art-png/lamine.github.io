import pytest
import importlib.util
import sys
from pathlib import Path
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import get_db
from app.models.aws_marketplace import AwsMarketplaceRegistration

# Load the router independently of unrelated connector imports in api.v1.
spec = importlib.util.spec_from_file_location("aws_registration_test_route", Path(__file__).parents[2] / "app/api/v1/aws_marketplace.py")
route = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = route
spec.loader.exec_module(route)


@pytest.fixture
def registration(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    AwsMarketplaceRegistration.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    def database():
        with sessions() as db:
            yield db
    app = FastAPI()
    app.include_router(route.router)
    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(route.settings, "AWS_MARKETPLACE_ONBOARDING_ENABLED", True)
    monkeypatch.setattr(route.settings, "AWS_MARKETPLACE_PRODUCT_CODE", "test-product")
    monkeypatch.setattr(route.limiter, "enabled", False)
    identity = dict(product_code="test-product", customer_aws_account_id="123456789012", license_arn="arn:aws:license-manager:us-east-1:123456789012:license:l-test")
    monkeypatch.setattr(route, "_resolve", lambda token: identity)
    with TestClient(app) as client:
        yield client, sessions
    engine.dispose()


def test_retries_preserve_one_pending_registration_without_token(registration):
    client, sessions = registration
    responses = [client.post("/marketplace/aws/register", data={"x-amzn-marketplace-token": "sensitive-token"}) for _ in range(2)]
    assert all(response.status_code == 200 for response in responses)
    assert responses[0].text == responses[1].text
    assert "sensitive-token" not in responses[0].text
    assert responses[0].headers["cache-control"] == "no-store"
    with sessions() as db:
        rows = db.query(AwsMarketplaceRegistration).all()
        assert len(rows) == 1
        assert rows[0].status == "pending_license"
        assert not hasattr(rows[0], "registration_token")


def test_disabled_rejects_before_aws_call(registration, monkeypatch):
    client, _ = registration
    monkeypatch.setattr(route.settings, "AWS_MARKETPLACE_ONBOARDING_ENABLED", False)
    monkeypatch.setattr(route, "_resolve", lambda token: pytest.fail("AWS must not be called"))
    assert client.post("/marketplace/aws/register", data={"x-amzn-marketplace-token": "token"}).status_code == 503


@pytest.mark.parametrize("body,code", [("", 400), ("x-amzn-marketplace-token=a&x-amzn-marketplace-token=b", 400), ("a=" + "x" * 33000, 413)])
def test_invalid_form_never_reaches_aws(registration, monkeypatch, body, code):
    client, _ = registration
    monkeypatch.setattr(route, "_resolve", lambda token: pytest.fail("AWS must not be called"))
    assert client.post("/marketplace/aws/register", content=body, headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == code


def test_aws_failure_hides_exception_and_creates_no_registration(registration, monkeypatch):
    client, sessions = registration
    def fail(token):
        raise ClientError({"Error": {"Code": "InternalServiceError", "Message": "sensitive-upstream-detail"}}, "ResolveCustomer")
    monkeypatch.setattr(route, "_resolve", fail)
    response = client.post("/marketplace/aws/register", data={"x-amzn-marketplace-token": "token"})
    assert response.status_code == 503
    assert "sensitive-upstream-detail" not in response.text
    with sessions() as db:
        assert db.query(AwsMarketplaceRegistration).count() == 0


@pytest.mark.parametrize("status,expected_code", [("license_confirmed", 200), ("revoked", 409)])
def test_registration_preserves_license_events_arriving_first(registration, status, expected_code):
    client, sessions = registration
    with sessions() as db:
        db.add(AwsMarketplaceRegistration(
            product_code="test-product", customer_aws_account_id="123456789012",
            license_arn="arn:aws:license-manager:us-east-1:123456789012:license:l-test",
            status=status,
        ))
        db.commit()
    response = client.post("/marketplace/aws/register", data={"x-amzn-marketplace-token": "token"})
    assert response.status_code == expected_code
    with sessions() as db:
        assert db.query(AwsMarketplaceRegistration).one().status == status
