# AGRO-AI portal loader branding

`officialAgroAiLoaderLogo.ts` contains the optimized official AGRO-AI logo supplied for the portal loading experience. It is embedded as a small WebP data URI so the loading screen does not introduce an additional network dependency during application bootstrap.

The loader is intentionally presentation-only: auth, routing, locale fail-open behavior, and the 12-second locale cover bound remain unchanged.
