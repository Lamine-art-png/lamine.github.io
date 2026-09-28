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
4. Validation enforces key parity, placeholder parity, valid Unicode, non-empty values, and meaningful translation progress.
5. Only after the entire locale matrix validates may the release promote those locales into the production manifest.
6. Vite bundles the complete validated catalogs with the authenticated and pre-auth application.
7. Selecting a language switches from one complete catalog to another complete catalog atomically.

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

## Release proof

Mocked translation-provider tests are useful unit coverage but are not production proof.

Release gates must include:
- static full-matrix catalog validation;
- fresh-browser pre-auth switching with no localization API mock;
- representative `pt-BR`, Japanese, Arabic/RTL, German, Burmese, and French checks;
- exact locale persistence across reload;
- post-deploy production browser smoke against `app.agroai-pilot.com`.

A production locale fallback, source-fingerprint mismatch, raw translation key, serialization artifact, or mixed English shell outside an explicit proper-noun allowlist is a release failure.
