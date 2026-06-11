# Water Command Center V2 Preview Deploy

This document describes a manual Cloudflare Pages preview deployment for the
Water Command Center V2 app only. Do not modify the live portal, DNS, custom
domains, provider settings, secrets, or existing Pages projects.

## Cloudflare Pages Project

Create a separate Pages project in the Cloudflare dashboard.

- Project name: `agroai-command-center-v2-preview`
- Root directory: `apps/agroai-command-center-v2`
- Build command: `npm ci && npm run build`
- Output directory: `dist`
- Environment variable:
  - `VITE_API_BASE_URL=https://api-preview.agroai-pilot.com`

Use the generated `pages.dev` URL only.

## Manual Dashboard Steps

1. Open Cloudflare Dashboard.
2. Go to Workers & Pages.
3. Create a new Pages project.
4. Connect the repository and select the branch for this PR.
5. Set the project name to `agroai-command-center-v2-preview`.
6. Set root directory to `apps/agroai-command-center-v2`.
7. Set build command to `npm ci && npm run build`.
8. Set output directory to `dist`.
9. Add environment variable `VITE_API_BASE_URL` with value
   `https://api-preview.agroai-pilot.com`.
10. Deploy and use only the generated `pages.dev` preview URL.

## Safety Rules

- Do not modify `app.agroai-pilot.com`.
- Do not add a custom domain.
- Do not modify Cloudflare DNS.
- Do not modify production routing.
- Do not touch the existing `agroai-portal` Pages project.
- Do not touch Velia hosting.
- Do not modify provider secrets.
- Keep `api-preview.agroai-pilot.com` separate from the stable
  `api.agroai-pilot.com` API fallback.

The Vite config uses `base: "./"` and emits a static `dist/` bundle, preserving
relative asset paths for preview deployment.

## Required Post-Deployment CORS Step

After Cloudflare assigns the exact preview `pages.dev` URL, open a **separate
controlled backend PR** that adds that exact origin to the API CORS allowlist.
Use the full URL (e.g. `https://agroai-command-center-v2-preview.pages.dev`).

Do **not** allow wildcard `*.pages.dev` origins — wildcard coverage would allow
any Cloudflare Pages deployment to call the production API without authorisation.

## Local API Browser Testing

Browser requests from localhost to a deployed API will be blocked by CORS unless
the allowlist explicitly includes the local preview origins:

- `http://localhost:4180`
- `http://127.0.0.1:4180`

Add these to the backend CORS allowlist only in a development/staging configuration,
never in the production allowlist.

## Current Routing Map

- V2 preview portal: `app-v2.agroai-pilot.com` -> `agroai-command-center-v2-preview.pages.dev`.
- Generated preview URL: `https://agroai-command-center-v2-preview.pages.dev/`.
- V2 preview API: `api-preview.agroai-pilot.com` -> Render service `agroai-api-preview`.
- Stable portal: `app.agroai-pilot.com` -> `agroai-portal.pages.dev`.
- Stable API: `api.agroai-pilot.com` -> temporary stable Railway-backed fallback.

Do not cut over `api.agroai-pilot.com` to Render until the production cutover is
approved and stable portal compatibility is proven.

## Current Known Limitations

- Calibration packs are default farm-type baselines, not farm-specific calibrations.
- Evaluation sessions are in-memory only; durable tenant persistence is future work.
- Production identity provisioning is not active in the preview environment.
- Exact preview CORS allowlisting requires a separate controlled backend PR after
  the `pages.dev` URL is known.
