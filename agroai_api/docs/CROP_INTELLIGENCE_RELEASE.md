# Crop Intelligence: portal workspace and release status

Status: **staging candidate, not released.** Production is unchanged until
PR #562 is approved and merged. Specialized detection stays **disabled**
(see `FIELD_DETECTION_RELEASE.md`).

## What a customer gets (`/crop-intelligence` in the Enterprise Portal)

| Tab | Backed by | What it does | What it never does |
|---|---|---|---|
| Overview | `GET /v1/field-intelligence/crop-intelligence/overview` | Fields with crop records in the workspace, the newest finished crop assessment per field, evidence freshness, and why a field needs attention (high severity, open review, failed processing, stale or missing assessment, future-dated records, unsupported or unrecorded crop) | Compare fields with each other or call a trend |
| Crop health | `GET /v1/field-intelligence/fields/{id}/crop-condition` | Latest assessment, visual analysis (confidence labelled uncalibrated), changes only against a comparable prior (same block, same method), block snapshot, recent records, links to the record in Field Intelligence | Present a difference between non-comparable records as a trend |
| Production | `POST …/crop-intelligence/production-estimate` | Probability-sample estimate with a 95% interval from counts the customer made by hand, plus optional calibration (visible share, unit weight, marketable share, area) | Estimate from a convenience sample, accept automated counts without a registry-verified detector, or hide missing calibration |
| Harvest window | `POST …/crop-intelligence/harvest-window` | Degree-day window from a sourced maturity target, this season's daily weather and at least 5 earlier seasons (CSV paste or upload); limitations and approval-only preparation suggestions | Give a single harvest date or create tasks |
| Maturity | `POST …/crop-intelligence/maturity-stages` | Stage shares with Wilson intervals and a readiness call only from a random sample against a sourced threshold | Make a readiness call from a non-random or stratified sample |

Every calculator shows which values are the customer's inputs (unverified),
which are calculated, and which capabilities are not available yet.

## Market Intelligence hand-off

A production estimate with area, weight and a reliable interval yields a
*proposal*. "Review in Market Intelligence" carries it (session storage only)
to the Market Intelligence workspace, where a member with write access can
record it through the existing yield-estimate intake
(`POST /v1/market-intelligence/positions/{id}/yield-estimates`,
`source: crop_intelligence`). Recording is a deliberate action. Updating the
position's expected production is a separate, unchecked-by-default choice,
and the server keeps the replaced value. Read-only members can review but not
record. The proposal is labelled an agricultural estimate, not commercially
verified volume.

## Access and isolation

- All routes require authentication and are tenant-scoped through the existing
  Field Intelligence observation query and release gate.
- The three calculators keep the existing Professional-or-higher
  `intelligence.deep_analysis` entitlement (402 `upgrade_required` otherwise);
  the portal shows the plan boundary and the server stays authoritative.
- The overview and crop health are reads of the customer's own records.

## Localization

237 new English strings live in one copy table
(`src/app/cropIntelligence/cropIntelligenceCopy.ts`) and are in
`shared/localization/source.json`. Translations for all 59 bundled locales were
authored for this change by AI translation (as with the existing
build-time-generated catalogs, no locale has had human linguistic review) and
pass the repository's own release gate (`scripts/i18n_quality.py`: placeholder
parity, script, English-leak, degenerate and collapsed-output checks). Terms a
native agronomist should confirm include almond hull and grape veraison names
in some locales.

## Scientific status (unchanged by the portal)

Automated tests prove the arithmetic and the refusal paths on constructed
inputs. They do not prove agricultural accuracy. Not yet validated:
crop-profile degree-day conventions for any variety, harvest windows against
actual harvest dates, production estimates against harvested yield,
hull-split readiness thresholds, vision accuracy (#352 gate: 0 of 50), and any
detector (none is registered).

## Tests

- Backend: `test_crop_intelligence_summary.py` (overview roll-up),
  `test_crop_intelligence_api.py` (overview route: authentication, tenant
  isolation, foreign workspace 404), plus the existing estimator suites.
- Portal: `tests/browser/crop-intelligence.spec.mjs` (Field Intelligence CI) on
  the production bundle with synthetic data: navigation, overview, crop health
  and the Field Intelligence deep link, exact calculator request contracts,
  the market hand-off recording with `apply_to_production: false` and no other
  commercial write, read-only review, plan lock and server 402, empty state,
  client-side validation, mobile width on every tab, and a translated locale.
- Staging: `tests/browser/crop-intelligence-staging.spec.mjs` runs from
  `field-intelligence-staging.yml` in deploy mode against the deployed staging
  portal and API with the canary token, using synthetic records it deletes.
