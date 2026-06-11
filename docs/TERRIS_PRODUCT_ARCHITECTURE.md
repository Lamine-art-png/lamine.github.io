# Terris Product Architecture

Terris is AGRO-AI's operating intelligence and evidence layer for agriculture. It converts fragmented farm data into prioritized decisions, field execution, verification, and trusted proof.

The operating loop is: Observe -> Recommend -> Approve -> Execute -> Verify -> Prove -> Improve.

## Scope

Implemented now:
- Terris branding across active mobile and backend UI/service surfaces.
- Terris Water remains the active wedge and uses the existing recommendation, offline, voice, multilingual, guardrail, and evaluation foundation.
- A canonical field-ledger event envelope for water, nutrients, energy, ops, and proof events.
- A typed module registry with active, beta, preview, and reserved module boundaries.
- Beta helper services and mobile surfaces for Nutrients, Energy, Ops, and Proof.

Staged only:
- Terris Protect is a preview boundary, not a crop-protection workflow.
- Terris Risk API is a reserved contract boundary, not a public endpoint.
- California Compliance remains a separate kernel and is not merged into Terris Proof.

Out of scope:
- Accounting, payroll, CRM, inventory, commodity trading, broad crop planning, input marketplace, novelty chatbot behavior, official regulatory filing, chemical prescription, pesticide recommendation.

## Local Run

Backend:

```bash
cd apps/velia-ai-api
npm test
npm run dev
```

Mobile:

```bash
cd apps/velia-mobile
npm test
python3 -m http.server 4174
```

The app paths retain their historical names for local tooling compatibility; the active product name is Terris.
