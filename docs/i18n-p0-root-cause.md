# Production localization incident: verified findings

Audited main: 6157038c0b1a08a3fee9cdf918434aa11f392aee.

On the actual unauthenticated production signup, selecting Japanese changes the
selector while the headings, labels, organization options, and marketing copy
remain English. The selector reports 33 missing critical keys and no translation
progress. This is a reproduced failure, not a passing production smoke.

The shared registry exposes 59 actual locales plus Auto, but declares only en and
fr-FR complete. That declaration is itself insufficient: French core-key parity
does not establish completeness of portal literals or route copy. Activation
commits a requested language on provider failure, then t() falls back per key.
The resulting selected locale, document language, and visible language disagree.

The runtime's full source excludes dynamic route catalogs. Its explicit imports
stop at ui-literals.en.14.json although parts 15–19 exist. The regex inventory
also misses string expressions, conditional branches, and option arrays used by
signup. These defects persist independently of provider availability.

Verification emails outside Portuguese/English invoke a live model and return
English when generation fails or runs in an async context. Regional pt-BR is
collapsed to pt. Legal links do not carry language. Existing Playwright tests
mock catalogs with synthetic language prefixes; production release checks grep
bundle contents, which cannot prove a customer's language switch works.

Required release boundary: versioned artifacts with exact source fingerprints,
complete source coverage, structural validation, and real customer-path tests.
Offline generation produces candidates only; an unreviewed or incomplete
candidate must never enable a language. Production completion is unproven until
post-deployment black-box checks pass on both customer hostnames.
