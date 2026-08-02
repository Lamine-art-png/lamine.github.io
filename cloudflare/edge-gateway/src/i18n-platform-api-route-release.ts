// Deployment marker for the Platform API custom-domain route release.
//
// The production Worker is configured by ../../wrangler.toml. Keeping this
// marker under the i18n-* deployment path forces Wrangler to reconcile the
// app, platform, and api custom-domain routes whenever the Platform API public
// edge needs to be reasserted.
export const PLATFORM_API_ROUTE_RELEASE = "api-host-route-2026-08-02";
