# AGRO-AI Deployment Truth Map

This document records the dashboard-confirmed routing state after PR #60. It is
an infrastructure map only; it does not authorize DNS changes, provider changes,
feature activation, data seeding, or production migrations.

## A. Marketing Website

`agroai-pilot.com`

Routes to:

`agroai-343.pages.dev`

Classification: current Cloudflare Pages marketing site.

## B. Existing Stable Portal

`app.agroai-pilot.com`

Routes to:

`agroai-portal.pages.dev`

The stable portal calls:

`api.agroai-pilot.com`

which currently routes to:

`ayheamed.up.railway.app`

Classification: temporary stable Railway-backed fallback retained until a
controlled Render production cutover is completed.

## C. V2 Preview Portal

`app-v2.agroai-pilot.com`

Routes to:

`agroai-command-center-v2-preview.pages.dev`

Generated preview URL:

`https://agroai-command-center-v2-preview.pages.dev/`

Preview API:

`api-preview.agroai-pilot.com`

Routes to:

`agroai-api-preview.onrender.com`

Classification: Render-backed V2 evaluation preview. This is not yet the stable
production API.

## D. Legacy Cloudflare Containers Path

The root `wrangler.toml` still exists, and `.github/workflows/deploy.yml` still
exists. The Cloudflare Containers custom route for `api.agroai-pilot.com/*` is
commented out in `wrangler.toml`.

Cloudflare DNS does not currently route the active API domains to this
Cloudflare Containers path. It is retained temporarily for manual historical
inspection only.

## E. Safety Rules

- Do not change `api.agroai-pilot.com` DNS until Render production cutover is
  explicitly approved.
- Do not remove Railway until stable portal compatibility is proven.
- Do not expose backend provider URLs in browser code when a controlled custom
  API domain exists.
- Keep preview and production routes separate.
- Compliance activation is a separate release phase.
