# AGRO-AI Platform API — developer experience

The unified, standalone developer platform for the AGRO-AI Platform API:
a marketing landing page, documentation, a spec-driven API reference, and an
interactive API Explorer. It is a **static** surface served by Cloudflare Pages
from this repository — there is no build step and no framework.

> This is the developer-facing **frontend**. It does not implement or duplicate
> the Platform API backend, authentication, billing, or the Enterprise Portal.
> It links out to them.

## Surfaces & intended hosts

| URL | Serves | Notes |
| --- | --- | --- |
| `agroai-pilot.com/platform-api` | `platform-api/index.html` | Canonical path for the landing page. |
| `platform.agroai-pilot.com` | this tree | Optional custom domain mapped to the same Pages project. |
| `docs.agroai-pilot.com` | `platform-api/docs/` + `reference.html` | Optional custom domain for documentation. |
| `app.agroai-pilot.com` | Enterprise Portal (separate) | Linked as "Get API keys" / "Developer portal". |
| `api.agroai-pilot.com` | Machine API (separate) | The REST API these docs describe. |

Host → content mapping is a **Cloudflare Pages / DNS concern and is not
configured here.** Because Pages serves physical files before applying the
`/* /index.html` catch-all in `_redirects`, every page in this tree resolves at
its real path without any routing change. Links are root-relative
(`/platform-api/...`) so they work under the same Pages project regardless of
which custom domain fronts it.

## Structure

```
platform-api/
├── index.html              Landing page
├── reference.html          API reference (rendered from assets/openapi.json)
├── explorer.html           Interactive API Explorer
├── changelog.html          Changelog
├── docs/                   Narrative documentation
│   ├── index.html          Overview
│   ├── quickstart.html
│   ├── authentication.html
│   ├── pagination.html
│   ├── errors.html
│   ├── rate-limits.html
│   ├── webhooks.html
│   └── support.html
├── assets/
│   ├── platform.css        Design system (brand tokens, light/dark, responsive)
│   ├── platform.js         Shared UI (theme, nav, copy, highlight, tabs, TOC)
│   ├── reference.js         Renders the reference from the spec
│   ├── explorer.js          The API Explorer
│   ├── openapi.json         Public API surface (drives reference + explorer)
│   └── logo.svg             AGRO-AI mark
└── tests/
    └── validate_platform.py  Static quality gate (see below)
```

`openapi.json` is the **single source of truth** for the reference and the
Explorer — add an endpoint there and both surfaces update.

## Security posture

- **No secrets in the browser.** The Explorer's API key is supplied by the user,
  held in memory (optionally `sessionStorage`, cleared when the tab closes),
  never in `localStorage`, and never sent to AGRO-AI web servers. In Live mode
  it is sent only to the API host the user selects, as a bearer token.
- The default Explorer mode is **Sample response** — a documented example with
  no network request and no key required.
- Generated cURL uses the `$AGROAI_API_KEY` placeholder, never the raw key.
- `_headers` applies a tight Content-Security-Policy and hardening headers
  scoped to `/platform-api/*` only.
- `tests/validate_platform.py` scans committed assets for leaked key material.

## Local development

Serve the repo root (so `/platform-api/...` paths resolve) and open the site:

```bash
python3 -m http.server 8000     # run from the repository root
# then visit http://127.0.0.1:8000/platform-api/
```

## Validation

The quality gate runs with the Python standard library only:

```bash
python3 platform-api/tests/validate_platform.py
```

It checks HTML structure, accessibility basics (lang, single `h1`, skip link,
image alt text, labelled controls), internal-link and anchor integrity,
committed-secret scanning, and `openapi.json` consistency. JavaScript is
syntax-checked with `node --check`. Both run in CI via
`.github/workflows/platform-api-experience-ci.yml`.
