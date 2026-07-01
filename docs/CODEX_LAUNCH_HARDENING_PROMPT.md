# AGRO-AI Launch Hardening Prompt for Codex

You are acting as a principal backend, frontend, AI systems, agriculture-domain, and industrial controls engineer. Treat this as a launch-blocking review for AGRO-AI before exposing the platform to serious enterprise customers.

## Non-negotiable launch standard

AGRO-AI must not feel like a chatbot demo. It must feel like an enterprise operating machine for agriculture. The system must safely convert fragmented farm/controller/compliance/operator evidence into decisions, reports, tasks, audit trails, approval packets, and eventually controller execution when provider-specific safety gates are satisfied.

Do not overclaim. Do not fake live integrations. Do not silently fall back to generic demo data when a real customer request depends on missing evidence, missing credentials, missing field mapping, or missing provider write contracts.

## Critical repo areas to inspect

Backend:
- `agroai_api/app/main.py`
- `agroai_api/app/core/config.py`
- `agroai_api/app/core/security.py`
- `agroai_api/app/api/deps.py`
- `agroai_api/app/api/v1/auth.py`
- `agroai_api/app/api/v1/saas.py`
- `agroai_api/app/api/v1/billing.py`
- `agroai_api/app/api/v1/connectors.py`
- `agroai_api/app/api/v1/controllers.py`
- `agroai_api/app/api/v1/wiseconn.py`
- `agroai_api/app/api/v1/talgil.py`
- `agroai_api/app/api/v1/brain.py`
- `agroai_api/app/api/v1/intelligence.py`
- `agroai_api/app/api/v1/chat_artifacts.py`
- `agroai_api/app/api/v1/agentic_actions.py`
- `agroai_api/app/api/v1/field_operations.py`
- `agroai_api/app/services/model_router.py`
- `agroai_api/app/services/email_delivery.py`
- `agroai_api/app/services/field_operating_loop.py`
- `agroai_api/app/adapters/base.py`
- `agroai_api/app/adapters/registry.py`
- `agroai_api/app/adapters/wiseconn.py`
- `agroai_api/app/adapters/talgil.py`
- all SQLAlchemy models under `agroai_api/app/models/`

Frontend:
- `figma-enterprise-v4/src/app/api/client.ts`
- app shell/routing components
- connector hub components
- Ask AGRO-AI components
- billing/pricing components
- all plan/paywall/onboarding UI

## Backend launch review tasks

1. Run syntax and import checks.
   - `python -m py_compile` on every Python file under `agroai_api/app`.
   - Import FastAPI app: `python -c "from app.main import app; print(app.title)"` from the backend root.
   - Fix every syntax/import error.

2. Route inventory and collision check.
   - Print all FastAPI routes.
   - Confirm no accidental duplicate route shadows a newer endpoint.
   - Confirm every frontend API client route has a backend route.
   - Confirm every backend route used by the UI returns stable JSON shape or expected binary response.

3. Auth and tenancy.
   - Verify every customer data route requires tenant/auth where appropriate.
   - Public routes should be limited to health, product/pricing/catalog-type endpoints, and explicit public diagnostics.
   - Ensure no route leaks another tenant's connector records, evidence, jobs, generated artifacts, reports, team data, or field operations.
   - Ensure credentials/secrets are never returned raw.

4. Database/schema readiness.
   - Verify models and runtime schema guards are consistent.
   - Confirm migrations or runtime guards cover connector tables, email verification tables, team invitations, evidence records, generated artifacts, intelligence runs, jobs, and controller connection fields.
   - Replace fragile runtime schema mutation with Alembic migrations where possible, but do not break current Render deployment.

5. AI/model routing.
   - Confirm `/v1/runtime/ai-status` returns truthful non-secret configuration state.
   - Confirm `/v1/intelligence/brain/model-smoke` can prove model availability.
   - Confirm `/v1/intelligence/brain/run` does not expose raw model JSON to users.
   - Confirm local Ollama mode is bounded and hosted OpenRouter mode can produce serious long-form report answers.
   - Do not let the model claim evidence exists when it was not provided.

6. Report factory.
   - Verify generated PDFs are real downloadable PDFs, not text pretending to be PDFs.
   - Verify AGRO-AI branding/logo renders correctly.
   - Verify PDF generation handles long sections, uploaded evidence metadata, missing evidence, timestamps, tables, and appendices without crashing.
   - Verify `/v1/intelligence/chat/report-pdf` and `/v1/intelligence/chat/report-email` are stable.
   - Verify email report delivery does not return `sent` when provider delivery failed.

7. Agentic action layer.
   - Verify `/v1/agents/actions/plan` and `/v1/agents/actions/execute` are mounted and authenticated.
   - Safe actions may execute: email report to user, create task, record field update, parse field message, integration readiness check, evidence collection plan.
   - Risky actions must require approval: controller actions, customer communications, physical execution, financial/payment changes.
   - Execution results must be auditable and should include action id, type, status, tenant/workspace, timestamp, and result.

8. Controller-agnostic gateway.
   - Verify `universal_controller` is accepted end-to-end by connector catalog, connection creation, uploads, mapping, data, jobs, and controller readiness.
   - Verify `/v1/controllers/universal/data-contract` returns normalized controller object contract.
   - Verify `/v1/controllers/customer-connect` supports `wiseconn`, `talgil`, and `universal_controller`.
   - Verify `/v1/controllers/execution-readiness` includes native providers and universal controller connections.
   - Verify `/v1/controllers/execution/prepare` never physically executes unless all hard gates pass.

9. Industrial controls safety.
   - Physical execution must default to `dry_run=true` and `approval_required`.
   - Live physical execution is allowed only for provider-specific verified paths.
   - Current safe rule: only WiseConn `schedule_irrigation` may be promoted to provider write, and only if:
     - `provider=wiseconn`
     - `command=schedule_irrigation`
     - live write readiness is verified
     - `dry_run=false`
     - `approval_confirmed=true`
     - `zone_id`, `start_time`, and `duration_minutes` exist
     - metadata includes `customer_authorized=true`, `mapping_confirmed=true`, `write_scope_verified=true`, `water_budget_checked=true`, and `safety_window_checked=true`
   - Talgil and universal controller paths must remain approval packets until a provider-specific write contract is implemented and verified.

10. Connector hub and evidence ingestion.
   - Verify CSV/JSON/TXT upload parsing is stable.
   - PDF support must be honest: limited text extraction unless a real PDF parser is implemented.
   - Verify mapping suggestions and saved mappings work.
   - Verify evidence records are created with citations and tenant boundaries.
   - Verify upload file storage does not break in Render ephemeral filesystem; if durable storage is not configured, surface that limitation honestly.

11. Billing/pricing backend.
   - Verify product plans, pricing, billing status, checkout, portal session, and plan gating are coherent.
   - Confirm plan ids match frontend plan ids.
   - Confirm Stripe/env-missing states are truthful and do not crash.
   - Confirm free plan still works without Stripe.

## Pricing page redesign

The current pricing screen is crowded and visually inconsistent. It has too much text inside narrow cards, uneven card height, weak hierarchy, and too many competing CTAs. Redesign it in a clean Figma/Synthesia-style structure:

### Layout
- Hero section:
  - Left-aligned or centered eyebrow: `AGRO-AI Pricing`
  - Strong headline: `Choose the operating layer for your farm intelligence.`
  - Short subcopy, max two lines.
  - Monthly/Annual segmented control with annual discount note.
- Plan cards:
  - Use 4 primary cards max in the first row if possible. If keeping 5 plans, make layout responsive and horizontal-scroll on smaller screens.
  - Highlight `Professional` or `Team` as `Most popular` depending product strategy.
  - Cards should have consistent height, compact bullets, and a clear CTA.
  - Do not put long paragraphs in cards.
- Comparison table below:
  - Sticky-ish plan header on desktop if easy.
  - Group rows by category: Workspace, AI & Reports, Controller & Field Ops, Compliance, Integrations, Support.
  - Use icons/checkmarks, not long text in every cell.
- Services/add-ons section:
  - Onboarding & rollout
  - Custom integrations
  - Enterprise security review
- FAQ section:
  - Short, clean accordion or grid.

### Suggested pricing copy
- Free — `$0/month`: explore workspace, import limited files, sample reports.
- Professional — `$299/month`: one commercial workspace, AGRO-AI reports, evidence imports, operator tasks, email report delivery.
- Team — `$799/month`: multiple users/workspaces, controller readiness, field ops, compliance reporting, shared audit trails.
- Network — `$1,500/month`: multi-site/network operations, advanced integrations, controller gateway, customer/account reporting.
- Enterprise — `Contact sales`: custom controller/API integration, security review, dedicated rollout, SSO/SAML, custom SLAs.

### Visual system
- Use AGRO-AI dark green, soft off-white backgrounds, subtle borders, rounded 16–24px cards, restrained shadows, high whitespace.
- Avoid dense side-by-side tiny text.
- Use a narrow max-width container and table that feels premium.
- Mobile should stack cards cleanly.
- Keep CTA labels short: `Start free`, `Upgrade`, `Talk to sales`.

## Acceptance tests

Backend:
- `GET /v1/health` returns 200.
- `GET /v1/runtime/ai-status` returns 200 and no secrets.
- `GET /v1/connectors/catalog` returns 200 and includes `universal_controller`.
- Authenticated `POST /v1/connectors/connections` with provider `universal_controller` returns 201/200.
- Authenticated upload to that connection returns parsed data/evidence/job payload.
- `GET /v1/controllers/universal/data-contract` returns 200.
- `GET /v1/controllers/environments` returns WiseConn, Talgil, and Universal Controller Gateway.
- Authenticated `GET /v1/controllers/execution-readiness` returns readiness cards and hard-gate requirements.
- `POST /v1/controllers/execution/prepare` with `dry_run=true` returns `approval_required` and never executes.
- `POST /v1/controllers/execution/prepare` for Talgil or Universal Controller returns approval packet, not provider write.
- `POST /v1/intelligence/chat/report-pdf` returns an application/pdf response.
- `POST /v1/intelligence/chat/report-email` returns truthful delivery status.
- `POST /v1/agents/actions/plan` returns action cards.
- `POST /v1/agents/actions/execute` executes safe actions and approval-gates risky actions.

Frontend:
- TypeScript build passes.
- Pricing page has no text overflow at 1440px, 1024px, 768px, and mobile widths.
- Connector hub shows Universal Controller / Custom Irrigation System.
- Ask AGRO-AI action cards render and safe actions can be triggered.
- Controller readiness UI can call data contract and readiness endpoints.

## Definition of done

- No fake integration claims.
- No raw secrets in API responses.
- No unscoped tenant data exposure.
- No physical execution without provider-specific adapter + hard gates.
- PDF/email/action/report workflows work end-to-end.
- Pricing page looks enterprise-grade, clean, and not text-overflowing.
- All changed routes are manually smoke-tested against local backend or documented with curl commands.
