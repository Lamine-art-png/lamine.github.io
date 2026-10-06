from datetime import datetime, timedelta
from types import SimpleNamespace
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.aws_marketplace import AwsMarketplaceRegistration
from app.platform_api.aws_marketplace_reconciliation import agreement_is_active, reconcile_registration, require_marketplace_access


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


def row(status="license_confirmed"):
    return SimpleNamespace(license_arn=LICENSE, customer_aws_account_id="123456789012", status=status, reconciled_at=None)


@pytest.mark.parametrize("change", [
    {"status": "TERMINATED"}, {"entitlement": "PENDING"},
    {"buyer": "999999999999"}, {"product": "prod-other"},
])
def test_reconciliation_rejects_wrong_or_inactive_agreement(change):
    assert not agreement_is_active(Agreements(**change), row(), "prod-test")


def test_reconciliation_requires_event_and_current_agreement():
    db = SimpleNamespace(commit=lambda: None)
    pending = row("pending_license")
    assert reconcile_registration(db, Agreements(), pending, "prod-test") == "pending_license"
    assert pending.reconciled_at is None
    confirmed = row()
    assert reconcile_registration(db, Agreements(), confirmed, "prod-test") == "active"
    assert confirmed.reconciled_at is not None
    assert reconcile_registration(db, Agreements(status="TERMINATED"), confirmed, "prod-test") == "revoked"


def test_key_access_fails_when_license_stale_or_revoked():
    license_row = row("active")
    license_row.reconciled_at = datetime.utcnow() - timedelta(hours=26)
    query = SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: license_row))
    db = SimpleNamespace(query=lambda model: query)
    with pytest.raises(HTTPException) as exc:
        require_marketplace_access(db, "org-test")
    assert exc.value.status_code == 403


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
