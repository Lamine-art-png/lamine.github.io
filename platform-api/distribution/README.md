# AGRO-AI Platform API distribution kit

This directory contains the technical package for distributing the AGRO-AI Platform API outside the AGRO-AI website. Technical readiness, publication, seller verification, billing, and public TEST enrollment are **separate** states.

## Ready artifacts

- `AGRO-AI-Platform-API.postman_collection.json` — official import-ready collection generated from the curated contract.
- `marketplace_openapi.json` — curated contract with an absolute production server URL for marketplace imports.
- `rapidapi_openapi_3_0_2.json` — RapidAPI-compatible OpenAPI 3.0.2 import artifact.
- `marketplace-listing.md` — canonical copy, positioning, pricing references, URLs, keywords, and channel rules.
- `../../docs/platform-api-pricing-catalog.md` — direct pricing and billing evidence; active Stripe prices do not prove marketplace availability.

## Verified channel state — 2026-10-09

| Channel | Verified state | Outstanding external gate |
| --- | --- | --- |
| AGRO-AI direct | Developer and Scale products and prices are active in production Stripe; direct billing integration is production-verified. Public site/docs correctly say **Private preview**. | Counsel-approved legal catalog and protected activation before public automatic TEST enrollment or indexing. |
| Postman | Official workspace and collection were reported published and publicly visible from the authorized account on 2026-10-04. | Maintain existing assets and reverify public visibility when needed. **Do not create duplicates.** |
| AWS Marketplace | Seller-account OIDC, runtime identity, event/reconciliation integration, Developer/Scale entitlement mapping, and diagnostics are implemented. Product reached **Limited** visibility. Production startup verified seller identity and a successful GetEntitlements probe on 2026-10-09. | **Public** visibility, approved seller financial/KYC state, public offer/purchase URL, and controlled paid buyer registration, entitlement, and cancellation are **not independently verified**. |
| RapidAPI | Import-ready OpenAPI 3.0.2 and listing copy exist. | Provider identity/approval, proxy/auth/plan mapping, single billing owner, and publication unverified. |
| Microsoft Marketplace | Listing copy and API contract prepared. | Publisher identity, tax/payout approval, SaaS fulfillment/SSO/webhook integration, entitlement lifecycle, and publication unverified. |

## Legal and release boundary

Public TEST self-service must remain fail-closed until counsel approves the exact API Terms, Acceptable Use Policy, Privacy Notice, and DPA treatment. Approved versioned HTML assets and a matching `platform-api/legal/approved-catalog.json` with genuine reviewer/approval evidence are required. Only then run the protected activation workflow against current `main`. See [legal gate #530](https://github.com/Lamine-art-png/lamine.github.io/issues/530) and [activation gate #417](https://github.com/Lamine-art-png/lamine.github.io/issues/417).

Registration improvements do not relax identity, LIVE provider, physical-execution, or legal gates.

## Non-negotiable billing and publication rules

- An external marketplace subscription must use that marketplace's required transaction and entitlement path. Never also charge the customer directly through Stripe for the same subscription.
- Active Stripe prices, successful OIDC, or a successful GetEntitlements probe **do not** establish a completed sale or publicly purchasable listing.
- Do not duplicate published marketplace products or Postman collections, fabricate seller/counsel approval, commit sensitive financial/KYC records, or enable physical commands as part of TEST distribution.
- Record verified external evidence and pending owner actions in [marketplace issue #531](https://github.com/Lamine-art-png/lamine.github.io/issues/531).
