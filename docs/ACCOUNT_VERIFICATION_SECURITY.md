# Automated Account Verification and Portal Security

## Scope

The Enterprise Portal now evaluates new registrations before granting live operational access. The decision engine checks organization evidence, agricultural relevance, email-domain risk, professional identity evidence, and obvious placeholder or disposable-account signals.

Consumer email domains such as Gmail and Outlook remain eligible, but require stronger supporting evidence than an organization-domain email. Disposable email domains and applications without a credible agricultural use case are rejected automatically.

## Access states

- `pending_email`: automated evidence checks passed, but control of the email address is not yet proven.
- `active`: email verification and organization approval requirements are satisfied.
- `rejected`: automated checks did not establish a credible agricultural organization or professional use case.
- `suspended`: access is disabled by a server-side account control.

Legacy organizations are migrated to `approved_legacy` to avoid breaking existing legitimate customers. Backend authorization—not frontend visibility—enforces organization and workspace access.

## Security controls included

- Server-side account, membership, organization, workspace, and role checks.
- Organization identity carried in JWT claims and revalidated against current database membership.
- Automatic email verification before strict-registration accounts become active.
- Login failure tracking and temporary account lockout.
- Production authentication rate limits with Redis support and an in-memory fallback.
- AES-256-GCM encryption for submitted phone evidence.
- HMAC-based privacy hashes for security audit identifiers instead of raw email, IP, or user-agent storage.
- Stricter production CORS behavior and API/browser security headers.
- Alembic migration and schema-readiness checks for verification and audit tables.

## Configuration

`ACCOUNT_VERIFICATION_MODE` supports:

- `auto`: enforce in production and remain compatibility-safe outside production.
- `enforce`: enforce in every environment.
- `disabled`: preserve legacy registration behavior for controlled testing or rollback.

The default is `auto`.

## Deliberate limits

This release does not claim that the platform cannot be compromised. It reduces attack surface, denies unverified production access, improves auditability, and limits damage from weak or fraudulent accounts.

This release does not perform government-ID verification and does not add a third-party KYC provider. It also does not add passkeys or TOTP MFA. Those require a dedicated identity-provider decision and separate rollout.
