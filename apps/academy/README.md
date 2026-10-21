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

## Brand

The official AGRO-AI Academy lockup is `brand/agro-ai-academy-logo.svg`, the single source
for every logo file. `src/brand.js` holds the logo paths, the palette (sampled from the logo)
and the brand typeface, and is used by pages, emails, certificates and the CSP.

- Regenerate the logo assets after the source changes (needs Playwright's Chromium and Pillow):
  `node scripts/brand/render-logo.mjs /tmp/logo@2x.png && python3 scripts/brand/build_assets.py /tmp/logo@2x.png`.
  It writes `public/static/brand/*` (lockups for light and dark surfaces, mark, favicons,
  email header, 1200×630 social card), `public/favicon.ico`, `public/apple-touch-icon.png` and
  the certificate header image `src/lib/brand-jpeg.js`. Assets only crop, scale or recolour the
  official artwork; nothing is redrawn.
- Typeface: **Glacial Indifference** for headings, navigation and controls; reading text stays
  in a system sans that covers every script. The font loads without blocking the first paint
  from the same source as agroai-pilot.com (`BRAND.fontStylesheet`, allowed by the CSP). To
  self-host it, serve the OFL font files with a local stylesheet and point `fontStylesheet` at it.
- Static files are cached as immutable under `?v=<BUILD>`: bump `BUILD` in
  `src/views/assets.js` whenever anything under `public/static/` changes.

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
npm test                   # unit, integration and deploy-script tests (99), the real Worker in-process
npm run test:e2e           # Chromium end-to-end journey with WCAG contrast/label/overflow checks
node tests/e2e/shaping-oracle.mjs   # certificate-name shaping vs Chromium/HarfBuzz (117 names)
node tests/e2e/pdf-poppler.mjs      # certificate PDFs rendered and extracted by Poppler
node tests/e2e/axe.mjs              # axe-core WCAG 2.2 AA scan (needs axe-core installed)
npm run test:staging -- https://academy-staging.agroai-pilot.com   # against deployed staging
```

The e2e test drives the full journey through the UI: founder publishes →
learner registers → verifies email → enrolls → studies → passes quizzes →
takes the timed exam (autosave) → receives a certificate → downloads the PDF →
verifies it publicly → opens LinkedIn add-to-profile → sees the dashboard;
plus mobile, dark theme and Arabic RTL.

## Deploy

`.github/workflows/academy-deploy.yml` keeps staging and production apart:

| | Staging | Production |
|---|---|---|
| Trigger | every push to `main` touching the Academy | manual *Academy Deploy* run on `main` with `target=production` and `confirm=deploy academy production`, after staging passes in the same run |
| GitHub environment | `academy-staging` | `academy-production` (add required reviewers) |
| App secrets | `ACADEMY_STAGING_*` | `ACADEMY_PRODUCTION_*` |
| Worker / D1 | `agroai-academy-staging` | `agroai-academy` |
| Files / backups (R2) | `agroai-academy-staging-files` / `-staging-backups` | `agroai-academy-files` / `agroai-academy-backups` |
| Checks after deploy | smoke test + **mandatory** staging write-path test (`tests/remote/staging.mjs`, real D1 over HTTP; fails without its token) | smoke test |

`scripts/deploy.sh <target>` (production also needs `ACADEMY_DEPLOY_CONFIRM=production`):

1. Refuses to deploy if the hostname has a DNS record that is not this Worker (never edits DNS).
2. Creates the D1 database and file bucket if missing; fills in only this target's database id.
3. **Backs up before migrating**: fingerprint critical records (learners, roles, enrollments,
   progress, attempts, answers, certificates, reviews, revisions) → export → fingerprint again →
   restore into a scratch SQLite database and check integrity, foreign keys, that **every critical
   record unchanged during the export is present and identical** (no tolerance; append-only
   records may never vanish), other tables' row counts, and that pending migrations apply to the
   restored copy → gzip (GPG AES-256 with `BACKUP_PASSPHRASE`) → private R2 bucket → read back and
   compare checksums. Any failure stops the deploy before the schema or code changes. A D1 Time
   Travel bookmark is recorded as a second recovery path.
4. Applies migrations, deploys the Worker, then sets secrets. The certificate signing key is
   never replaced, and never generated while certificates exist.

Restore drill (never touches the live database; the restored database's row counts and critical
records are compared with the backup exactly):
`bash scripts/restore-backup.sh agroai-academy-backups/<key> agroai-academy-restore-<date> <sha256>`.

Rollback: `npx wrangler rollback --name agroai-academy` (Worker); schema changes are additive
and reversible with `migrations/down/*.down.sql` (destructive — export first).

The exact secrets, Cloudflare permissions and launch steps are in `docs/STATUS.md`.

## Operating the Academy

* **Admins:** set `ACADEMY_BOOTSTRAP_ADMIN_EMAILS`; those addresses become
  super administrators after verifying their email. Super admins grant other
  roles (academy admin, instructor, content editor) from *Admin → Learners*.
* **Publishing:** editors always change a **draft** of the course. Learners see the live
  content, which changes only when a draft is published as a numbered **revision**.
  *Admin → Courses* shows a readiness checklist. Publishing or scheduling is blocked until
  every check passes, including three mandatory reviews (academic, assessment,
  accessibility) recorded against the exact draft — editing afterwards voids them — and,
  under the default video policy, approved, playable, captioned videos for every planned
  lesson video. Publication never deletes what learners used: removed lessons are hidden,
  removed modules, assessments and questions retired, and open exam attempts keep their
  frozen questions and policy. Unpublished changes can be discarded. A course that has
  never been released follows its draft directly (it is shown as upcoming). A course may switch to an
  "optional" video policy with a recorded, audited reason. Scheduled courses are
  re-checked at publication time. Course A1 is in **review** for 29 Oct 2026.
* **Videos:** *Admin → Videos* records Synthesia/R2/Stream assets (https URLs only) and
  their captions. Only **approved** videos with a playable URL are shown; others show an
  honest "in production" notice. Approval requires the video's duration. Video lessons
  complete only by watching, measured by the server from timed heartbeats
  (`docs/VIDEO_PROGRESS.md` explains the rule and its trust boundary). Course A1 ships
  with a spoken script per lesson ready for Joshua video production; no video is approved yet.
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
