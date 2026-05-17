import { filteredRecommendations, progressStatus, timelineForRecommendation } from "../services/intelligenceOpsService.js";

const fmt = (v) => new Date(v).toLocaleString();

export function commandCenterView(state) {
  const farm = state.app.farms.find((f) => f.id === state.app.farmId);
  const zone = state.app.zones.find((z) => z.id === state.app.zoneId) || state.app.zones[0];
  const rec = state.app.recommendations.find((r) => r.id === state.app.selectedRecommendationId) || state.app.recommendations[0];
  return `<section class="grid two-col">
    <article class="card">
      <h2>Operational Command Center</h2>
      <table class="data-table">
        <tr><th>Organization</th><td>${state.app.organizations.find((o) => o.id === state.app.organizationId)?.name}</td></tr>
        <tr><th>Farm</th><td>${farm?.name}</td></tr>
        <tr><th>Zone</th><td>${zone?.name}</td></tr>
        <tr><th>Provider</th><td>${zone?.provider}</td></tr>
        <tr><th>Today decision</th><td>${rec.recommendation}</td></tr>
        <tr><th>Confidence</th><td>${rec.confidence}%</td></tr>
        <tr><th>Data quality</th><td>${zone?.dataQuality}</td></tr>
      </table>
    </article>
    <article class="card">
      <h3>Verification backlog</h3>
      <p>${state.app.recommendations.filter((r) => r.status !== "verified").length} recommendations pending final verification.</p>
      <h3>Water usage status</h3>
      <p>${farm?.waterStatus}</p>
      <h3>Sensor status</h3>
      <p>${farm?.sensorStatus}</p>
    </article>
  </section>`;
}

export function farmsView(state) {
  return `<section class="card">
    <h2>Farm Explorer</h2>
    <table class="data-table">
      <thead><tr><th>Organization</th><th>Farm</th><th>Crop</th><th>Soil</th><th>Controller</th><th>Active recommendations</th><th>Verification backlog</th><th>Water usage</th><th>Sensor status</th></tr></thead>
      <tbody>
        ${state.app.farms
          .map((farm) => {
            const active = state.app.recommendations.filter((r) => r.farmId === farm.id && r.status !== "verified").length;
            const backlog = state.app.verificationLogs.filter((v) => {
              const rec = state.app.recommendations.find((r) => r.id === v.recommendationId);
              return rec?.farmId === farm.id && v.stage !== "verified";
            }).length;
            return `<tr>
              <td>${state.app.organizations.find((o) => o.id === farm.organizationId)?.name}</td>
              <td><button class="link-btn" data-action="set-farm" data-farm="${farm.id}">${farm.name}</button></td>
              <td>${farm.crop}</td>
              <td>${farm.soil}</td>
              <td>${farm.provider}</td>
              <td>${active}</td>
              <td>${backlog}</td>
              <td>${farm.waterStatus}</td>
              <td>${farm.sensorStatus}</td>
            </tr>`;
          })
          .join("")}
      </tbody>
    </table>
    <h3>Zones</h3>
    <table class="data-table">
      <thead><tr><th>Zone</th><th>Latest recommendation</th><th>Confidence</th><th>Data quality</th><th>Execution status</th><th>Observed outcome</th></tr></thead>
      <tbody>
        ${state.app.zones
          .map((zone) => {
            const rec = state.app.recommendations.find((r) => r.zoneId === zone.id);
            return `<tr>
              <td>${zone.name}</td>
              <td>${rec?.recommendation || "No recommendation"}</td>
              <td>${rec?.confidence || "-"}</td>
              <td>${zone.dataQuality}</td>
              <td>${zone.executionStatus}</td>
              <td>${zone.observedOutcome}</td>
            </tr>`;
          })
          .join("")}
      </tbody>
    </table>
  </section>`;
}

export function intelligenceView(state) {
  const rows = filteredRecommendations(state.app, state.filters);
  const selected = state.app.recommendations.find((r) => r.id === state.app.selectedRecommendationId) || rows[0];
  const timeline = selected ? timelineForRecommendation(state.app, selected.id) : [];

  return `<section class="grid two-col">
    <article class="card">
      <h2>Recommendations Queue</h2>
      ${filtersBar(state)}
      <table class="data-table">
        <thead><tr><th>Zone</th><th>Recommendation</th><th>Priority</th><th>Confidence</th><th>Status</th><th>Source</th><th>Created</th></tr></thead>
        <tbody>
          ${rows
            .map(
              (r) => `<tr>
                <td>${state.app.zones.find((z) => z.id === r.zoneId)?.name || r.zoneId}</td>
                <td><button class="link-btn" data-action="select-recommendation" data-rec="${r.id}">${r.recommendation}</button></td>
                <td><span class="pill ${r.priority}">${r.priority}</span></td>
                <td>${r.confidence}%</td>
                <td>${r.status}</td>
                <td>${r.source}</td>
                <td>${fmt(r.createdAt)}</td>
              </tr>`,
            )
            .join("")}
        </tbody>
      </table>
    </article>
    <article class="card">
      <h3>Decision Detail</h3>
      ${selected ? `<p><strong>Summary:</strong> ${selected.recommendation}</p>
      <p><strong>Confidence basis:</strong> ${selected.confidence}%</p>
      <p><strong>Key drivers:</strong> ${selected.keyDrivers.join(", ")}</p>
      <p><strong>Limitations:</strong> ${selected.limitations.join(", ") || "None"}</p>
      <p><strong>Verification plan:</strong> ${selected.verificationPlan}</p>
      <p><strong>Execution steps:</strong></p>
      <ul>${selected.executionSteps.map((s) => `<li>${s}</li>`).join("")}</ul>` : "<p>No recommendation selected.</p>"}
      <h3>Recommendation Timeline</h3>
      <ul class="timeline">${timeline.map((t) => `<li><strong>${t.stage}</strong> • ${fmt(t.at)} • ${t.by}<br/>${t.note}</li>`).join("") || "<li>No timeline events.</li>"}</ul>
    </article>
  </section>`;
}

function filtersBar(state) {
  return `<div class="filters">
    <label>Farm<select data-filter="farm"><option value="all">All</option>${state.app.farms.map((f) => `<option value="${f.id}" ${state.filters.farm === f.id ? "selected" : ""}>${f.name}</option>`).join("")}</select></label>
    <label>Zone<select data-filter="zone"><option value="all">All</option>${state.app.zones.map((z) => `<option value="${z.id}" ${state.filters.zone === z.id ? "selected" : ""}>${z.name}</option>`).join("")}</select></label>
    <label>Provider<select data-filter="provider"><option value="all">All</option><option value="wiseconn" ${state.filters.provider === "wiseconn" ? "selected" : ""}>WiseConn</option><option value="talgil" ${state.filters.provider === "talgil" ? "selected" : ""}>Talgil</option></select></label>
    <label>Status<select data-filter="status"><option value="all">All</option><option>recommended</option><option>scheduled</option><option>applied</option><option>observed</option><option>verified</option></select></label>
  </div>`;
}

export function verificationView(state) {
  const selected = state.app.recommendations.find((r) => r.id === state.app.selectedRecommendationId) || state.app.recommendations[0];
  return `<section class="grid two-col">
    <article class="card">
      <h2>Execution Proof Chain</h2>
      <div class="status-flow">${progressStatus(selected.status).map((s) => `<div class="step ${s.reached ? "done" : ""}">${s.status}</div>`).join("")}</div>
      <table class="data-table">
        <thead><tr><th>Stage</th><th>Who executed</th><th>When executed</th><th>What changed</th><th>Outcome observed</th></tr></thead>
        <tbody>${state.app.verificationLogs.filter((v) => v.recommendationId === selected.id).map((v) => `<tr><td>${v.stage}</td><td>${v.by}</td><td>${fmt(v.at)}</td><td>${v.changed}</td><td>${v.outcome}</td></tr>`).join("")}</tbody>
      </table>
    </article>
    <article class="card">
      <h3>Manual verification submission</h3>
      <form data-form="verification" class="form-grid">
        <label>Stage<select name="stage"><option>scheduled</option><option>applied</option><option>observed</option><option>verified</option></select></label>
        <label>Operator note<textarea name="note" required placeholder="Describe what changed in field operations"></textarea></label>
        <label>Observed outcome<input name="outcome" required placeholder="e.g., moisture trend recovered" /></label>
        <button class="btn primary" type="submit">Submit verification event</button>
      </form>
    </article>
  </section>`;
}

export function integrationsView(state) {
  const setup = state.app.integrationsSetup;
  return `<section class="grid two-col">
    <article class="card">
      <h2>Integrations Setup</h2>
      <p>Step ${setup.step} of 5</p>
      <ol class="steps">
        <li class="${setup.step >= 1 ? "active" : ""}">Select provider</li>
        <li class="${setup.step >= 2 ? "active" : ""}">Authenticate provider connection</li>
        <li class="${setup.step >= 3 ? "active" : ""}">Sync farms/controllers</li>
        <li class="${setup.step >= 4 ? "active" : ""}">Select active zones</li>
        <li class="${setup.step >= 5 ? "active" : ""}">Activate AGRO-AI intelligence</li>
      </ol>
      <label>Provider<select data-action="provider-select"><option value="wiseconn" ${setup.provider === "wiseconn" ? "selected" : ""}>WiseConn</option><option value="talgil" ${setup.provider === "talgil" ? "selected" : ""}>Talgil</option></select></label>
      <label>Connection state<select data-action="provider-state"><option>connected</option><option>syncing</option><option>error</option><option>disconnected</option></select></label>
      <div class="actions-row"><button class="btn" data-action="integration-prev">Previous</button><button class="btn primary" data-action="integration-next">Next step</button></div>
    </article>
    <article class="card">
      <h3>Provider health</h3>
      <table class="data-table">
        <thead><tr><th>Provider</th><th>Connection health</th><th>Last sync</th><th>Farms synced</th><th>Zones discovered</th><th>Sensor count</th><th>Status</th></tr></thead>
        <tbody>${state.app.providerConnections.map((p) => `<tr><td>${p.provider}</td><td>${p.health}</td><td>${fmt(p.lastSync)}</td><td>${p.farmsSynced}</td><td>${p.zonesDiscovered}</td><td>${p.sensorCount}</td><td>${p.status}</td></tr>`).join("")}</tbody>
      </table>
    </article>
  </section>`;
}

export function reportsView(state) {
  return `<section class="card">
    <h2>Reporting Center</h2>
    <div class="filters"><label>View<select><option>weekly</option><option>monthly</option><option>quarterly</option></select></label></div>
    <table class="data-table">
      <thead><tr><th>Report</th><th>Cadence</th><th>Updated</th><th>Exports</th></tr></thead>
      <tbody>${state.app.reports.map((r) => `<tr><td>${r.name}</td><td>${r.cadence}</td><td>${fmt(r.updatedAt)}</td><td><button class="btn small">PDF</button> <button class="btn small">CSV</button></td></tr>`).join("")}</tbody>
    </table>
  </section>`;
}

export function settingsView(state) {
  return `<section class="card">
    <h2>Tenant settings</h2>
    <p>Role-based access control active for role: <strong>${state.session.user.role}</strong>.</p>
    <p>Membership count: ${state.app.memberships.length}</p>
    <p>Session expiry: ${fmt(state.session.expiresAt)}</p>
  </section>`;
}

export function auditLogsView(state) {
  return `<section class="card">
    <h2>Audit Trail</h2>
    <table class="data-table">
      <thead><tr><th>Action</th><th>Actor</th><th>Timestamp</th><th>Metadata</th></tr></thead>
      <tbody>${state.app.auditLogs.map((log) => `<tr><td>${log.action}</td><td>${log.actor}</td><td>${fmt(log.at)}</td><td>${log.metadata}</td></tr>`).join("")}</tbody>
    </table>
  </section>`;
}
