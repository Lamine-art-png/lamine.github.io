# ADR 006: Credential Vault Implementation

Decision: Keep the existing AES-256-GCM encrypted connector credential table and wrap it with a Platform API credential-vault boundary.

The table already supports unique nonces, associated data, versioned keys, rotation, revocation, and no plaintext persistence. A later managed KMS backend can replace the interface without changing route behavior.

The compatibility adapter is intentionally narrower than legacy connector custody. Decryption requires a Platform API key principal bound to the same organization and API project, an active service account with `connectors:sync`, an authorized provider-job call site, matching connection/workspace/provider/secret-type custody, and any configured provider allowlist. Portal-user or legacy tenant context alone is rejected.

Production Platform API use requires `CONNECTOR_CREDENTIAL_KEYS_JSON` to contain the active `CONNECTOR_CREDENTIAL_ACTIVE_KEY_VERSION`. The shared Portal vault may retain its existing master-key or domain-separated runtime-root compatibility behavior, but the Platform API adapter does not accept those fallbacks in production.
