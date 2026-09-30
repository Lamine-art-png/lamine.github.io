# Global UI Language Contract

AGRO-AI exposes one shared locale registry across the pre-auth experience, Enterprise Portal, Platform API surfaces, backend-generated communications, and billing.

## Production invariant

A language is not supported merely because it appears in a selector or a model can translate it.

A customer-visible production locale MUST have a complete, source-fingerprinted, release-versioned catalog before it appears in `enabledUiLocales`.

The release invariant is:

`enabledUiLocales - {"auto"} == catalogCompleteLocales`

and production releases MUST keep `dynamicCatalogLocales` empty.

## Catalog lifecycle

1. English remains the canonical product-copy source.
2. `scripts/i18n-build-source.mjs` produces the canonical source envelope and fingerprint.
3. Build-time authoring generates one exact-key catalog per production locale.
4. Validation enforces key parity, placeholder parity, valid Unicode, non-empty values, and the shared release-quality gate in `scripts/i18n_quality.py` (English leakage, native-script share, cross-script contamination, authoring-marker residue, byte-identical code samples).
5. `scripts/i18n-reconcile-production-locales.py` is the single readiness definition: a locale is advertised only when its UI catalog, transactional catalog and legal snapshots all pass. It rewrites `enabledUiLocales` and emits `shared/localization/release-matrix.json` (per-locale UI/transactional/legal status, direction, UI quality, Stripe locale, voice and intelligence language context).
6. Vite ships every validated catalog as its own lazily loaded, content-hashed chunk of the same deployment. `main.tsx` installs the persisted locale's chunk before first render.
7. Selecting a language loads that static chunk and then switches from one complete catalog to another atomically. `runtime-source-parity-contract.mjs` fails CI if the English source the running portal requires diverges from `source.json`.

### Release artifact identity

`sourceFingerprint` identifies the English source a catalog translates and does not change when only translated values change. Each catalog therefore also carries `catalogSha256` — the SHA-256 of its canonical content (locale, source fingerprint, every translated value) — stamped by `scripts/i18n_catalog_identity.py` and recorded in the release matrix. The release gate requires the stamp to be current, and `scripts/i18n-verify-production-catalogs.mjs` recomputes it from the checked-in catalog and requires that exact identity in the deployed chunk, so an older translation can never pass production verification.

### Authoring

`.github/workflows/i18n-global-authoring.yml` runs on `i18n-authoring/*` branches and never pushes. For every target locale that is not release-ready it authors the UI catalog (reusing previously validated entries whose English is unchanged), the transactional catalog and the legal snapshots, and uploads them. `scripts/i18n-install-authoring-artifacts.py <download-dir>` installs a run and re-runs the release gate. Customer-facing API messages are inventoried by `scripts/i18n-extract-api-messages.py` so server errors are translated like any other UI copy.

### Legal presentation

Localized Terms of Service and Privacy Policy are translations of one pinned canonical English DOM (`shared/localization/legal-canonical/`). Each snapshot records the clickwrap version (`SELF_SERVICE_*_VERSION`) it presents; readiness requires that version to equal the version customers accept, so acceptance evidence always refers to one canonical legal version regardless of display language.

Runtime AI translation is not the critical path for an advertised locale. The legacy `POST /v1/i18n/catalog` path may remain for recovery, authoring, diagnostics, or non-production experimentation, but a production user must not depend on it in order to see the language shown in the selector.

## Locale state

`shared/supported-locales.json` is the source of truth for:
- visible UI locales;
- BCP-47 locale identity;
- language family;
- directionality;
- fallback metadata;
- release completeness.

Brazilian Portuguese is represented as `pt-BR` in production. Regional identity must not be discarded when it affects customer-facing language, email, billing, formatting, or legal presentation.

Locale precedence: explicit current choice (stored selection) > account preference (adopted after sign-in only when no explicit choice exists) > locale carried by a signed verification/recovery link (applied at boot on those routes, so another device opens in the email's language) > browser language > English.

The browser keeps the explicit selected locale separately from automatic browser resolution. Explicit customer choice takes precedence over account preference for the current session; authenticated preference synchronization must not silently revert a deliberate selection.

## Customer-path requirements

The selected/effective locale must propagate through:
- anonymous login and signup;
- validation and error copy;
- legal acceptance and legal-document links;
- email verification and verification-link restoration;
- onboarding;
- authenticated navigation and workspaces;
- Ask AGRO-AI and voice language context;
- notifications and transactional email;
- checkout and billing;
- account recovery;
- locale-aware dates, times, numbers, and directionality.

RTL locales must set the document direction and remain usable at component/layout level.

## Failure behavior

A requested language may become active only when its complete validated catalog is available.

If a requested complete asset cannot be loaded, the UI must keep the previous complete locale and expose a recoverable error. It must never display a requested language in the selector while silently rendering English fallback copy.

## Billing, intelligence and voice

Stripe Checkout receives the mapped locale from `stripe_checkout_locale()` (e.g. `tl`→`fil`, `no`→`nb`, `fr-FR`→`fr`); locales Stripe does not offer use `auto`. AGRO-AI's own billing UI and emails always keep the customer's AGRO-AI locale.

Ask AGRO-AI receives the effective locale as `preferred_language`: the answer defaults to it, and an explicit request or a clearly different message language overrides it. Voice sends the effective locale as the recognition hint and response language; browser fallback speech is device-dependent.

## Observability

The portal reports `locale_switch_requested|completed|failed`, `locale_catalog_missing` and `locale_fallback_triggered` (an English fallback inside an advertised locale) to `POST /v1/i18n/events` with locale codes, catalog fingerprint, release SHA, surface and latency only — no identity or copy. Failure events are logged at ERROR.

## QA metadata

`shared/supported-locales.json` → `qa` records exactly what has been executed:

- `releaseGateValidatedLocales` — every advertised locale passed the full static release gate.
- `browserSwitchContractLocales` — every advertised locale is switched in real Chromium against the built portal with zero runtime catalog requests (`global-language-switching.spec.mjs`).
- `productionBrowserProofLocales` + `productionBrowserProofScope: "representative"` — the sample exercised end to end against production (`production-global-localization.spec.mjs`); not one production journey per locale.
- `humanLinguisticReviewLocales` — locales whose machine-authored catalogs have had native-speaker review (none yet).

`static-locale-catalog-contract.mjs` fails if these fields overclaim.

## Release proof

Mocked translation-provider tests are useful unit coverage but are not production proof.

Release gates must include:
- static full-matrix catalog validation;
- fresh-browser pre-auth switching with no localization API mock;
- representative `pt-BR`, Japanese, Arabic/RTL, German, Burmese, and French checks;
- exact locale persistence across reload;
- post-deploy production browser smoke against `app.agroai-pilot.com`.

A production locale fallback, source-fingerprint mismatch, raw translation key, serialization artifact, or mixed English shell outside an explicit proper-noun allowlist is a release failure.
