# Academy UI localization catalogs

This directory contains the Academy interface catalogs for the 60 enabled UI locales in `shared/supported-locales.json`. The English catalog is the source of truth for keys, interpolation placeholders, and markup. The other 59 catalogs are machine-prepared drafts, **not human-reviewed translations**.

`_meta.json` records provenance and review status for each locale. Its `source_language_fallback_keys` list identifies interface strings deliberately left in source English when machine output could not safely preserve meaning, placeholders, or markup. Do not remove these disclosures or mark a locale reviewed without a real linguistic review.

These files cover interface text only. They do not constitute reviewed A1 lesson content, translated assessments, video captions, or authorization to issue certificates in another language. The Academy must continue to label machine-prepared content accurately and use reviewed-only assessment/caption gates.

Before changing a catalog, preserve exact key parity with `en.json`, placeholders, markup, RTL behavior, and the regression tests. Do not put proprietary video transcripts, captions, exam questions, or answer keys in this directory.
