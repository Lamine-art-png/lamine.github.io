import { ApiClient } from "./apiClient.js";
import { acceptedWorkbenchFields, sampleDataPackage, workbenchOutputSchema } from "./demoData.js";
import { launchDemoSession, notify, returnToEntry, setActiveView, setDemoRuntime, setLoginError, startLoginScaffold, state, subscribe, SESSION_MODES } from "./state.js";
import { loadLiveSnapshot, generateWiseConnRecommendation } from "./services/liveData.js";
import { addObservation, attachUploadArtifact, completeAiAnalysis, generateDemoRecommendation, generateDemoReport, markApplied, markBackendUnavailable, nextStep, prepareBackendSetupRequest, resetDemo, runAiAnalysis, scheduleRecommendation, selectFarm, selectIntakeMode, selectZone, startGuidedDemo, switchScenario, switchWorkspaceScenario, toCsv, verifyOutcome } from "./services/demoRuntime.js";
import { renderEntryView } from "./views/entryView.js";
import { renderShell } from "./views/shellView.js";
import { renderCommandCenter } from "./views/commandCenterView.js";
import { renderFarmExplorer } from "./views/farmExplorerView.js";
import { renderIntelligence } from "./views/intelligenceView.js";
import { renderVerification } from "./views/verificationView.js";
import { renderReports } from "./views/reportsView.js";
import { renderIntegrations } from "./views/integrationsView.js";
import { renderAuditLog } from "./views/auditLogView.js";
import { renderSettings } from "./views/settingsView.js";
import { renderCompliance } from "./views/complianceView.js";

const api = new ApiClient();
const root = document.getElementById("app");
let liveSnapshotLoaded = false;

function updateDemo(runtime, message = "Command Center updated") {
  runtime.toast = message;
  setDemoRuntime(runtime);
}

function downloadCsv(snapshot) {
  if (!snapshot) {
    const rt = generateDemoReport(state.demoRuntime);
    setDemoRuntime(rt);
    snapshot = rt.reportSnapshots?.[0];
  }
  if (!snapshot) {
    openModal("Report export unavailable", "<p>A report snapshot is required before CSV export. Preview the report or run intelligence analysis first.</p>");
    return;
  }
  const blob = new Blob([toCsv(snapshot)], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${snapshot.type.replaceAll(" ", "-").toLowerCase()}-${snapshot.id}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadText(filename, content, type = "text/plain") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadSamplePackage() {
  sampleDataPackage.forEach((file, index) => {
    window.setTimeout(() => downloadText(file.filename, file.content, file.mime), index * 120);
  });
}

function closeModal() {
  document.querySelector(".portal-modal-backdrop")?.remove();
}

function openModal(title, body, footer = "") {
  closeModal();
  const wrapper = document.createElement("div");
  wrapper.className = "portal-modal-backdrop";
  wrapper.innerHTML = `<section class="portal-modal" role="dialog" aria-modal="true" aria-label="${title}">
    <div class="modal-head"><h2>${title}</h2><button class="button ghost" data-modal-close type="button">Close</button></div>
    <div class="modal-body">${body}</div>
    ${footer ? `<div class="modal-footer">${footer}</div>` : ""}
  </section>`;
  document.body.appendChild(wrapper);
  wrapper.querySelectorAll("[data-modal-close]").forEach((button) => button.addEventListener("click", closeModal));
  wrapper.addEventListener("click", (event) => {
    if (event.target === wrapper) closeModal();
  });
  return wrapper;
}

function fieldsMarkup(fields = acceptedWorkbenchFields) {
  return `<div class="schema-list">${Object.entries(fields)
    .map(([name, values]) => `<article><h3>${name}</h3><p>${values.join(", ")}</p></article>`)
    .join("")}</div>`;
}

async function showAcceptedFields() {
  const schema = await api.getWorkbenchSchema();
  const fields = schema.ok && schema.data?.expected_fields ? schema.data.expected_fields : acceptedWorkbenchFields;
  openModal("Accepted fields", fieldsMarkup(fields));
}

async function showAnalysisSchema() {
  const response = await api.getWorkbenchSchema();
  const schema = response.ok && response.data?.output_schema ? response.data.output_schema : workbenchOutputSchema;
  openModal(
    "Analysis schema",
    `<div class="schema-list">${schema.map((item) => `<article><h3>${item}</h3><p>Returned by the Workbench Engine for portal rendering and report generation.</p></article>`).join("")}</div>`
  );
}

function setupBrief(provider = "WiseConn") {
  return [
    "Backend setup request",
    "",
    `Provider: ${provider}`,
    "Workspace: Alpha Vineyard",
    "Credential vault requirement: production credentials must be encrypted and stored server-side",
    "Tenant provisioning requirement: create a tenant-scoped Workbench session and data namespace",
    "Farm and block mapping requirement: map provider IDs to AGRO-AI farm, block, crop, soil, and irrigation entities",
    "Security note: credentials must be stored server-side, not in browser storage",
    "Operational next step: provision provider access, select production targets, then enable live source analysis",
  ].join("\n");
}

async function copyTextToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_error) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    return copied;
  }
}

function openBackendSetupModal(provider = "WiseConn") {
  const brief = setupBrief(provider);
  const modal = openModal(
    "Backend setup request",
    `<dl class="setup-brief">
      <div><dt>Provider</dt><dd>${provider}</dd></div>
      <div><dt>Workspace</dt><dd>Alpha Vineyard</dd></div>
      <div><dt>Credential vault requirement</dt><dd>Production credentials must be encrypted and stored server-side.</dd></div>
      <div><dt>Tenant provisioning requirement</dt><dd>Create a tenant-scoped Workbench session and data namespace.</dd></div>
      <div><dt>Farm and block mapping requirement</dt><dd>Map provider IDs to AGRO-AI farm, block, crop, soil, and irrigation entities.</dd></div>
      <div><dt>Security note</dt><dd>Credentials must be stored server-side, not in browser storage.</dd></div>
      <div><dt>Operational next step</dt><dd>Provision provider access, select production targets, then enable live source analysis.</dd></div>
    </dl>`,
    `<button class="button secondary" data-copy-setup type="button">Copy brief</button><button class="button primary" data-download-setup type="button">Download brief</button><button class="button ghost" data-modal-close type="button">Close</button>`
  );
  modal.querySelector("[data-copy-setup]")?.addEventListener("click", async () => {
    const copied = await copyTextToClipboard(brief);
    if (copied) {
    updateDemo(state.demoRuntime, "Setup brief copied.");
    } else {
      downloadText(`${provider.toLowerCase()}-backend-setup-brief.txt`, brief);
      updateDemo(state.demoRuntime, "Clipboard unavailable. Setup brief downloaded.");
    }
  });
  modal.querySelector("[data-download-setup]")?.addEventListener("click", () => {
    downloadText(`${provider.toLowerCase()}-backend-setup-brief.txt`, brief);
    updateDemo(state.demoRuntime, "Setup brief downloaded.");
  });
}

function collectOverrides(form) {
  const data = new FormData(form);
  const overrides = {};

  for (const [key, value] of data.entries()) {
    const normalized = String(value).trim();
    if (!normalized) continue;
    overrides[key] = ["eto", "rain_forecast"].includes(key) ? Number(normalized) : normalized;
  }

  return overrides;
}

function renderActiveView() {
  if (state.activeView === "farm-explorer") return renderFarmExplorer(state);
  if (state.activeView === "intelligence") return renderIntelligence(state);
  if (state.activeView === "verification") return renderVerification(state);
  if (state.activeView === "reports") return renderReports(state);
  if (state.activeView === "integrations") return renderIntegrations(state);
  if (state.activeView === "audit-log") return renderAuditLog(state);
  if (state.activeView === "settings") return renderSettings(state);
  if (state.activeView === "compliance" && window.AGROAI_PORTAL_CONFIG?.CALIFORNIA_COMPLIANCE_PACK_ENABLED) return renderCompliance(state);
  return renderCommandCenter(state);
}

function render() {
  if (state.session.mode === SESSION_MODES.ENTRY) {
    root.innerHTML = renderEntryView(state);
    bindEntryEvents();
    return;
  }

  root.innerHTML = renderShell(state, renderActiveView());
  bindShellEvents();
}

function bindEntryEvents() {
  document.getElementById("launch-demo")?.addEventListener("click", () => {
    launchDemoSession();
  });

  document.getElementById("login-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    setLoginError("We could not verify those credentials. Check your email and password.");
  });

  document.getElementById("live-status-preview")?.addEventListener("click", async () => {
    startLoginScaffold(document.getElementById("login-email")?.value || "");
    if (!liveSnapshotLoaded) {
      await loadLiveSnapshot(api, state);
      liveSnapshotLoaded = true;
      notify();
    }
  });
}

async function animateAnalysis() {
  if (!state.demoRuntime.intakeMode) {
    updateDemo(state.demoRuntime, "Select a source before running intelligence analysis.");
    return;
  }
  const rt = runAiAnalysis(state.demoRuntime);
  setDemoRuntime(rt);
  for (let i = 0; i < rt.analysis.steps.length; i += 1) {
    await new Promise((r) => setTimeout(r, 450));
    rt.analysis.steps[i] = { ...rt.analysis.steps[i], status: "running", statusLabel: "Active", detail: "Processing selected source records" };
    setDemoRuntime(rt);
    await new Promise((r) => setTimeout(r, 300));
    rt.analysis.steps[i] = { ...rt.analysis.steps[i], status: "complete", statusLabel: "Complete", detail: "Complete" };
    setDemoRuntime(rt);
  }
  let backend;
  try {
    if (rt.intakeMode === "connected") {
      backend = await api.analyzeLiveWorkbench({
        source: "wiseconn",
        entity_id: "162803",
        crop_type: "Cabernet Sauvignon",
        soil_type: "loam",
        irrigation_method: "drip",
        weather_context: {
          eto_mm: 6.4,
          precipitation_forecast_mm: 0,
        },
        field_observations: ["Mild afternoon stress"],
        language: "en",
        user_role: "operations_manager",
      });
    } else {
      if (rt.intakeMode === "sample" && !rt.analysis.sampleLoaded) {
        const sample = await api.createSampleWorkbenchSession();
        if (sample.ok) {
          rt.analysis.sessionId = sample.data?.session?.session_id || sample.data?.session_id || rt.analysis.sessionId;
          rt.analysis.artifacts = sample.data?.artifacts || [];
          rt.analysis.sampleLoaded = true;
        }
      }
      if (rt.intakeMode === "upload" && !rt.analysis.artifacts?.length) {
        updateDemo(markBackendUnavailable(rt, "Upload records before running production ingestion. Representative-data analysis remains available."), "Upload records before running production ingestion.");
        return;
      }
      if (!rt.analysis.sessionId && rt.intakeMode !== "sample") {
        const created = await api.createWorkbenchSession({ mode: "uploaded", workspace_name: "Alpha Vineyard · Water Command Center" });
        if (created.ok) rt.analysis.sessionId = created.data?.session_id || created.data?.session?.session_id || "";
      }
      if (rt.analysis.sessionId) {
        // The backend WorkbenchAnalysisRequest.mode is a strict Literal
        // ("demo" | "live" | "uploaded"); the engine branches on artifacts,
        // not the mode string, so representative (sample) and uploaded
        // sessions both analyze correctly as "uploaded".
        backend = await api.analyzeWorkbenchSession(rt.analysis.sessionId, { session_id: rt.analysis.sessionId, mode: "uploaded" });
      }
    }
  } catch (_error) {
    backend = { ok: false, error: "Backend intelligence unavailable. Representative-data analysis remains available." };
  }
  if (backend?.ok) {
    rt.analysis.backendResult = backend.data;
    updateDemo(completeAiAnalysis(rt), "Analysis complete. Decision ready.");
  } else {
    const message = "Backend intelligence unavailable. Representative-data analysis remains available.";
    if (rt.intakeMode === "sample") {
      rt.analysis.backendError = message;
      updateDemo(completeAiAnalysis(rt), message);
    } else {
      updateDemo(markBackendUnavailable(rt, message), message);
    }
  }
}


async function handleWorkbenchUpload(file) {
  const rt = selectIntakeMode(state.demoRuntime, "upload");
  if (!rt.analysis.sessionId) {
    const created = await api.createWorkbenchSession({ mode: "uploaded", workspace_name: "Alpha Vineyard · Water Command Center" });
    if (created.ok) rt.analysis.sessionId = created.data?.session_id || created.data?.session?.session_id || "";
  }
  if (!rt.analysis.sessionId) {
    updateDemo(markBackendUnavailable(rt, "Backend upload endpoint required for production ingestion. Representative-data analysis remains available."), "Backend upload endpoint required for production ingestion.");
    updateSourceDrawerStatus(file, "Backend upload endpoint required. Representative-data analysis remains available.");
    return;
  }
  const up = await api.uploadWorkbenchFile(rt.analysis.sessionId, file);
  if (up.ok) {
    updateDemo(attachUploadArtifact(rt, up.data || { filename: file.name, status: "Accepted for analysis" }, file), `${file.name} accepted for analysis.`);
    updateSourceDrawerStatus(file, up.data?.parse_status || "Accepted for analysis", up.data);
  } else {
    updateDemo(markBackendUnavailable(rt, up.error || "Backend upload endpoint required for production ingestion. Representative-data analysis remains available."), "Backend upload endpoint required for production ingestion.");
    updateSourceDrawerStatus(file, "Backend upload endpoint required. Representative-data analysis remains available.");
  }
}

function detectSourceType(filename = "") {
  const ext = filename.split(".").pop()?.toLowerCase();
  const map = { csv: "Tabular records (CSV)", xlsx: "Spreadsheet export (Excel)", xls: "Spreadsheet export (Excel)", json: "Structured records (JSON)", txt: "Field notes (TXT)" };
  return map[ext] || "Detected on upload";
}

function updateSourceDrawerStatus(file, parseStatus, data = null) {
  const panel = document.getElementById("drawer-upload-status");
  if (!panel) return;
  const rows = data?.rows_detected ?? data?.rows ?? "Detected on parse";
  const cols = data?.columns_detected;
  const fields = Array.isArray(cols) ? `${cols.length} (${cols.slice(0, 6).join(", ")}${cols.length > 6 ? "…" : ""})` : data?.fields_mapped ?? data?.fields ?? "Mapped on parse";
  const warnings = Array.isArray(data?.warnings) && data.warnings.length ? data.warnings.join("; ") : "None";
  panel.innerHTML = `<dl class="drawer-def">
      <div><dt>Uploaded file</dt><dd>${escapeHtmlSafe(file?.name || "—")}</dd></div>
      <div><dt>Detected source type</dt><dd>${escapeHtmlSafe(detectSourceType(file?.name))}</dd></div>
      <div><dt>Parse status</dt><dd>${escapeHtmlSafe(parseStatus)}</dd></div>
      <div><dt>Rows detected</dt><dd>${escapeHtmlSafe(String(rows))}</dd></div>
      <div><dt>Fields mapped</dt><dd>${escapeHtmlSafe(String(fields))}</dd></div>
      <div><dt>Warnings</dt><dd>${escapeHtmlSafe(warnings)}</dd></div>
    </dl>
    <div class="drawer-actions"><button class="button ghost compact" id="drawer-remove-file" type="button">Remove file</button><button class="button primary compact" id="drawer-analyze-upload" type="button">Analyze uploaded records</button></div>`;
  panel.querySelector("#drawer-remove-file")?.addEventListener("click", () => {
    panel.innerHTML = '<p class="muted">No file selected.</p>';
  });
  panel.querySelector("#drawer-analyze-upload")?.addEventListener("click", async () => {
    closeSourceDrawer();
    await animateAnalysis();
  });
}

function escapeHtmlSafe(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function closeSourceDrawer() {
  document.querySelector(".source-drawer-backdrop")?.remove();
}

const SOURCE_DRAWER_TABS = {
  connected: `<div class="drawer-tabpanel" data-panel="connected">
      <article class="drawer-source-row"><div><h4>WiseConn</h4><span class="badge success">Live-ready</span></div><p>Controller environment prepared for credential-backed onboarding.</p><button class="button secondary compact" data-action="request-backend-setup" data-integration="WiseConn" type="button">Connect or configure</button></article>
      <article class="drawer-source-row"><div><h4>Talgil</h4><span class="badge success">Runtime reachable</span></div><p>Runtime is reachable; production targets are not yet selected.</p><button class="button secondary compact" data-action="request-backend-setup" data-integration="Talgil" type="button">Select production targets</button></article>
      <article class="drawer-source-row"><div><h4>Generic controller</h4><span class="badge neutral">Available</span></div><p>Connector setup can be requested for other controller environments.</p><button class="button secondary compact" data-action="request-backend-setup" data-integration="Generic controller" type="button">Request connector setup</button></article>
    </div>`,
  upload: `<div class="drawer-tabpanel" data-panel="upload">
      <p class="muted">Accepted: CSV, Excel, JSON, TXT, spreadsheet exports, and field notes.</p>
      <label class="drawer-dropzone" id="drawer-dropzone"><input class="visually-hidden" id="drawer-upload-input" type="file" accept=".csv,.json,.txt,.xlsx,.xls,application/json,text/csv,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" /><strong>Drop a file or browse</strong><span>Records are processed through the Workbench upload route.</span></label>
      <div id="drawer-upload-status"><p class="muted">No file selected.</p></div>
    </div>`,
  api: `<div class="drawer-tabpanel" data-panel="api">
      <dl class="drawer-def">
        <div><dt>Ingestion endpoint</dt><dd><code>POST /v1/workbench/sessions/{session_id}/upload</code></dd></div>
        <div><dt>Authentication</dt><dd>Server-side credential vault required. Keys are never stored in the browser.</dd></div>
        <div><dt>Accepted payload categories</dt><dd>Controller events, weather, soil moisture, flow meter, field notes, crop profile, earth observation.</dd></div>
        <div><dt>Schema</dt><dd><button class="button ghost compact" data-action="view-accepted-fields" type="button">View accepted fields</button></dd></div>
      </dl>
      <button class="button primary compact" id="drawer-copy-api" type="button">Copy API setup brief</button>
    </div>`,
  partner: `<div class="drawer-tabpanel" data-panel="partner">
      <article class="drawer-source-row"><div><h4>Weather provider</h4><span class="badge neutral">Authorization required</span></div><p>Demand signals (ETo, rainfall) from a weather provider.</p></article>
      <article class="drawer-source-row"><div><h4>Earth observation layer</h4><span class="badge neutral">Authorization required</span></div><p>Canopy stress and vegetation indices as a representative layer.</p></article>
      <article class="drawer-source-row"><div><h4>Agronomic data feed</h4><span class="badge neutral">Authorization required</span></div><p>Third-party agronomic context for reconciliation.</p></article>
      <article class="drawer-source-row"><div><h4>Custom partner feed</h4><span class="badge neutral">Authorization required</span></div><p>Bring a custom partner signal into the decision pipeline.</p></article>
      <p class="muted">Partner feed authorization required for production use.</p>
    </div>`,
};

function openSourceDrawer() {
  closeSourceDrawer();
  const wrapper = document.createElement("div");
  wrapper.className = "source-drawer-backdrop";
  wrapper.innerHTML = `<aside class="source-drawer" role="dialog" aria-modal="true" aria-label="Connect irrigation data">
    <div class="drawer-head"><div><p class="eyebrow">Source intelligence</p><h2>Connect irrigation data</h2></div><button class="button ghost compact" data-drawer-close type="button">Close</button></div>
    <div class="drawer-tabs" role="tablist">
      <button class="drawer-tab active" data-tab="connected" type="button">Connected systems</button>
      <button class="drawer-tab" data-tab="upload" type="button">Upload records</button>
      <button class="drawer-tab" data-tab="api" type="button">API access</button>
      <button class="drawer-tab" data-tab="partner" type="button">Partner feeds</button>
    </div>
    <div class="drawer-body">${SOURCE_DRAWER_TABS.connected}</div>
  </aside>`;
  document.body.appendChild(wrapper);
  const body = wrapper.querySelector(".drawer-body");

  function bindBodyActions() {
    body.querySelectorAll("[data-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const action = button.dataset.action;
        if (action === "request-backend-setup") {
          const provider = button.dataset.integration || "WiseConn";
          updateDemo(prepareBackendSetupRequest(state.demoRuntime, provider), "Backend setup request prepared");
          closeSourceDrawer();
          openBackendSetupModal(provider);
        }
        if (action === "view-accepted-fields") showAcceptedFields();
      });
    });
    body.querySelector("#drawer-upload-input")?.addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      if (file) await handleWorkbenchUpload(file);
    });
    const dropzone = body.querySelector("#drawer-dropzone");
    if (dropzone) {
      ["dragover", "dragenter"].forEach((evt) => dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.add("dragging"); }));
      ["dragleave", "drop"].forEach((evt) => dropzone.addEventListener(evt, () => dropzone.classList.remove("dragging")));
      dropzone.addEventListener("drop", async (event) => {
        event.preventDefault();
        const file = event.dataTransfer?.files?.[0];
        if (file) await handleWorkbenchUpload(file);
      });
    }
    body.querySelector("#drawer-copy-api")?.addEventListener("click", async () => {
      const brief = setupBrief("API ingestion");
      const copied = await copyTextToClipboard(brief);
      updateDemo(state.demoRuntime, copied ? "API setup brief copied." : "Clipboard unavailable.");
    });
  }
  bindBodyActions();

  wrapper.querySelectorAll(".drawer-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      wrapper.querySelectorAll(".drawer-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      body.innerHTML = SOURCE_DRAWER_TABS[tab.dataset.tab] || "";
      bindBodyActions();
    });
  });
  wrapper.querySelector("[data-drawer-close]")?.addEventListener("click", closeSourceDrawer);
  wrapper.addEventListener("click", (event) => {
    if (event.target === wrapper) closeSourceDrawer();
  });
}

function openWorkspaceDetails() {
  const runtime = state.demoRuntime;
  openModal(
    "Workspace details",
    `<dl class="setup-brief">
      <div><dt>Workspace</dt><dd>${escapeHtmlSafe(runtime.activeFarm?.name || "Alpha Vineyard")} · Water Command Center</dd></div>
      <div><dt>Environment</dt><dd>Evaluation workspace</dd></div>
      <div><dt>Data provenance</dt><dd>Representative data — production targets not yet connected</dd></div>
      <div><dt>Active block</dt><dd>${escapeHtmlSafe(runtime.activeZone?.name || "Block A North")}</dd></div>
      <div><dt>Sources</dt><dd>Mixed sources (controller history, weather, soil, flow, observation, earth observation)</dd></div>
      <div><dt>Backend</dt><dd>Workbench intelligence routes used when available; representative-data analysis as fallback.</dd></div>
    </dl>`
  );
}

function bindShellEvents() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setActiveView(button.dataset.view));
  });

  document.getElementById("exit-session")?.addEventListener("click", () => {
    returnToEntry();
  });

  document.getElementById("live-recommendation-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const overrides = collectOverrides(event.currentTarget);
    await generateWiseConnRecommendation(api, state, overrides);
    notify();
  });

  document.getElementById("scenario-select")?.addEventListener("change", (event) => {
    updateDemo(switchScenario(state.demoRuntime, event.target.value), "Scenario updated");
  });
  document.getElementById("farm-select-runtime")?.addEventListener("change", (event) => {
    updateDemo(selectFarm(state.demoRuntime, event.target.value), "Farm selected");
  });
  document.getElementById("zone-select-runtime")?.addEventListener("change", (event) => {
    updateDemo(selectZone(state.demoRuntime, event.target.value), "Zone selected");
  });

  document.getElementById("workbench-upload-input")?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (file) await handleWorkbenchUpload(file);
  });

  document.getElementById("workspace-scenario-select")?.addEventListener("change", (event) => {
    updateDemo(switchWorkspaceScenario(state.demoRuntime, event.target.value), "Workspace scenario loaded");
  });

  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset.action;
      if (action === "reset-demo") updateDemo(resetDemo(), "Command Center reset");
      if (action === "start-guide") updateDemo(startGuidedDemo(state.demoRuntime), "Guided enterprise workflow started");
      if (action === "next-step") updateDemo(nextStep(state.demoRuntime), "Workflow advanced");
      if (action === "generate-demo-recommendation") updateDemo(generateDemoRecommendation(state.demoRuntime), "Recommendation generated");
      if (action === "use-connected-field" || action === "use-connected-source") updateDemo(selectIntakeMode(state.demoRuntime, "connected"), "Connected source selected");
      if (action === "choose-upload-records") {
        updateDemo(selectIntakeMode(state.demoRuntime, "upload"), "Upload records selected");
        window.setTimeout(() => document.getElementById("workbench-upload-input")?.click(), 0);
      }
      if (action === "use-upload-records") updateDemo(selectIntakeMode(state.demoRuntime, "upload"), "Uploaded source selected");
      if (action === "load-sample-data-package" || action === "load-pilot-package") updateDemo(selectIntakeMode(state.demoRuntime, "sample"), "Representative data selected");
      if (action === "download-sample-package") downloadSamplePackage();
      if (action === "view-accepted-fields") showAcceptedFields();
      if (action === "view-analysis-schema") showAnalysisSchema();
      if (action === "run-ai-analysis") await animateAnalysis();
      if (action === "schedule") updateDemo(scheduleRecommendation(state.demoRuntime), "Recommendation scheduled");
      if (action === "mark-applied") updateDemo(markApplied(state.demoRuntime), "Applied water confirmed");
      if (action === "add-observation") updateDemo(addObservation(state.demoRuntime), "Observation recorded");
      if (action === "verify") updateDemo(verifyOutcome(state.demoRuntime), "Outcome verified");
      if (action === "open-report") {
        updateDemo(generateDemoReport(state.demoRuntime), "Report preview generated");
        setActiveView("reports");
      }
      if (action === "preview-report") updateDemo(generateDemoReport(state.demoRuntime, button.dataset.reportType || "Irrigation Intelligence Report"), "Report preview generated");
      if (action === "print-report") window.print();
      if (action === "export-csv") downloadCsv(state.demoRuntime.reportSnapshots?.[0]);
      if (action === "live-execution-note") openModal("Execution capture", "<p>Execution capture requires backend execution endpoints. Verification chain and reconciliation are available in this workspace.</p>");
      if (action === "integration-note") openModal("Integration status", `<p>${button.dataset.message || "Runtime status details are shown in this card. Secure credential storage requires backend credential endpoints."}</p>`);
      if (action === "request-backend-setup") {
        const provider = button.dataset.integration || "WiseConn";
        updateDemo(prepareBackendSetupRequest(state.demoRuntime, provider), "Backend setup request prepared");
        openBackendSetupModal(provider);
      }
      if (action === "report-readiness") openModal("Report readiness", `<p>${button.dataset.message || "Report generation will activate when the required backend endpoint is available."}</p>`);
      if (action === "check-integrations") setActiveView("integrations");
      if (action === "open-source-drawer") openSourceDrawer();
      if (action === "workspace-details") openWorkspaceDetails();
    });
  });
}

// Close header overflow / user menus when clicking outside of them (registered once).
document.addEventListener("click", (event) => {
  document.querySelectorAll(".overflow-menu[open], .user-menu[open]").forEach((menu) => {
    if (!menu.contains(event.target)) menu.removeAttribute("open");
  });
});

subscribe(render);
render();
