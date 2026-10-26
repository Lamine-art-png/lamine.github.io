# AGRO-AI Academy — staging, launch and production runbook

Release candidate: PR #618 (`claude/inspiring-hypatia-gq0x5p`). Nothing in
this document deploys production; production needs the founder's explicit
approval and a manual workflow run (section 6).

## 1. Infrastructure preflight (2026-10-20, workflow "Academy Preflight")

The preflight workflow (`.github/workflows/academy-preflight.yml`) is read-only
and prints secret presence only, never values. Re-run it at any time from the
Actions tab (after merge) or by re-running the PR check.

| Item | Finding |
|---|---|
| Cloudflare API token (repository secret) | Present, valid, active. Zone `agroai-pilot.com` accessible (Free plan). |
| Workers / custom domains | Readable; the same token already deploys Workers on custom domains (`faep`, `signal`). |
| R2 | Readable (3 company buckets). Academy buckets are created by `deploy.sh`. |
| **D1** | Repository token: HTTP 401 (no D1). Resolved with a dedicated Academy token in the `academy-staging` environment (D1 and DNS readable). `academy-production` still needs its own. |
| DNS records | HTTP 403 (no DNS read). `deploy.sh` now falls back to public DNS for the ownership check; Cloudflare also refuses to attach a custom domain over an existing record. |
| Academy hostnames | `academy.agroai-pilot.com` and `academy-staging.agroai-pilot.com` do not resolve: no records, nothing to collide with. |
| Existing Academy resources | None (no Academy Worker, D1 database or bucket yet). |
| GitHub environment `academy-staging` | Exists (created by the preflight), no protection rules, no environment secrets; inherits the repository Cloudflare secrets. |
| GitHub environment `academy-production` | Not created yet. It is created on first use; add required reviewers before the first production run. |
| Company email | Platform API reports Resend configured, sender domain `mail.agroai-pilot.com`; operator notifications from `no-reply@mail.agroai-pilot.com` are being delivered. The Academy now sends from `academy@mail.agroai-pilot.com` (same verified domain), replies to `contact@agroai-pilot.com`. |
| Resend key for the Academy | The company key lives in the `production` environment only and cannot be read by Academy jobs. A copy (or a new sending-only key) must be added as an Academy secret. |
| Early-access form | `agroai-pilot.com/academy/early-access` live (HTTP 200), untouched. |

### What deploys without any new secret

`deploy.sh` creates the D1 database and both private R2 buckets, generates the
certificate-signing key inside Cloudflare (staging), and the staging workflow
generates a fresh, masked staging test token on every run. Bootstrap admin
emails, Resend and Google are optional for staging: without them the staging
test still runs end to end (its synthetic addresses use a suppressed outbox).

## 2. Founder checklist (everything that only you can do)

Staging setup (done in PR #601; kept for reference):

1. **Cloudflare token: add D1 permission.** In Cloudflare → My Profile → API
   Tokens, edit the token stored as the GitHub secret `CLOUDFLARE_API_TOKEN`
   and add **Account → D1 → Edit** (recommended also: **Zone agroai-pilot.com →
   DNS → Read**). Alternatively create a dedicated Academy token with: Account →
   Workers Scripts Edit, D1 Edit, Workers R2 Storage Edit, Account Settings
   Read; Zone agroai-pilot.com → Workers Routes Edit, DNS Read, Zone Read — and
   save it as `CLOUDFLARE_API_TOKEN` in the `academy-staging` and
   `academy-production` GitHub environments (environment secrets override the
   repository one, so other company workflows are unaffected).
   Then re-run the "Academy Preflight" check: D1 must read as accessible.

Recommended for a full live staging test (each is optional):

2. `ACADEMY_STAGING_BOOTSTRAP_ADMIN_EMAILS` (environment `academy-staging`):
   your email, to sign in to the staging admin console.
3. `ACADEMY_STAGING_RESEND_API_KEY`: the company Resend key (or a new
   sending-only key for `mail.agroai-pilot.com`), to verify real email delivery
   to your own inbox on staging.
4. `ACADEMY_STAGING_GOOGLE_CLIENT_ID` / `_SECRET`: only if Google sign-in should
   be tested (OAuth redirect URI
   `https://academy-staging.agroai-pilot.com/auth/google/callback`).

### Production secrets readiness (preflight run 40214066973, 2026-10-25)

GitHub environment `academy-production` exists. The preflight reports only
presence, never values:

| Secret (environment `academy-production`) | Present | What it is / how to create it |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | yes (repository secret; no production-specific token found) | The repository token **cannot read D1** (HTTP 401), so it cannot deploy the Academy. Add the same scoped Academy token used by `academy-staging` (Workers Scripts Edit, D1 Edit, Workers R2 Storage Edit, Account Settings Read; zone: Workers Routes Edit, DNS Read, Zone Read) as an **environment** secret of `academy-production`. |
| `CLOUDFLARE_ACCOUNT_ID` | yes | — |
| `ACADEMY_STREAM_API_TOKEN` | yes (repository secret) | Stream:Edit only. Required: no deploy starts without it. |
| `ACADEMY_PRODUCTION_CERT_SIGNING_SECRET` | **no** | Signs every certificate. Production has never issued one: the database `agroai-academy` does not exist (preflight D1 listing), so a new key invalidates nothing. Generate it **yourself**: `openssl rand -hex 32`. Store it first in the company password manager (escrow), then as this secret. If it is left empty, `deploy.sh` generates a key inside Cloudflare that can never be read back: no escrow. It never replaces an existing key, and it refuses to deploy if certificates exist without one. |
| `ACADEMY_PRODUCTION_BACKUP_PASSPHRASE` | **no** | **Required: the production deploy refuses to start without it** (at least 20 characters). Encrypts every pre-migration backup (GPG AES-256). Each deploy first runs an encrypt/decrypt self-test, then decrypts the stored copy and compares it with the verified export before any migration. Use a long random passphrase, e.g. `openssl rand -base64 48`, kept in the password manager. A lost passphrase makes those backups unrecoverable. |
| `ACADEMY_PRODUCTION_RESEND_API_KEY` | **no** | Sends verification, password-reset and certificate emails from `academy@mail.agroai-pilot.com`. Create a sending-only key for the verified domain `mail.agroai-pilot.com` in Resend. Without it, production cannot verify accounts, so nobody can earn a certificate. |
| `ACADEMY_PRODUCTION_BOOTSTRAP_ADMIN_EMAILS` | **no** | The exact address(es) of the founder's production account, comma-separated (see "Administrator bootstrap" below). |
| `ACADEMY_PRODUCTION_GOOGLE_CLIENT_ID` / `_SECRET` | no | Optional (Google sign-in). Redirect URI `https://academy.agroai-pilot.com/auth/google/callback`. |

Also before the first production run: add **required reviewers** to the
`academy-production` environment (GitHub → Settings → Environments).

### Administrator bootstrap (staging diagnosis, preflight run 40214066973)

The staging secret `ACADEMY_STAGING_BOOTSTRAP_ADMIN_EMAILS` holds one
address, correctly formatted. It matches no account. Staging has exactly one
real account, verified. That account shares neither the configured
address's domain nor the part before the @, and is not a Gmail variant of it.
The secret and the account use two different addresses. To fix it:

1. Sign in to `https://academy-staging.agroai-pilot.com` and open *Account*
   to see the exact address of your staging account.
2. GitHub → Settings → Environments → `academy-staging` → edit
   `ACADEMY_STAGING_BOOTSTRAP_ADMIN_EMAILS`. Paste that exact address only,
   with no quotes, name or `mailto:`. Use commas to separate several
   addresses.
3. Run *Academy Deploy* for staging (secrets are applied at deploy), then
   sign out and sign in again: the role is granted at sign-in to a verified
   matching address.
4. Re-run *Academy Preflight*: "Bootstrap administrators … super_admin
   role: 1".

Alternatively, register a new staging account with the address already in
the secret and verify it. Use the same procedure for production with
`ACADEMY_PRODUCTION_BOOTSTRAP_ADMIN_EMAILS`.

## 3. Live staging verification

Every push to `main` that touches the Academy runs CI, then deploys staging and
runs `tests/remote/staging.mjs` against `https://academy-staging.agroai-pilot.com`
over real HTTP, Cloudflare D1 and R2. Production depends on that job passing.

| Check | Covered live by | Notes |
|---|---|---|
| Health, D1, signing, language inventory | staging.mjs | |
| Security headers, HTTPS redirect, mobile viewport | staging.mjs | Visual mobile layout and WCAG scan run in CI (Playwright, axe) on the same build, not against the live host. |
| Languages pt-BR, fr-FR, es, ar (RTL) | staging.mjs | |
| Registration → email verification → sign-in | staging.mjs | Synthetic `.invalid` addresses, suppressed outbox read through the token-protected staging inbox. |
| Enrollment → lesson → saved progress → completion | staging.mjs (probe course) | |
| Course publication through a reviewed revision | staging.mjs | Probe course publishes a new revision every run. |
| Exam → result → certificate → PDF → public verification → LinkedIn link | staging.mjs | Exam questions are snapshot at start; grading uses the snapshot. |
| Admin access, role restrictions, A1 publication refused without approvals | staging.mjs | Synthetic staff account gets `academy_admin` through a staging-only, token-protected endpoint (never super_admin). |
| R2 upload by staff, authenticated learner download, anonymous refusal, removal | staging.mjs | |
| Password reset, account deletion (credential revoked) | staging.mjs | |
| Real email delivery to a real inbox | Manual, needs item 3 | Register on staging with your own address. |
| Google sign-in | Manual, needs item 4 | |

Results are recorded per run in the workflow log and job summary. A check is
reported PASS only from a run against the deployed staging host.

### Results — 2026-10-20, run 39384703436 (commit 50c178d, branch code)

Deploy: verified backup of the live staging D1 to the private backup bucket
(read back intact, restore rehearsed), no pending migrations, Worker deployed
to `academy-staging.agroai-pilot.com`. Smoke test: PASS (10 routes).

| Check | Result |
|---|---|
| Health, D1, signing, 60-language inventory | PASS |
| Security headers | PASS |
| Public pages read from D1 | PASS |
| Languages pt-BR, fr-FR, es, ar (RTL) | PASS |
| HTTPS only (http → 308), mobile viewport | PASS |
| Staging inbox closed without the token | PASS |
| Probe course published through the revision path | PASS |
| Registration, email verification (suppressed outbox), sign-out/sign-in | PASS |
| Enrollment, progress, lesson completion | PASS |
| Exam, grading, certificate issuance, public verification | PASS |
| Certificate PDF download, LinkedIn link | PASS |
| Admin closed to learners; staff admin access and role restrictions | PASS |
| Course A1 publication refused without approvals | PASS |
| R2 upload, learner download, anonymous refusal, removal | PASS |
| Password reset, learner deletion, staff deletion | PASS |
| Real email delivery to a real inbox | NOT TESTED (no `ACADEMY_STAGING_RESEND_API_KEY`) |
| Google sign-in | NOT TESTED (no staging OAuth client) |
| Admin console sign-in for the founder | Configured address now matches the founder's verified account; the role is granted on the founder's next request after a staging deploy |
| Backup encryption | Production: ENFORCED by the deploy (no passphrase, no deploy; self-test and decrypt-and-compare of the stored copy before migrations). Staging: optional, configured only if `ACADEMY_STAGING_BACKUP_PASSPHRASE` is set |

Live-only defects found and fixed on the way (local SQLite does not have these
D1 limits; the test doubles now enforce them): compound SELECT term limit in the
pre-migration backup fingerprint (6fabf15), and the 50-byte LIKE pattern cap
that made admin searches return HTTP 500 (50c178d).

## 4. Existing early-access registrants

Where they are: the Platform API database, table `saas_requests`, rows with
`source_page = 'academy/early-access'` (name, email, role, `metadata_json` with
`language`, `email_opt_in`, `campaign`), created through
`api.agroai-pilot.com/v1/sales/contact`. About 18 operator notifications were
delivered to `contact@agroai-pilot.com` between 15 and 20 October, including
internal test submissions from deployment workflows. None of these people has
an Academy account (the Academy has never been deployed). The Academy never
reads the Platform API database.

Process (built and tested in this PR, migration 0008):

1. **Export** (founder or operator with database access, read-only):

   ```sql
   \copy (SELECT id AS source_id, email, name, metadata_json->>'language' AS language,
                 role, COALESCE(metadata_json->>'email_opt_in', 'false') AS email_opt_in,
                 created_at AS registered_at
            FROM saas_requests
           WHERE source_page = 'academy/early-access'
           ORDER BY created_at) TO 'academy-early-access.csv' WITH CSV HEADER
   ```

   Keep the file in a private location and delete it after import.
2. **Import** in the production Academy: Admin → People → Early access (super
   administrators only). Paste the CSV, review the preview (new, already
   imported, already have an account, consented, rejected rows), then import.
   Importing creates no accounts, no passwords, verifies nothing and sends no
   email. Internal test submissions (`contact@agroai-pilot.com`) are skipped;
   duplicates merge by email (earliest registration and any consent kept);
   language and role are preserved.
3. **Activation:** a registrant becomes "activated" only when that person
   registers with the same address **and proves the mailbox** (email
   verification, password reset or Google). Anyone who already has a verified
   account is linked at import time.
4. **Invitation (needs founder approval):** the same page shows how many
   registrants consented, have no account and were never invited, and sends
   them a one-time invitation in their language in confirmed batches of 100
   (typed confirmation; a changed count cancels the send). Each registrant is
   claimed atomically before sending, so nobody is invited twice. Outside
   production only synthetic test addresses can be invited.
5. **Deletion:** deleting an Academy account also deletes the matching
   early-access record.

## 5. Course A1 — Introduction to Artificial Intelligence in Agriculture

State in the release candidate (from the seeded database):

| Item | State |
|---|---|
| Structure | 4 modules, 17 required lessons: 12 text, 1 case study, 1 exercise, 3 module quizzes |
| Module quizzes | 3, each draws 5 of 6 questions, pass mark 60% |
| Certification exam | 20 questions drawn by difficulty (6 easy of 9, 10 medium of 14, 4 hard of 7) from a 30-question bank, 30 minutes, pass mark 80% |
| Certificate | Enabled; requires all lessons and the exam (quiz passes not required) |
| Course status | `review` (not published) |
| Academic reviews recorded | 0 of 3 |
| Instructor videos | **14 of 14 in Cloudflare Stream, all 14 verified private** (§5a). The 14 records are linked to their uploads on staging and remain `scripted` until a person approves each one after watching it. Captions: 14 machine drafts imported for review, **0 reviewed**. |
| Video policy | `required` — publication is blocked until videos are approved, playable and captioned, or the waiver below is approved |
| Other 33 courses | `draft` (shown as upcoming / not open) |

**Three approvals the founder must record** (Admin → Courses → A1, "Reviews" section,
each by a named reviewer, bound to the exact course content; any later edit
voids them):

1. **Academic review** — lesson content and learning objectives are accurate,
   current and appropriate for the stated audience.
2. **Assessment review** — the three quizzes, the 30-question exam bank and the
   80% passing standard measure the learning objectives fairly.
3. **Accessibility review** — reading level, text alternatives, captions or
   transcripts for any media, keyboard and screen-reader use.

**Video policy stays `required` (founder decision, 2026-10-25).** A1 is not
published with missing or unreviewed videos, and no certification check is
waived to meet 29 October. The *Optional* video policy still exists in the
admin for other courses; using it for A1 would need a new, explicit founder
decision.

### 5a. Protected lesson videos (Cloudflare Stream)

**Status (staging deploy run 40216697146, 2026-10-25): 14 of 14 uploaded,
mapped and verified private.** For each video, Stream reports signed URLs
required, embedding limited to the two Academy hosts and no downloads. The
bare id (HLS, MP4, thumbnail) and an expired token are refused (401); a fresh
token plays (200). The real-playback test passed in Google Chrome. 14 English
machine-caption drafts are in the Academy awaiting review and are not in
Stream's player.

The Academy plays these videos only inside Stream's player, from tokens the
Worker signs for an enrolled learner (or staff). Tokens are valid 20 minutes
and the player renews them when they expire. No page, API or caption route
exposes a video id, manifest, MP4 or download. Direct media URLs (`hls_url`,
`mp4_url`) are ignored in staging and production. Without the signing key,
Stream lessons show "temporarily unavailable" (fail closed).

**Every deploy does this, and fails if anything is not verified**
(`scripts/stream.mjs`, run from `deploy.sh`). The Stream token
(`ACADEMY_STREAM_API_TOKEN`, Stream:Edit only) is required: without it no
deployment starts.

- **Maps** uploads to lesson videos by the number in the upload's name
  ("Video4- …", "video 9- …"). The final titles are reworded, so lesson
  titles are only a fallback for unnumbered uploads. If two uploads carry the
  same number, neither is mapped; the run reports it so one can be renamed or
  deleted.
- **Protects every upload in the account**: signed URLs required, embedding
  only on `academy.agroai-pilot.com` and `academy-staging.agroai-pilot.com`,
  downloadable renditions deleted. Names are kept.
- **Re-reads the settings from Stream and probes from outside.** The bare id
  (HLS, MP4, thumbnail) and an expired token must be refused (401/403), and a
  fresh signed token must play (200). The results go to the job summary and to
  `stream_protection`. Publication requires a passing record no older than 8
  days for every Stream video.
- **Creates** the Worker's own signing key on first run (Worker secrets
  `STREAM_SIGNING_KEY_ID`, `STREAM_SIGNING_JWK`; never printed or stored
  elsewhere).
- **Links** each video record to its upload (Stream id, duration measured by
  Stream). It never approves one: a person approves each video in Admin →
  Videos after watching it.
- **Captions:** asks Stream for automatic English captions on videos that have
  none (included for Stream customers; staging deploys set
  `STREAM_GENERATE_CAPTIONS=1`). It imports them as **drafts** (status
  `machine`): never shown to learners, never marked reviewed. Once a reviewer
  corrects a draft and marks it *reviewed* in the admin, the next deploy puts
  the reviewed file in Stream's player in place of the machine one. The
  transcript tab is built only from reviewed captions.
- **Real playback test** (`tests/remote/stream-playback.mjs`, mandatory staging
  step). A synthetic learner plays one verified upload through a staging-only
  probe lesson, which approves nothing in A1. The test checks that:
  - the signed manifest, a rendition and a media segment play;
  - the bare id and anonymous visitors are refused;
  - token renewal works;
  - headless Chromium plays the video in Stream's player.

**Replacing a video:** upload the new file with the same number at the start
of its name, delete the old upload in Stream, then run *Academy Deploy* for
staging. The run must report 14 of 14 mapped and every upload verified
private. A replaced video needs a new approval and new captions.

**Residual risks (cannot be prevented by any web player):** an entitled
learner can screen-record or photograph playback; a signed token copied out
of the page plays until it expires (at most 20 minutes, one video). Downloads,
anonymous playback, embedding on other sites and token scraping (rate limit:
60 tokens per learner per 10 minutes) are prevented. DRM (Widevine/FairPlay)
would raise the bar against capture tools and needs a paid vendor decision.

## 6. Production release (requires founder approval)

Preconditions: staging run green on the merged commit; founder checklist items
5–9 complete; three reviews recorded and the video decision taken (or A1 kept
unpublished at launch).

1. **Run:** Actions → *Academy Deploy* → Run workflow on `main`, target
   `production`, confirmation `deploy academy production`. Staging deploys and
   passes its live test first in the same run; required reviewers on
   `academy-production` must approve.
2. **What the job does:** checks `academy.agroai-pilot.com` has no foreign DNS
   record (refuses otherwise; never edits DNS), creates/uses D1
   `agroai-academy` and private buckets `agroai-academy-files` and
   `agroai-academy-backups`, exports + verifies + stores a backup before any
   migration (on the first deploy the database is new), applies migrations,
   deploys the Worker, sets secrets without ever replacing an existing signing
   key, then runs the read-only smoke test.
3. **Certificate-signing continuity:** the production key comes from
   `ACADEMY_PRODUCTION_CERT_SIGNING_SECRET` (escrowed). It is set once and never
   replaced; the deploy refuses to run if certificates exist and the Worker has
   no key.
4. **Smoke test after deploy (manual, 10 minutes):** `/healthz` (database ok,
   signing configured), home in English and Arabic, register with your own
   address, receive and confirm the email, sign in, open A1 (or see it as
   upcoming if not yet published), `/verify/AGA-0000-0000-0000` → not found.
5. **Publishing A1** is a separate admin action after the reviews; it is not
   part of the deploy.
6. **Rollback:** code — re-run the workflow on the previous good commit, or
   `wrangler rollback` for the `agroai-academy` Worker. Data — every deploy
   records a D1 Time Travel bookmark and a verified backup in
   `agroai-academy-backups`; restore with
   `scripts/restore-backup.sh <bucket>/<key> <new-db-name> <sha256>` into a new
   database, verify, then point `database_id` at it and redeploy. Hostname —
   removing the Worker's custom domain takes `academy.agroai-pilot.com` offline
   without touching any other record.
7. **Isolation:** the Academy uses only its own Worker, D1 databases, buckets
   and hostnames. It does not change DNS, the Enterprise Portal, Platform API,
   billing, the website, the early-access Worker or any other Worker; the
   preflight and the deploy script both assert this.

## 7. Legal pages — review checklist (founder or counsel)

Pages: `/privacy`, `/terms`, `/accessibility` (source
`src/content/legal.js`).

- Controller identity and contact (AGRO-AI Inc., `contact@agroai-pilot.com`).
- Data collected (account, learning records, assessment answers, certificates,
  optional country analytics), purposes and legal bases.
- Processors: Cloudflare (hosting, database, storage), Resend (email), Google
  (optional sign-in). International transfers.
- Retention: accounts until deletion; certificates kept as revoked/anonymized
  after deletion; email outbox; backups (state the backup retention period).
- Early-access registrants: consent given on the agroai-pilot.com form, use
  for one opening invitation, deletion on request and on account deletion.
- Learner rights (access, correction, deletion, export), children's use and
  minimum age, cookies (session, CSRF, language, theme only).
- Certificates: what public verification shows; revocation policy.
- AI-generated content and avatar labelling; no professional-advice disclaimer
  for agronomic decisions.
- Accessibility statement: conformance target WCAG 2.2 AA, known gaps, contact.
