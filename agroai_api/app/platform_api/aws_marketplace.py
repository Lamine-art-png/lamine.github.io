"""AWS token boundary. Credentials come from the standard AWS SDK provider chain."""
import re


class InvalidMarketplaceIdentity(ValueError):
    pass


def resolve_purchase(client, token: str, expected_product_code: str) -> dict[str, str]:
    if not token or len(token) > 16384 or not expected_product_code:
        raise InvalidMarketplaceIdentity("Invalid registration configuration or token")
    result = client.resolve_customer(RegistrationToken=token)
    account_id = result.get("CustomerAWSAccountId", "")
    license_arn = result.get("LicenseArn", "")
    if (
        result.get("ProductCode") != expected_product_code
        or not re.fullmatch(r"[0-9]{12}", account_id)
        or not re.fullmatch(r"arn:aws[a-z-]*:license-manager:[^:]*:[0-9]{12}:license:[A-Za-z0-9-]+", license_arn)
    ):
        raise InvalidMarketplaceIdentity("AWS returned an unexpected purchase identity")
    return {
        "customer_aws_account_id": account_id,
        "license_arn": license_arn,
        "product_code": expected_product_code,
    }
