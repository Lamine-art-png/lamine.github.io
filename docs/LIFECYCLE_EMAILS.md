# Lifecycle onboarding email

Automated onboarding email for the AGRO-AI Enterprise Portal, layered on the
existing email provider (`app/services/email_delivery.py`, Resend or SMTP), the
existing hourly scheduled maintenance, and the existing localization pipeline.

## Sequence (sequence version `2026-10-01.v1`)

| Step | When | Sent only if | CTA |
| --- | --- | --- | --- |
| `welcome` | at email verification | always | `/onboarding` |
| `connect_data` | day 1 | no uploaded file or connected system yet | `/integrations` |
| `ask` | day 3 | plan includes Ask AGRO-AI and it has not been used (variant: with/without data) | `/intelligence` |
| `field` | day 5 | no Field Intelligence observation yet | `/field-intelligence` |
| `market` | day 7 | no Market Intelligence position yet (the production crop-position surface) | `/market-intelligence` |
| `connectors` | day 10 | no live connection yet (Free: file import now, live connections from Professional) | `/integrations` |
| `team` | day 12 | plan includes team invitations, user is owner/admin, no invitation yet | `/team` |
| `plans` | day 14 | effective plan is Free, owner/admin, not Enterprise, never subscribed; variant `usage` only when ≥80% of the real evidence-upload quota is used | `/billing` |
| `reactivation` | day 21 | inactive ≥7 days and a step is unfinished; CTA is the first unfinished step | dynamic |

Rules: at most one lifecycle email per user per pass and ≥20 h apart; a step
more than 72 h overdue is skipped as `expired` (no catch-up bursts after an
outage or late enablement); every skip records its reason. Plan facts come from
the effective entitlements at send time (`resolve_effective_entitlements`), so
emails never invite a customer to a feature their plan does not include.

## Architecture

- `app/services/lifecycle_emails.py`: campaign logic, signals from existing
  tables (data sources, connectors, chat/intelligence runs, Field Intelligence
  observations, Market Intelligence positions, invitations, quota usage,
  `last_login_at`), scheduling, rendering, sending, attribution.
- `app/services/lifecycle_email_i18n.py`: localized copy.
- `app/api/v1/lifecycle_email_routes.py`: unsubscribe, provider events, admin view.
- `alembic/versions/038_lifecycle_emails.py`: `lifecycle_email_enrollments`,
  `lifecycle_email_sends` (unique `(user_id, step)` = idempotency key);
  `039_lifecycle_next_action.py`: `next_action_at` on the enrollment.
- Scheduling: after every pass an enrollment records when it next has work
  (the next step's due time, no earlier than a retry/deferred-localization
  time or the 20h gap; a stale in-flight claim is re-examined after 30 min).
  `process_due` selects only active enrollments due now, earliest first, up to
  the batch limit, so users who are merely waiting never fill a batch and a
  backlog larger than the batch rotates. An enrollment whose processing raises
  backs off one hour instead of holding the head of the queue.
- Hooks: `/v1/auth/email-verification/confirm` and
  `/v1/team/invitations/accept-new-account` enqueue `enroll_and_start` as a
  background task; `/v1/internal/queue/drain-outbox` (hourly Cloudflare edge
  cron) runs `run_scheduled`, isolated from the other maintenance jobs.

## Localization

Copy lives in `shared/localization/lifecycle-email-source.json`. Language is
resolved at send time from the user's current preference (then the signup
locale). For every supported locale the email is delivered in that language:
the deterministic catalog `shared/localization/lifecycle-email-catalogs/<locale>.json`
(authored by `i18n-global-authoring.yml`, installed by
`scripts/i18n-install-authoring-artifacts.py`) or, until it exists, the
platform translator (ModelRouter `ui_translation`) with key/placeholder
validation. If neither works the send is deferred hourly for up to 3 days and
then skipped as `localization_unavailable` — never sent in English. English is
used only for unknown/unsupported/invalid locales. RTL locales render `dir="rtl"`.

Catalog quality: fr-FR, pt-BR, es, sw, sr and wo are hand-written; the
other locales are machine-authored with hand corrections to high-risk keys.
Each catalog envelope has a `review` object stating exactly that (none has
had native-speaker review). The release gate and every generator reject
degenerate machine output (token loops, one stock phrase reused for many
unrelated strings) and keep Serbian in Cyrillic. Keep the English source free
of phrases machine translation renders literally ("seats", "evidence uploads",
"setup emails", "operation", "field walks", a sentence-initial "Crop").

Wolof (wo) is a target locale with a shipped lifecycle catalog, but it is not
advertised: its UI, transactional and legal artifacts cannot yet be authored
(no provider in the pipeline produces usable Wolof), so the gate fails it
closed and a `wo` preference resolves to English until it is released.

The field and market steps only run when Field Intelligence / Market
Intelligence are released to the organization (their release gates), so an
email never sends a customer to a page they cannot open. Market copy uses the
page's own terms: crop and market intelligence live in Market Intelligence.

To change copy: edit the English source, push an `i18n-authoring/*` branch,
install the artifacts. The matrix (`scripts/i18n-authoring-matrix.py`) includes
every locale whose lifecycle catalog is not current.

## Preferences and compliance

- Every email carries a footer reason, an unsubscribe link, RFC 8058
  `List-Unsubscribe` / `List-Unsubscribe-Post` headers, the company name and
  the postal address. The unsubscribe link (HMAC token derived from
  `SECRET_KEY`) shows a confirm button (GET never unsubscribes, so link
  scanners cannot); POST and one-click POST unsubscribe.
- Unsubscribing stops only this sequence (stored on the enrollment, not in
  `notifications_json`, so a Settings save cannot undo it). Verification,
  security, invitation, billing and support email are unaffected.
- Permanent bounces and complaints (Resend webhook) stop the sequence.

## Configuration (Render, API service)

| Variable | Required | Purpose |
| --- | --- | --- |
| `LIFECYCLE_EMAILS_ENABLED` | yes, `true` to send | Feature flag; default off |
| `LIFECYCLE_EMAIL_POSTAL_ADDRESS` | yes | Physical postal address in the footer (CAN-SPAM). Sending is held until set |
| `RESEND_WEBHOOK_SECRET` | for analytics | `whsec_…` signing secret; endpoint fails closed without it |
| `RESEND_API_KEY`, `FROM_EMAIL` | existing | Provider (already configured) |

Resend dashboard: add a webhook to `https://app.agroai-pilot.com/v1/email/provider-events`
for `email.delivered`, `email.opened`, `email.clicked`, `email.bounced`,
`email.complained`, and enable open/click tracking on the sending domain if
open/click analytics are wanted.

## Rollout

1. Deploy (migration 038 runs at startup). With the flag off, verified sign-ups
   are enrolled but nothing is sent.
2. Set `LIFECYCLE_EMAIL_POSTAL_ADDRESS`, optionally the webhook secret, then
   `LIFECYCLE_EMAILS_ENABLED=true`. New verifications get the welcome
   immediately; later steps go out on the hourly maintenance.
3. Existing accounts are never enrolled automatically. To include a cohort:
   `python scripts/lifecycle_backfill.py --created-after 2026-09-01 --start-step reactivation --limit 50`
   (dry run), then add `--apply`. Earlier steps are recorded as skipped.

## Debugging

`GET /v1/admin/lifecycle-emails/{user_id}` (platform administrators only):
enrollment status and stop reason, unsubscribe state, each step's status,
reason, variant, locale, plan at send, attempts, delivery/open/click/bounce
times, attributed activation, and the next scheduled step. Logs:
`lifecycle_email_*` lines in logger `agroai.lifecycle_email`.
