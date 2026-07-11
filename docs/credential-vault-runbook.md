# Credential Vault Runbook

Connector credentials are stored as AES-256-GCM encrypted blobs with unique nonces and associated data.

Production requirements:

- `CONNECTOR_CREDENTIAL_MASTER_KEY` or `CONNECTOR_CREDENTIAL_KEYS_JSON`.
- Active key version set with `CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION`.
- Keys stored outside the database.
- No provider credentials in logs, responses, analytics, or browser bundles.

Rotation:

1. Add new key version to the keyring.
2. Set the active version.
3. Keep old versions available for reads.
4. Migrate rows through the vault interface.
5. Remove old versions only after proof that no rows need them.
