# AGRO-AI Academy

Free agricultural-AI courses and verifiable certificates from AGRO-AI Inc.
Target address: **https://academy.agroai-pilot.com** (staging: `academy-staging.agroai-pilot.com`).

The Academy is an **independent product**: its own Cloudflare Worker, its own
D1 (SQLite) database, its own deploy pipeline. It shares no runtime, database,
credentials or cookies with the Enterprise Portal (`app.`), the Platform API
(`api.`, Render) or the marketing site, and it does not modify billing,
subscriptions or existing DNS records.

## Architecture

| Layer | Implementation |
|---|---|
| Runtime | Cloudflare Worker (`src/index.js`), server-rendered HTML with progressive-enhancement JS (`public/static/js/academy.js`) — no framework, no npm runtime dependencies |
| Data | Cloudflare D1, schema in `migrations/0001_academy_core.sql`, curriculum seed in `0002_curriculum_seed.sql` (generated), reversible via `migrations/down/` |
| Files (optional) | R2 binding `FILES` for uploaded lesson resources |
| Email | Resend (AGRO-AI's existing provider) through a durable outbox; disabled until `RESEND_API_KEY` is set |
| Auth | Email + password (PBKDF2-SHA256, 100k iterations), verified email, password reset, optional Google OIDC (code + PKCE); server-side sessions in `__Host-` cookies |
| Jobs | Cron trigger: scheduled publishing, exam auto-submission, email retries, opt-in reminders, cleanup |
| i18n | Language inventory read from the Portal manifest `shared/supported-locales.json` (60 locales, 3 RTL); UI catalogs in `src/i18n/`, overridable from the admin console; content translations per field with review status |

Source map:

```
src/app.js            request context, session, locale, CSRF, auth guards, errors
src/routes.js         route table with per-route auth/permission requirements
src/lib/              html escaping, markdown, security, i18n, router, QR, PDF
src/services/         content, progress, assessments, certificates, email, analytics, jobs
src/pages/            learner pages and admin console (src/pages/admin/)
src/content/          curriculum source (catalog, Course A1), legal texts
dev/                  local server + D1 shim (node:sqlite) used by dev and tests
tests/                unit, integration (in-process Worker), e2e (Playwright)
```

## Run locally

Requires Node 22.5+ (uses the built-in `node:sqlite`). No `npm install` needed.

```bash
cd apps/academy
npm run dev:fresh          # http://localhost:8787, fresh database with curriculum seed
```

Register with `admin@academy.test` (the dev bootstrap admin), open
`http://localhost:8787/__dev/mail` to read the verification email, verify, then
use `/admin`. The dev mailbox and `/__dev/cron` exist only in the dev server.

## Tests

```bash
npm test                   # unit + integration (34 tests), runs the real Worker in-process
npm run test:e2e           # Chromium end-to-end journey with WCAG contrast/label/overflow checks
```

The e2e test drives the full journey through the UI: founder publishes →
learner registers → verifies email → enrolls → studies → passes quizzes →
takes the timed exam (autosave) → receives a certificate → downloads the PDF →
verifies it publicly → opens LinkedIn add-to-profile → sees the dashboard;
plus mobile, dark theme and Arabic RTL.

## Deploy

`.github/workflows/academy-deploy.yml` runs on pushes to `main` that touch the
Academy (or manually): CI → **staging** deploy + smoke test → **production**
deploy + smoke test. `scripts/deploy.sh`:

1. Refuses to deploy if the hostname already has a DNS record that is not this
   Worker's custom domain (it never edits DNS).
2. Creates the D1 database if missing, backs up production, applies migrations.
3. Deploys the Worker with its custom domain (Cloudflare provisions DNS + TLS).
4. Generates `CERT_SIGNING_SECRET` inside Cloudflare if absent and loads
   optional secrets from GitHub secrets.

GitHub secrets used (environment `production`): `CLOUDFLARE_API_TOKEN`,
`CLOUDFLARE_ACCOUNT_ID` (already used by other workflows) and, optionally,
`ACADEMY_BOOTSTRAP_ADMIN_EMAILS`, `ACADEMY_RESEND_API_KEY`,
`ACADEMY_GOOGLE_CLIENT_ID`, `ACADEMY_GOOGLE_CLIENT_SECRET`.

Rollback: `npx wrangler rollback --name agroai-academy` (Worker) and
`migrations/down/*.down.sql` (schema, destructive — export first).

## Operating the Academy

* **Admins:** set `ACADEMY_BOOTSTRAP_ADMIN_EMAILS`; those addresses become
  super administrators after verifying their email. Super admins grant other
  roles (academy admin, instructor, content editor) from *Admin → Learners*.
* **Publishing:** *Admin → Courses* shows a readiness checklist. Publishing or
  scheduling is blocked until every check passes. Course A1 is in **review**
  with a planned date of 29 Oct 2026; publish it after faculty review.
* **Videos:** *Admin → Videos* records Synthesia/R2/Stream assets and their
  captions. Only **approved** videos with a playable URL are shown; others show
  an honest "in production" notice. Course A1 ships with a spoken script per
  lesson ready for Joshua video production.
* **Questions:** written in a plain-text format (`* ` marks correct options,
  `Left => Right` for matching, one line per ordered item).
* **Translations:** *Admin → Translations* edits UI strings without a deploy,
  translates course content field by field, and exports/imports JSON for
  translators. Certification exams use **reviewed** translations only.
* **Certificates:** issued automatically when eligible; *Admin → Certificates*
  revokes, reinstates and (with a documented reason) issues manually. Every
  action is in the audit log.

See `docs/STATUS.md` for the execution checklist, what is complete, and what
needs founder action.
