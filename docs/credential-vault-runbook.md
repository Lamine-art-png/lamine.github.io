# Credential Vault Runbook

Connector credentials are stored in the existing connector credential vault as AES-256-GCM encrypted blobs with unique nonces and associated data. The Platform API does not duplicate encryption; it wraps the shared vault with a compatibility adapter in `app/platform_api/credential_vault.py`.

Implementation details:

- Algorithm: AES-256-GCM.
- Nonce: 96-bit random nonce from `os.urandom(12)` per stored secret.
- Associated data: tenant/organization ID, connection ID, provider ID, and key version from the existing connector vault.
- Platform API adapter authorization: organization ownership, API project ownership, workspace compatibility, active service account, `connectors:sync` scope, provider restrictions, secret type metadata, and provider-job-only retrieval.
- Database fields: `connector_credentials.key_version`, `algorithm`, `nonce_b64`, `ciphertext_b64`, `token_expires_at`, `scopes_json`, and `revoked_at`.
- Metadata inspection excludes nonce and ciphertext.
- Customer and browser responses must never expose plaintext, ciphertext, key material, provider credentials, webhook secrets, or raw authorization headers.

Production requirements:

- `CONNECTOR_CREDENTIAL_MASTER_KEY` or `CONNECTOR_CREDENTIAL_KEYS_JSON`.
- Active key version set with `CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION`.
- Keys stored outside the database.
- Production must not fall back to test key material.
- No provider credentials in logs, responses, analytics, or browser bundles.

Rotation:

1. Add new key version to the keyring.
2. Set the active version.
3. Keep old versions available for reads.
4. Migrate rows through the vault interface.
5. Remove old versions only after proof that no rows need them.
