locals {
  managed_runtime_secret_names = toset([
    "SECRET_KEY",
    "REDIS_URL",
    "CONNECTOR_CREDENTIAL_MASTER_KEY",
    "CONNECTOR_CREDENTIAL_KEYS_JSON",
    "OAUTH_STATE_SIGNING_KEY",
  ])
}
