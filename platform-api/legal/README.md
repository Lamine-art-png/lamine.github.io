# Platform API legal launch package

This directory is the legal-release boundary for public TEST self-service.

## State

`legal_review_required`

The repository contains a technical clickthrough/acceptance system and draft documents for counsel review. The drafts are **not** represented as legal advice, attorney-approved terms, or effective customer agreements.

Public TEST self-service must remain fail closed until all of the following are true:

1. counsel approves the exact API Terms, Acceptable Use Policy, Privacy Notice, and any DPA required for the launch;
2. the approved documents are copied to `platform-api/assets/legal/` with stable versioned filenames;
3. `approved-catalog.json` is added with `status: "counsel_approved"`, document versions, SHA-256 content digests, approval date, and reviewer record;
4. the same document type/version/digest values are published as `approved_effective` Platform terms records in production;
5. the activation workflow verifies the production legal catalog before enabling automatic TEST enrollment.

Do not create `approved-catalog.json` merely to make CI green. It is evidence, not a feature flag.

## Drafts

Current review set:

- `drafts/2026-08-v1/api-terms.md`
- `drafts/2026-08-v1/acceptable-use.md`
- `drafts/2026-08-v1/privacy.md`
- `drafts/2026-08-v1/dpa.md` (optional unless counsel/commercial policy makes it required)

Counsel should confirm governing law/venue, liability cap, indemnities, privacy disclosures, state/international privacy applicability, retention, subprocessors, cross-border transfers, DPA mechanics, and reacceptance policy before approval.
