from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.aws_marketplace import AwsMarketplaceRegistration
from app.platform_api.aws_marketplace_reconciliation import (
    agreement_is_active,
    marketplace_plan_entitlement,
    reconcile_registration,
    require_marketplace_access,
)


LICENSE = "arn:aws:license-manager::123456789012:license/lic-test"


class Agreements:
    def __init__(self, status="ACTIVE", entitlement="PROVISIONED", buyer="123456789012", product="prod-test"):
        self.status, self.entitlement, self.buyer, self.product = status, entitlement, buyer, product

    def search_agreements(self, **kwargs):
        assert kwargs["filters"][2] == {"name": "LicenseArn", "values": [LICENSE]}
        return {"agreementViewSummaries": [{
            "agreementId": "agmt-test", "status": self.status,
            "acceptor": {"accountId": self.buyer},
            "proposalSummary": {"resources": [{"id": self.product, "type": "SaaSProduct"}]},
            "entitlements": [{"licenseArn": LICENSE}],
        }]}

    def get_agreement_entitlements(self, **kwargs):
        assert kwargs["agreementId"] == "agmt-test"
        return {"agreementEntitlements": [{
            "licenseArn": LICENSE, "status": self.entitlement,
            "resource": {"id": self.product, "type": "SaaSProduct"},
        }]}


class Entitlements:
    def __init__(self, dimensions=("developer",), buyer="123456789012", product="product-test", value=None):
        self.dimensions = dimensions
        self.buyer = buyer
        self.product = product
        self.value = value or {"IntegerValue": 1}

    def get_entitlements(self, **kwargs):
        assert kwargs["ProductCode"] == "product-test"
        assert kwargs["Filter"] == {"LICENSE_ARN": [LICENSE]}
        return {
            "Entitlements": [
                {
                    "LicenseArn": LICENSE,
                    "CustomerAWSAccountId": self.buyer,
                    "ProductCode": self.product,
                    "Dimension": dimension,
                    "ExpirationDate": datetime.now(timezone.utc) + timedelta(days=30),
                    "Value": self.value,
                }
                for dimension in self.dimensions
            ]
        }


def row(status="license_confirmed"):
    return SimpleNamespace(
        id="registration-test",
        license_arn=LICENSE,
        customer_aws_account_id="123456789012",
        product_code="product-test",
        status=status,
        reconciled_at=None,
        organization_id=None,
        plan_identifier=None,
        entitlement_expires_at=None,
    )


@pytest.mark.parametrize("change", [
    {"status": "TERMINATED"}, {"entitlement": "PENDING"},
    {"buyer": "999999999999"}, {"product": "prod-other"},
])
def test_reconciliation_rejects_wrong_or_inactive_agreement(change):
    assert not agreement_is_active(Agreements(**change), row(), "prod-test")


def test_marketplace_dimension_maps_to_exact_plan():
    plan, expiry = marketplace_plan_entitlement(Entitlements(("developer",)), row(), "product-test")
    assert plan == "developer"
    assert expiry is not None


@pytest.mark.parametrize("entitlements", [
    Entitlements(("developer", "scale")),
    Entitlements(("unknown",)),
    Entitlements(("developer",), buyer="999999999999"),
    Entitlements(("developer",), value={"IntegerValue": 0}),
])
def test_marketplace_dimension_fails_closed_when_ambiguous_or_invalid(entitlements):
    assert marketplace_plan_entitlement(entitlements, row(), "product-test") == (None, None)


def test_reconciliation_requires_event_agreement_and_known_plan():
    db = SimpleNamespace(commit=lambda: None)
    pending = row("pending_license")
    assert reconcile_registration(
        db, Agreements(), pending, "prod-test",
        entitlements=Entitlements(), product_code="product-test",
    ) == "pending_license"
    assert pending.reconciled_at is None

    confirmed = row()
    assert reconcile_registration(
        db, Agreements(), confirmed, "prod-test",
        entitlements=Entitlements(("developer",)), product_code="product-test",
    ) == "active"
    assert confirmed.plan_identifier == "developer"
    assert confirmed.reconciled_at is not None

    assert reconcile_registration(
        db, Agreements(status="TERMINATED"), confirmed, "prod-test",
        entitlements=Entitlements(), product_code="product-test",
    ) == "revoked"


def test_unknown_plan_never_becomes_active():
    db = SimpleNamespace(commit=lambda: None)
    confirmed = row()
    assert reconcile_registration(
        db, Agreements(), confirmed, "prod-test",
        entitlements=Entitlements(("unknown",)), product_code="product-test",
    ) == "license_confirmed"
    assert confirmed.reconciled_at is None
    assert confirmed.plan_identifier is None


def test_key_access_fails_when_license_stale_or_unmapped():
    license_row = row("active")
    license_row.plan_identifier = "developer"
    license_row.reconciled_at = datetime.utcnow() - timedelta(hours=26)
    query = SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: license_row))
    db = SimpleNamespace(query=lambda model: query)
    with pytest.raises(HTTPException) as exc:
        require_marketplace_access(db, "org-test")
    assert exc.value.status_code == 403

    license_row.reconciled_at = datetime.utcnow()
    license_row.plan_identifier = None
    with pytest.raises(HTTPException):
        require_marketplace_access(db, "org-test")


def test_aws_billing_owner_blocks_stripe_checkout_boundary():
    spec = importlib.util.spec_from_file_location("marketplace_billing_guard_test", Path(__file__).parents[2] / "app/api/v1/platform_billing.py")
    billing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(billing)
    engine = create_engine("sqlite://")
    AwsMarketplaceRegistration.__table__.create(engine)
    with Session(engine) as db:
        db.add(AwsMarketplaceRegistration(
            license_arn=LICENSE,
            customer_aws_account_id="123456789012",
            product_code="product-test",
            organization_id="org-test",
        ))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            billing._require_no_aws_billing(db, "org-test")
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "aws_marketplace_billing_owned"
    engine.dispose()
