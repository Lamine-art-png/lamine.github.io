# AGRO-AI Academy — execution status

Durable checklist so work can resume across sessions. Updated 2026-10-17.
Branch: `claude/inspiring-hypatia-gq0x5p`.

## Audit findings (Phase 1)

* Repository `Lamine-art-png/lamine.github.io` hosts the Portal (`figma-enterprise-v4`, React/Vite),
  the Platform API (`agroai_api`, FastAPI on Render + Postgres, HS256 JWT bearer auth), and
  edge services as Cloudflare Workers deployed by GitHub Actions (`wrangler@4.107.0`).
* Existing Academy work: only an early-access email form Worker at
  `agroai-pilot.com/academy/early-access` and a launch article. No LMS, no course content,
  **no Synthesia integration or video assets** in the repository.
* Language inventory: `shared/supported-locales.json` → 60 enabled UI locales (+ `auto`),
  RTL: `ar`, `fa`, `ur`. Portal catalogs are machine-authored; none is human-reviewed.
* **SSO with the Enterprise Portal:** the Portal API issues HS256 bearer JWTs and exposes no
  OpenID Connect / OAuth authorization server. Sharing its signing secret with the Academy would
  let the Academy mint Portal tokens and is rejected as insecure; cross-domain cookie sharing is
  also out of scope. Standards-based SSO requires adding an OIDC authorization endpoint to the
  Platform API — a change to a production system, deferred for founder approval. The Academy's
  `oauth_accounts` table already supports additional OIDC providers.
* Domain: `academy.agroai-pilot.com` is a subdomain of the company zone used by the other
  Workers. Its current DNS state could not be inspected from the build sandbox (no Cloudflare
  credentials, egress blocked); the deploy script checks it with the API and refuses to proceed
  if an unrelated record exists.

## Phase checklist

- [x] Phase 1 — audit, architecture (standalone Worker + D1), branch
- [x] Phase 2 — design system (light/dark, RTL), public website, auth, catalog, dashboard, admin foundation
- [x] Phase 3 — curriculum model, lesson player, enrollment, progress (resume across devices, offline queue), resources, video assets
- [x] Phase 4 — assessment engine, exams, grading (auto + manual), certificates, PDF + QR, verification, revocation, sharing
- [x] Phase 5 — i18n (60 locales, 6 catalogs), translation workflow, recommendations, analytics
- [x] Phase 6 — automated tests (34 unit/integration + 10-step browser e2e), security review items, accessibility checks, CI, deploy pipeline
- [ ] Staging deployment — requires merge to `main` (or a workflow dispatch from `main`)
- [ ] Production deployment — automatic after staging passes
- [ ] Founder review and publication of Course A1

## Courses

| Course | State |
|---|---|
| A1 Introduction to Artificial Intelligence in Agriculture | **Complete** — 4 modules, 17 lessons, 3 quizzes, 30-question certification bank, 14 video scripts. Status `review`, planned 2026-10-29. Passes every publication check. |
| 33 other roadmap courses (Programs A–E) | Draft records with titles, descriptions, levels, topics and audiences. Hidden from the catalog; listed as "planned" on the Programs page. No instruction written. Program B/C courses must be written against the live Portal/API. |

## Localization coverage

| Locale | UI catalog | Provenance |
|---|---|---|
| en | 100% | source |
| pt-BR, es, fr-FR, ar, sw | 100% | machine-prepared, not reviewed by native speakers |
| 55 other Portal locales | English fallback (interface direction/formatting localized) | — |

Course content is English; content translations can be added per field in the admin console.

## Founder actions

1. **Merge** the branch to `main` to run staging → production deploy, or run *Academy Deploy*
   manually. The deploy fails safely if `academy.agroai-pilot.com` already has an unrelated DNS record.
2. Add GitHub secret `ACADEMY_BOOTSTRAP_ADMIN_EMAILS` (your admin email) before deploying.
3. Email: add `ACADEMY_RESEND_API_KEY` and confirm `academy@agroai-pilot.com` is an authorized
   sender on the verified Resend domain (or change `EMAIL_FROM` in `wrangler.toml`). Without it,
   verification emails are not sent and learners cannot receive certificates.
4. Optional: Google OAuth client (`ACADEMY_GOOGLE_CLIENT_ID/SECRET`, redirect
   `https://academy.agroai-pilot.com/auth/google/callback`); LinkedIn company page id
   (`LINKEDIN_ORGANIZATION_ID` var) so certificates link to the AGRO-AI Academy page.
5. Review Course A1 and the legal pages (Terms, Privacy, Accessibility) with counsel, then publish.
6. Approve Synthesia production of Joshua videos from the scripts in *Admin → Videos*; attach
   finished renders (HLS/MP4 + captions) and approve them.
7. Decide on Portal SSO (requires an OIDC endpoint in the Platform API).

## Known limitations

* PDF certificates use standard fonts (Latin script); names in other scripts print best from the
  web certificate. Learners are told this and can set a Latin credential name.
* HLS plays natively (Safari/iOS/Android); other browsers use the MP4 source.
* No offline downloads; offline tolerance is limited to queued progress sync.
* No AI learning assistant yet (not required for operation; would need source-grounded retrieval).
* Admin console is English-only.
