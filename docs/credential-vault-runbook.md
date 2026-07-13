# Credential Vault Runbook

Connector credentials are stored in the existing connector credential vault as AES-256-GCM encrypted blobs with unique nonces and associated data. The Platform API does not duplicate encryption; it wraps the shared vault with a compatibility adapter in `app/platform_api/credential_vault.py`.

Implementation details:

- Algorithm: AES-256-GCM.
- Nonce: 96-bit random nonce from `os.urandom(12)` per stored secret.
- Associated data: tenant/organization ID, connection ID, provider ID, and key version from the existing connector vault.
- Platform API adapter authorization: organization ownership, API project ownership, workspace compatibility, active service account, `connectors:sync` scope, provider restrictions, secret type metadata, and provider-job-only retrieval.
- Authentication boundary: only `platform_api_key` principals are accepted; Portal users, internal services, and legacy tenant context do not inherit retrieval rights.
- Connection boundary: the connection must be active, belong to the principal organization, match the requested provider, and match the project/workspace binding recorded when the Platform API secret was stored.
- Service-account boundary: the service account must be active and bound to both the principal organization and API project. Both the account and the principal must hold `connectors:sync`.
- Job boundary: callers must construct an internal `CredentialVaultContext` with provider-job authorization. No header, query parameter, cookie, JWT claim, or browser value can enable this internal boolean.
- Secret boundary: provider and secret type must match the stored connection metadata; cross-provider and cross-secret-type reads fail closed.
- Database fields: `connector_credentials.key_version`, `algorithm`, `nonce_b64`, `ciphertext_b64`, `token_expires_at`, `scopes_json`, and `revoked_at`.
- Metadata inspection excludes nonce and ciphertext.
- Customer and browser responses must never expose plaintext, ciphertext, key material, provider credentials, webhook secrets, or raw authorization headers.

Production requirements:

- Platform API production requires `CONNECTOR_CREDENTIAL_KEYS_JSON`; a single master key or a key derived from application runtime secrets is not accepted by the adapter.
- The keyring must contain the active version set with `CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION`, and each value must decode to exactly 32 bytes.
- Keys stored outside the database.
- Production must not fall back to test key material.
- No provider credentials in logs, responses, analytics, or browser bundles.

Rotation:

1. Add new key version to the keyring.
2. Set the active version.
3. Keep old versions available for reads.
4. Migrate rows through the vault interface.
5. Remove old versions only after proof that no rows need them.

Revocation sets `revoked_at` through the shared vault and immediately removes the row from active retrieval. Rotation writes a new nonce, ciphertext, and active key version through the same compatibility adapter; old plaintext and ciphertext are never returned.
