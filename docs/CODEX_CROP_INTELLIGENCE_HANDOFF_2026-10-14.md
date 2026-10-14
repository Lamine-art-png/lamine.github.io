# Codex handoff — Finish AGRO-AI Crop Intelligence in isolated staging
Date: 2026-10-14 (America/Los_Angeles)

## Why this branch exists
The owner asked Codex to continue Claude Code's Field & Crop Intelligence work while Claude's usage is unavailable until approximately 5:40 p.m. Pacific, then return the work for review. This is a **separate working branch** to avoid parallel writes to Claude's original branch. Do not write directly to the Claude source branch or merge into `main`.

Source: PR #562, `claude/wizardly-hypatia-gxpxvj` at `3ca4e38f00bd504b64882611439dbc2bc67f106d`.
Original: https://github.com/Lamine-art-png/lamine.github.io/pull/562
This branch was forked directly from that SHA, and its draft PR targets `main` so the repository's fail-closed staging workflow can recognize a normal draft PR. **Do not merge this temporary draft PR to main.** At handback, coordinate changes with #562 by review/cherry-pick/fast-forward as appropriate.

## Fact-checked status when handed off
- Claude's branch has extensive Field & Crop Intelligence backend engineering and audit corrections. Its latest SHA `3ca4e38` had 22 PR-triggered workflows reported completed/successful in a first-page lookup; previous PR narrative mentions 59 checks at an earlier head. Do not infer today's full release green status without rechecking all required checks on your own new head.
- A separate customer-facing `/crop-intelligence` route **does not exist** in `figma-enterprise-v4/src/app/routes.tsx`. `MainLayout.tsx` lists Market Intelligence and Field Intelligence, but no Crop Intelligence entry.
- Existing client API methods in `figma-enterprise-v4/src/app/api/client.ts`: `fieldIntelligence.cropProfiles`, `observationDetections`, `fieldCropCondition`, `harvestWindow`, `productionEstimate`, `maturityStages`. Reuse them and improve types/validation as needed.
- Backend work in `agroai_api/app/api/v1/field_intelligence.py`, `app/services/crop_intelligence.py`, `crop_estimation.py`, `crop_profiles.py`, `crop_scientific_tools.py`, Field Intelligence vision/detection modules and tests.
- Three crop calculators require the existing `intelligence.deep_analysis` Professional-or-higher entitlement. Preserve contract overrides, organization scoping and paid/free behavior.
- Specialized crop detection remains DISABLED, with an empty server model registry and empty allowlist. Validation on real crop observations is 0/50. No verified live detector or defensible harvest accuracy claim exists. Do not enable it.
- Existing Render staging API service: `agroai-field-intelligence-staging-api-6l9x`, id `srv-d9fed0jh523c73f2b4k0`, July branch `feature/field-intelligence-launch`, autoDeploy off. Its latest real application build and qualified staging configuration must be rechecked. There is also a suspended second staging API; avoid duplicates.
- Existing workflow `.github/workflows/field-intelligence-staging.yml` requires an exact PR head/merge SHA, base `main`, mandatory green checks, fail-closed isolation/identity checks, `qualify` then `deploy`. It has not been proven qualified or deployed for this new PR.
- As of handoff `main` was `ea7e2a86bf1c9fc0ac96194686c1e59f3241e0ad` (AWS Marketplace fixes, Oct 14). This branch may be behind `main`. Reconcile carefully and preserve AWS lifecycle, billing, paid Field Intelligence and localization code.

## Execution request — do the engineering, not just plan
1. Inspect the newest `main`, this branch, original #562 diff/reviews, and relevant frontend/router/navigation/auth/localization contracts. Merge/reconcile main safely without overwriting #562's changes or modifying production; run full CI after reconciliation.
2. Build a real `/crop-intelligence` customer-facing page in `figma-enterprise-v4` and add it to Intelligence navigation. Use the existing AGRO-AI design and shared components, including appropriate responsive/mobile behavior, translated messages, keyboard/accessibility basics, good loading/error/empty states. Do not create a parallel frontend or shadow API.
3. Connect **live authenticated data** scoped to the selected organization/workspace/field: crop-condition summary, freshness and evidence; links into Field Intelligence observations; production estimation (design/sample parameters and confidence intervals); sourced weather/harvest-window inputs; maturity-stage samples and uncertainty; reviewed, nonautomatic proposal to Market Intelligence. Distinguish observed vs calculated vs hypothetical vs unverified. If sample data is needed for tests, label it clearly as synthetic and keep it out of customer live panels.
4. Respect both existing scientific and commercial fail-closed gates: do not infer precision from unsupported inputs, elevate one unverified frame to a severe diagnosis, call unvalidated thresholds validated, overwrite manual commercial yields, or bypass paid entitlements. Do not turn on detector; preserve empty registry, review-only outputs, license and model attestations.
5. Add targeted frontend unit/browser and backend route tests. Required user journey: login, select authorized organization/workspace/field, open Crop Intelligence via sidebar/deeplink, examine real scoped condition/evidence, run valid estimator flows, see appropriate missing-evidence/error/paywall behavior, review Market proposal without persisting it automatically, navigate Field/Market Intelligences. Assert restricted accounts cannot see others' data. Test mobile and locales. Preserve existing onboarding, billing, Platform API, AWS, Field Intelligence behavior.
6. Use current repository CI and release/staging contracts. **Stage only if safe:** verify ALL staging identities distinct from production (hostnames, services, DB fingerprint, credentials, R2/buckets, provider endpoints, Cloudflare project), and run `qualify` read-only first. Do not invent secrets; if mandatory credentials or environment approvals unavailable, stop only that step and report exact blockage. After actual passed qualify and owner-authorized staging safeguards, deploy to preexisting isolated Render/Cloudflare staging resources, with no paid resource creation, no production deploy, no production schema changes.
7. Test the **deployed** portal against the staged API with an authenticated staging account on desktop and mobile; report exact URL, commit, version, and observed test results. If you cannot execute the deployed end-to-end test, do not claim success. Code-level passing tests alone are not deployment.
8. Keep this Codex branch/PR draft and distinct. Update PR with concise progress and objective evidence; leave a handback that Claude can integrate at/after 5:40 p.m. PT: changed files, tests, deploy URLs/results, missing inputs, next safe action. If a platform-triggered task cannot do writes, report that instead of pretending.

## Operating constraints
- No `main` merge, production deploy, live customer settings change, public release/marketing, detector activation, pricing or subscription change, purchases, new paid infrastructure, or secret exposure.
- Don't alter production AWS Marketplace, Stripe, Cloudflare routing or Render resources.
- Don't perform live customer field evaluation without consent.
- Avoid redundant audits. Fix genuine defects and prove fixes with tests.
- Changes should be minimal, reviewable and maintainable.
- The objective is **a usable staged Crop Intelligence page**, not another architecture document.

## Handback checklist
- [ ] Dedicated Crop Intelligence nav + routed portal UI, field/workspace scoping
- [ ] Existing backend API connected, permission and failure states verified
- [ ] Supported crop estimators surfaced without scientific overclaims
- [ ] Localization and desktop/mobile smoke
- [ ] Regression CI green against current main
- [ ] Staging isolation/read-only qualify passed, or exact blocker
- [ ] Isolated staging deploy and authenticated E2E passed, or exact blocker
- [ ] No production/customer/billing changes
- [ ] All changes and results documented for Claude's review
