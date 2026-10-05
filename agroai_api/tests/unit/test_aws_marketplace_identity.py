from unittest.mock import Mock

import pytest

from app.platform_api.aws_marketplace import InvalidMarketplaceIdentity, resolve_purchase


def identity():
    return {"CustomerAWSAccountId": "123456789012", "LicenseArn": "arn:aws:license-manager:us-east-1:123456789012:license:synthetic-license", "ProductCode": "synthetic-product"}


def test_new_agreement_does_not_require_legacy_customer_identifier():
    client = Mock()
    client.resolve_customer.return_value = identity()
    result = resolve_purchase(client, "synthetic-token", "synthetic-product")
    assert result["license_arn"] == identity()["LicenseArn"]
    assert "CustomerIdentifier" not in result
    client.resolve_customer.assert_called_once_with(RegistrationToken="synthetic-token")


@pytest.mark.parametrize("field,value", [("ProductCode", "another-product"), ("CustomerAWSAccountId", "bad"), ("LicenseArn", "")])
def test_rejects_untrusted_or_wrong_product_identity(field, value):
    client = Mock()
    payload = identity()
    payload[field] = value
    client.resolve_customer.return_value = payload
    with pytest.raises(InvalidMarketplaceIdentity):
        resolve_purchase(client, "synthetic-token", "synthetic-product")


def test_unconfigured_product_never_calls_aws():
    client = Mock()
    with pytest.raises(InvalidMarketplaceIdentity):
        resolve_purchase(client, "synthetic-token", "")
    client.resolve_customer.assert_not_called()
