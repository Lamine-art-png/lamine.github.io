# ADR 006: Credential Vault Implementation

Decision: Keep the existing AES-256-GCM encrypted connector credential table and wrap it with a Platform API credential-vault boundary.

The table already supports unique nonces, associated data, versioned keys, and no plaintext persistence. A later managed KMS backend can replace the interface without changing route behavior.
