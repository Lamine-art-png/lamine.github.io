# AGRO-AI Platform API distribution kit

This directory is the source-of-truth package for distributing the AGRO-AI Platform API outside the AGRO-AI website.

## Ready artifacts
- `AGRO-AI-Platform-API.postman_collection.json` — generated from the curated Platform API contract.
- `marketplace_openapi.json` — the same curated contract with an absolute production server URL for modern marketplace imports.\n- `rapidapi_openapi_3_0_2.json` — generated OpenAPI 3.0.2 compatibility artifact for RapidAPI import.
- `marketplace-listing.md` — canonical copy, positioning, pricing, URLs, keywords, and channel rules.

## Channel state

| Channel | Technical package | External publisher action still required |
| --- | --- | --- |
| AGRO-AI direct | Ready; production billing has a verified evidence trail | Public acquisition/indexing remains governed by the protected launch state |
| Postman | Import-ready collection | Publish from AGRO-AI's Postman workspace/account |
| RapidAPI | Import-ready OpenAPI 3.0.2 + listing copy | Create/authorize the provider listing, configure proxy/auth/plan mapping, publish |
| AWS Marketplace | Listing copy + API contract ready | Seller registration, banking/tax/legal acceptance, SaaS entitlement/metering adapter, AWS review |
| Microsoft Marketplace | Listing copy + API contract ready | Partner Center Marketplace enrollment, payout/tax profile, SaaS fulfillment/SSO/webhook integration, Microsoft review |

## Non-negotiable billing rule
A customer acquired and billed through an external marketplace must follow that marketplace's required transaction and entitlement path. Do not create a second direct Stripe charge for the same marketplace subscription.

## Product truth
AGRO-AI direct Developer and Scale billing is production verified. Marketplace availability is a separate fact and must only be claimed after each channel is actually approved and published.
