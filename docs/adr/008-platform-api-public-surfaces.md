# ADR 008: curated public routes and server-gated static pages

Accepted.

The public OpenAPI derives from an explicit route manifest. Developer Portal,
platform-admin, queue, internal, and generic Portal routes are excluded. The
marketing and documentation pages are Cloudflare Pages assets behind
server-side Functions flags and remain absent from navigation and sitemap while
disabled.
