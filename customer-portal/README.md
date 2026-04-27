# AGRO-AI Portal v2

Production-oriented multi-tenant enterprise irrigation intelligence workspace.

## Architecture

```text
customer-portal/js/
  app.js                      # Bootstrap, event bus, auth guards, route orchestration
  apiClient.js                # Existing live API client (preserved)
  v2/
    auth/
      authService.js          # login/logout/reset scaffolds + session restore
      sessionService.js       # persisted session + expiry checks
      rbac.js                 # role-to-permission mapping
    routes/
      router.js               # route registry + route normalization
    state/
      store.js                # tenant/app state + seeded operational data
    services/
      auditService.js         # audit event writer
      integrationSetupService.js # provider setup workflow state machine
      intelligenceOpsService.js  # queue/timeline filters
    components/
      shell.js                # enterprise shell layout + selectors/header
    views/
      loginView.js            # login/forgot/reset views
      appViews.js             # command center, farms, intelligence, verification, reports, integrations, settings, audit
    data/
      demoTenant.js           # demo organization/farms/zones/recommendations/logs
```

## Product capabilities implemented

- Enterprise authentication scaffold (email/password, remember me, forgot/reset scaffolds, logout, session expiry handling).
- Multi-tenant model and seeded relationships: Organization → Farm → Field → Zone → Recommendation → Verification Log.
- Role-aware UI guardrails for `owner`, `admin`, `farm_manager`, `operator`, `advisor`, `viewer`.
- Provider setup workflow with 5-step onboarding and connection states (`connected`, `syncing`, `error`, `disconnected`).
- Farm Explorer with table-first hierarchy and zone operational status.
- Intelligence Operations Center with queue, filters, detail pane, and recommendation timeline.
- Verification chain with stage progression and manual verification submission.
- Embedded isolated Demo Organization and “Launch Demo Environment” action.
- Reporting center with weekly/monthly/quarterly views and PDF/CSV export scaffolds.
- Enterprise shell including organization/farm selectors, notifications, profile, and audit logs.

## API compatibility

Existing live `apiClient` contract is preserved. The v2 app scaffolds enterprise workflows without breaking current intelligence endpoints.

## Run locally

```bash
cd customer-portal
python -m http.server 4173
```

Open `http://localhost:4173`.
