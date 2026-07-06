# Global UI Language Contract

AGRO-AI exposes one shared global language registry across backend and portal.

## Contract

- `shared/supported-locales.json` is the source of truth for visible UI locales.
- Every language family declared in `shared/chatgpt-language-targets.json` must be represented by a visible UI locale.
- English and French remain bundled static catalogs.
- Other enabled locales hydrate an authenticated translated UI catalog through `POST /v1/i18n/catalog`.
- Generated catalogs must preserve exact source keys and placeholders.
- Browser clients cache validated catalogs locally and fail back to the English source catalog if generation is unavailable.
- RTL direction is applied from shared locale metadata.
- `GET /v1/i18n/languages` exposes the backend-visible language contract.
- Persisted preferences reject locales outside the shared enabled registry and canonicalize supported regional aliases to a visible locale.

This contract deliberately avoids pretending that a language is globally available merely because the chat model can answer in it: the language must also be present in the UI registry and selectable in the portal.
