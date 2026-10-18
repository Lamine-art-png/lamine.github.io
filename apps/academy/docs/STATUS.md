# AGRO-AI Academy — execution status

Updated 2026-10-18 (second audit pass). Branch: `claude/inspiring-hypatia-gq0x5p`. Nothing is deployed yet;
merging to `main` deploys **staging only**. Production needs a separate, confirmed dispatch.

## Launch plan for 29 October (one excellent course)

Course A1 *Introduction to Artificial Intelligence in Agriculture* is complete in content
and passes every automatic check, but by design it **cannot be published** until people do
the following in the admin console (Admin → Courses → A1):

1. **Record the three mandatory reviews** (academic, assessment, accessibility). Each
   approval is bound to a fingerprint of the exact draft reviewed; any later edit to
   lessons, quizzes or exam questions voids it until it is recorded again. After launch,
   every change is a draft that needs fresh reviews and an explicit "Publish changes".
2. **Decide on instructor video**, one of:
   - *Required* (default): approve all 14 Joshua videos in Admin → Videos — playable HLS or
     MP4 URL, **duration in seconds**, plus **reviewed English captions** for each. None exist yet; scripts are ready.
   - *Optional*: switch the course's video policy to "optional" with a written reason
     (for example "text-first launch; videos follow after approval"). It is audited and
     shown in the readiness list; learners see an "in production" notice instead of video.
3. Clear legal review of Terms, Privacy and Accessibility, then publish or schedule.
   A scheduled course is re-checked when its time comes and goes back to review if
   anything changed.

Instructor video production is **not complete**: no approved Joshua video assets exist.

## Hardening pass (2026-10-18)

| # | Requirement | What changed | Evidence |
|---|---|---|---|
| 1 | Fail-closed certificate verification | A credential shows as valid only when its HMAC is recomputed and matches. Missing, short (<32 chars) or erroring signing configuration returns 503 "verification unavailable". Staging no longer falls back to a development key. `/healthz` is 503 in staging/production without signing, so the post-deploy smoke test fails. No unsigned credential is issued (progress kept; claim later). PDFs only for verified records. | `tests/integration/certificates-integrity.test.js` |
| 2 | Durable, verified backups | Before migrations: export → restore into a scratch SQLite DB (integrity, foreign keys, row counts vs live) → gzip (optional GPG AES-256) → private R2 bucket → read back and checksum. Any failure stops the deploy before schema or code change. Time Travel bookmark recorded. `scripts/restore-backup.sh` restores into a **new** database only. The signing key is never replaced and never regenerated while certificates exist. | `tests/deploy/deploy-script.test.js` (fake wrangler + fake Cloudflare API: 14 scenarios incl. 6 failure modes) |
| 3 | Publication readiness | Migration 0003: append-only `course_reviews` + video policy. Mandatory reviews bound to content hash; required videos approved, playable and captioned; scheduled publication re-checked; review permission separate from publish. | `tests/integration/publication-readiness.test.js` |
| 4 | Exam retry after expiry | Expired attempts are graded first (closed at the deadline), then eligibility is recomputed: maximum attempts and cooldown apply. | `tests/integration/exam-expiry.test.js` (2 of 5 fail on the previous code) |
| 5 | Separate environments | Push to `main` → staging only (`academy-staging` environment, `ACADEMY_STAGING_*` secrets). Production: manual dispatch on `main`, `target=production`, phrase `deploy academy production`, after staging passes in the same run, `academy-production` environment, `ACADEMY_PRODUCTION_*` secrets, `ACADEMY_DEPLOY_CONFIRM=production`. Separate Workers, D1 databases, file buckets, backup buckets. | deploy tests; `.github/workflows/academy-deploy.yml` |
| 6 | Unicode certificate PDFs | TrueType subsetter + OpenType shaper (bidi, Arabic joining, Indic syllables, Thai, marks, kerning). Embedded font subsets with ToUnicode/ActualText. Fonts: DejaVu, GNU FreeSerif, WenQuanYi Zen Hei (licenses in `public/static/fonts/pdf/LICENSES.txt`). | 117 names in 20+ scripts match Chromium/HarfBuzz (`tests/e2e/shaping-oracle.mjs`); golden fixture in unit tests; 11 PDFs render and extract correctly in Poppler; Arabic, Chinese, Hindi, accented Latin end to end |
| 7 | Course-learning flow | Video lessons with an approved video complete only by watching (90% of server-known length over plausible time, ≤2× speed); forged/explicit completion refused. E2E plays a real (synthetic) WebM clip, captions, saved position, resume after reload, watch-to-complete at 2×. | `tests/e2e/run.mjs`, `tests/integration/platform.test.js` |
| 8 | Honest internationalization | `/languages` lists all 60 languages with interface status (original / reviewed / automatic not yet reviewed / English for now), reviewed course translations and exam language. Picker groups translated vs English-for-now; notices on automatic or untranslated pages; copy no longer implies 60 translated languages. | `platform.test.js` "language support…" |
| 9 | Integrations when configured | Contract tests against recorded fakes (not live): Resend request shape, idempotency, retries, failures; reset and certificate links; Google OAuth with PKCE; certificate links; R2 uploads. Fixes: Google pre-account hijacking; R2 unsized stream; upload content sniffing; file buckets were not bound at all. | `tests/integration/integrations.test.js` |
| 10 | Real staging test | `tests/remote/staging.mjs` runs over HTTP against the deployed staging Worker and its D1: health, headers, public pages, register → verify (via token-protected staging-only inbox) → sign-in → enroll/progress → password reset → account deletion. Refuses to write unless the target reports `staging`. | `tests/integration/staging-harness.test.js` runs it against a local HTTP server |
| 11 | No regressions elsewhere | Only `apps/academy/**` and the two `academy-*` workflows changed. New, separately named Workers, databases and buckets; DNS guard refuses existing records. | see "Regression check" |
| 12 | Security, authorization, accessibility | See "Audit" below. | axe-core scan of 38 pages in CI; e2e accessibility checks |

## Second audit pass (2026-10-18)

| # | Finding | Resolution | Evidence (each test fails on the previous code) |
|---|---|---|---|
| Codex P1 | Attempts reinterpreted after an assessment is edited | Migration 0004: each attempt freezes its policy (kind, passing score, time limit, feedback policy, certification) and every drawn question (prompt, options, answer key, explanation, rubric, grading, points, case, translation). Scoring, grading, the attempt and review pages read the snapshot. | `tests/integration/attempt-snapshots.test.js` (4) |
| Codex P1 | Edits to a published course bypassed the mandatory reviews | Migration 0005: editors change a **draft**; learners see only live content, which changes only when a draft that passed readiness (reviews bound to that exact draft) is explicitly published as a numbered revision (`course_revisions`). Publication hides/retires removed content, never deletes it; progress, attempts and certificates keep their references. Discard restores the live revision. Banks belong to one course. | `tests/integration/course-drafts.test.js` (9) |
| Codex P2 | Country-registry changes did not trigger Academy CI/deploy | Registry added to CI and deploy path filters; a unit test derives every out-of-app import and checks the filters. | `tests/unit/workflow-paths.test.js` |
| 4 | Backup accepted up to max(5, 1%) missing rows | Critical records (users, roles, enrollments, progress, attempts, answers, certificates, certificate events, reviews, revisions) fingerprinted before and after the export: every record unchanged across the export must be in the dump identically; append-only records may never vanish. Pending migrations are rehearsed on the restored copy. Restore drills compare the new database with the backup exactly. | `tests/deploy/deploy-script.test.js` (21 scenarios incl. one dropped certificate/attempt/enrollment, an altered certificate, a vanished certificate, concurrent writes, a migration failing on real data, a lossy restore) |
| 5 | Staging write-path test skipped without credentials | Missing/short `ACADEMY_STAGING_TEST_INBOX_TOKEN` fails the staging job (before deploy and in the test); production `needs: staging`. A staging-only, token-protected probe course (published through the revision path) makes the full write path run on every deploy: registration, verification, sign-in, enrollment, progress, completion, certification exam, certificate issuance, public signature verification, password reset, account deletion (certificate revoked). | `tests/integration/staging-harness.test.js` (5), `tests/unit/release-gate.test.js` |
| 6 | Video completion trusted a client position plus wall-clock time | Server-timed heartbeats (migration 0006): only forward playback possible at ≤2× between beats 2–120 s apart (server clock) is credited; spans are merged; completion at 90% of the **server-recorded** duration (approval now requires it). Trust boundary in `docs/VIDEO_PROGRESS.md`. | `tests/integration/video-watch.test.js` (8: forged 95%, explicit completion, start-and-wait, fake duration, 3× speed, floods, replayed queues, rewatch loops, interleaved tabs, legitimate 1×/2× with pauses and seeks); e2e plays a real clip at 2× |
| 7 | Settings changed during an active exam | Covered by the snapshots, and end to end through the admin path: edit threshold (100%), time limit (1 min) and feedback (full), review, publish during an open exam → deadline, 80% threshold and correctness-only feedback unchanged. | `course-drafts.test.js` "publishing new exam settings while an exam is open…" |
| 8 | Preserve safeguards | Signature verification, Unicode PDFs, reviews, localization and environment isolation untouched and still tested. | full suite below |

### Results of this pass (local, commit noted in the PR)

- `npm test` (unit, integration, deploy): **132/132 pass**.
- Browser e2e (`tests/e2e/run.mjs`, Chromium): **12/12 steps pass**, including video watch-to-complete at 2×.
- Shaping oracle: **117/117** names match Chromium/HarfBuzz. Poppler: **11/11** PDFs render and extract.
- Seed and i18n index regenerate with no diff. Repository secret scan passes.
- axe-core is not installable in the offline sandbox; the WCAG scan runs in Academy CI.

### Outstanding issues (honest list)

- **Not deployed and not verified live.** Staging has never run: the Cloudflare and staging
  secrets below must be added first. The staging gate will fail (by design) until
  `ACADEMY_STAGING_TEST_INBOX_TOKEN` exists.
- **Video assurance has a stated limit:** a script sending plausible heartbeats in real time
  for half the video's length can pass; the credential rests on the graded exam.
- **Backups:** records created or changed during the export are reported, not required;
  D1 has no consistent-snapshot export, so the Time Travel bookmark remains the
  point-in-time recovery path for those.
- **Course drafts:** content translations (Admin → Translations) still apply to live content
  directly and are not part of the reviewed revision (certification exams use only reviewed
  translations, frozen per attempt). The admin "Open in classroom" link shows the live
  revision, not the draft.
- Earlier items remain: Telugu/Myanmar names in PDFs, GPL font counsel review, unreviewed
  machine catalogs, separation of duties, manual screen-reader audit, no adaptive-streaming
  library.

## Exact deployment requirements

GitHub (repository settings → Environments):

- Environment **`academy-staging`**: secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
  `ACADEMY_STAGING_BOOTSTRAP_ADMIN_EMAILS`, `ACADEMY_STAGING_TEST_INBOX_TOKEN` (random, ≥32 chars;
  **mandatory** — without it the staging job fails and production cannot deploy).
  Optional: `ACADEMY_STAGING_RESEND_API_KEY`, `ACADEMY_STAGING_CERT_SIGNING_SECRET`,
  `ACADEMY_STAGING_BACKUP_PASSPHRASE`, `ACADEMY_STAGING_GOOGLE_CLIENT_ID/SECRET`.
- Environment **`academy-production`**: add **required reviewers**; secrets `CLOUDFLARE_API_TOKEN`,
  `CLOUDFLARE_ACCOUNT_ID`, `ACADEMY_PRODUCTION_BOOTSTRAP_ADMIN_EMAILS`,
  `ACADEMY_PRODUCTION_RESEND_API_KEY`, `ACADEMY_PRODUCTION_BACKUP_PASSPHRASE` (recommended),
  `ACADEMY_PRODUCTION_CERT_SIGNING_SECRET` (recommended: generate 64 hex chars and keep a copy in
  a password manager; if omitted one is generated inside Cloudflare and cannot be recovered).
  Optional Google: `ACADEMY_PRODUCTION_GOOGLE_CLIENT_ID/SECRET` with redirect URI
  `https://academy.agroai-pilot.com/auth/google/callback` (staging: `https://academy-staging.agroai-pilot.com/auth/google/callback`).

Cloudflare (account of `agroai-pilot.com`):

- API token permissions: Workers Scripts edit, Workers custom domains edit, D1 edit, R2 edit,
  Zone `agroai-pilot.com` DNS read.
- R2 enabled (buckets created automatically: `agroai-academy-files`, `agroai-academy-backups`,
  and `-staging-` equivalents). Set a backup retention lifecycle consistent with the privacy policy.
- Workers Paid plan recommended: certificate PDFs for complex scripts take ~2–40 ms CPU.
- Hostnames `academy.agroai-pilot.com` and `academy-staging.agroai-pilot.com` must have no
  existing DNS record (the deploy refuses otherwise).

Email: verify `academy@agroai-pilot.com` as a sender on the Resend domain (or change `EMAIL_FROM`).

Then: merge → staging deploy, smoke test and staging integration test → run *Academy Deploy*
manually on `main` with `target=production` and `confirm=deploy academy production`.

## Regression check (other AGRO-AI systems)

- Files changed outside `apps/academy/`: `.github/workflows/academy-ci.yml`,
  `.github/workflows/academy-deploy.yml` (both Academy-only, path-filtered). Nothing else.
- Enterprise Portal, Platform API, marketing site, guides and other Workers: no file changed.
  `shared/supported-locales.json` and `shared/registries/countries.json` are read, not modified.
- Cloudflare resources are new and Academy-named; the existing `agroai-academy-early-access`
  Worker (route `agroai-pilot.com/academy/early-access`) is untouched. The repository-wide
  secret scan passes; the repository's actionlint job validates the workflows on the PR.

## Audit (security, authorization, accessibility)

Fixed in this pass: fail-open certificate verification; staging using a development signing
key; possible regeneration of the signing key on a failed secret listing; trailing newline in
generated keys; backups that were discarded and errors ignored; exam limit bypass after
expiry; publication without reviews or approved media; forged video completion; Google
pre-account hijacking; R2 uploads that would fail; upload type spoofing; missing file
bucket binding; header overflow in longer languages; duplicate form ids in admin pages.

Verified: CSRF on every state-changing route (token + Origin); role checks on every admin
route; learners cannot read others' attempts, certificates or files; output escaping; CSP
without inline scripts or styles; HSTS, nosniff, frame denial; rate limits on sign-in,
registration, resets, claims, PDFs, verification; identifiers interpolated into SQL come from
fixed allow-lists; the staging inbox is unavailable outside staging and without its token.

Remaining gaps (documented, not hidden):

- No live verification yet of Resend, Google, R2 or D1 in Cloudflare — requires the secrets above.
- Certificate PDFs cannot print Telugu or Myanmar names (no font); the learner is told and the
  web certificate shows the name as written. Other scripts of the 60 languages are covered.
- The GPL-licensed name fonts (with font-embedding exceptions) should be confirmed by counsel;
  they can be swapped for OFL fonts (e.g. Noto) by regenerating the golden fixture and passing
  the oracle.
- Five interface catalogs are machine-prepared and unreviewed; 54 languages show English.
- Separation of duties: one person holding both reviewer and publisher roles can review and
  publish (all actions are audited). Use distinct people for launch.
- Accessibility is checked automatically (axe-core WCAG 2.2 AA, contrast, labels, landmarks,
  duplicate ids, overflow, RTL, dark mode) but has not had a manual screen-reader audit.
- Video plays progressively (MP4/WebM) in all browsers and HLS natively; no adaptive streaming
  library for Chromium/Firefox.

## Courses

| Course | State |
|---|---|
| A1 Introduction to Artificial Intelligence in Agriculture | Content complete (4 modules, 17 lessons, 3 quizzes, 30-question exam bank, 14 video scripts). Status `review`, planned 2026-10-29. Blocked on the three reviews and the video decision (above). |
| 33 other roadmap courses | Draft records only; hidden from the catalog; listed as planned. |
