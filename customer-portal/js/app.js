import { ApiClient } from "./apiClient.js";
import { acceptedWorkbenchFields, sampleDataPackage, workbenchOutputSchema } from "./demoData.js";
import { launchDemoSession, notify, returnToEntry, setActiveView, setDemoRuntime, setLoginError, startLoginScaffold, state, subscribe, SESSION_MODES } from "./state.js";
import { loadLiveSnapshot, generateWiseConnRecommendation } from "./services/liveData.js";
import { addObservation, completeAiAnalysis, generateDemoRecommendation, generateDemoReport, markApplied, nextStep, prepareBackendSetupRequest, resetDemo, runAiAnalysis, scheduleRecommendation, selectFarm, selectIntakeMode, selectZone, startGuidedDemo, switchScenario, toCsv, verifyOutcome } from "./services/demoRuntime.js";
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

const api = new ApiClient();
const root = document.getElementById("app");
let liveSnapshotLoaded = false;

function updateDemo(runtime, message = "Workspace updated") {
  runtime.toast = message;
  setDemoRuntime(runtime);
}

function downloadCsv(snapshot) {
  if (!snapshot) return;
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
    "Workspace: Alpha Vineyard",
    `Integration: ${provider}`,
    "Required backend endpoint: credential vault and tenant provisioning",
    "Required access: API key, provider account, farm/block mapping",
    "Security note: credentials must be stored server-side, not in browser storage",
    "Next action: send setup brief to AGRO-AI technical team",
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
      <div><dt>Workspace</dt><dd>Alpha Vineyard</dd></div>
      <div><dt>Integration</dt><dd>${provider}</dd></div>
      <div><dt>Required backend endpoint</dt><dd>Credential vault and tenant provisioning</dd></div>
      <div><dt>Required access</dt><dd>API key, provider account, farm/block mapping</dd></div>
      <div><dt>Security note</dt><dd>Credentials must be stored server-side, not in browser storage.</dd></div>
      <div><dt>Next action</dt><dd>Send setup brief to AGRO-AI technical team.</dd></div>
    </dl>`,
    `<button class="button secondary" data-copy-setup type="button">Copy setup brief</button><button class="button primary" data-download-setup type="button">Download setup brief</button><button class="button ghost" data-modal-close type="button">Close</button>`
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
    setLoginError("We could not verify those credentials. Check your email and password or open the evaluation workspace.");
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
  const rt = runAiAnalysis(state.demoRuntime);
  setDemoRuntime(rt);
  for (let i = 0; i < rt.analysis.steps.length; i += 1) {
    await new Promise((r) => setTimeout(r, 450));
    rt.analysis.steps[i] = { ...rt.analysis.steps[i], status: "running", statusLabel: "Running", detail: "Processing" };
    setDemoRuntime(rt);
    await new Promise((r) => setTimeout(r, 300));
    rt.analysis.steps[i] = { ...rt.analysis.steps[i], status: "complete", statusLabel: "Complete", detail: "Complete" };
    setDemoRuntime(rt);
  }
  let backend;
  if (rt.intakeMode === "connected") {
    backend = await api.analyzeLiveWorkbench({ source: "wiseconn", entity_id: "162803" });
  } else {
    if (rt.intakeMode === "sample" && !rt.analysis.sampleLoaded) {
      const sample = await api.createSampleWorkbenchSession();
      if (sample.ok) {
        rt.analysis.sessionId = sample.data.session.session_id;
        rt.analysis.artifacts = sample.data.artifacts || [];
        rt.analysis.sampleLoaded = true;
      }
    }
    if (!rt.analysis.sessionId) {
      const created = await api.createWorkbenchSession({ mode: "uploaded", workspace_name: "Alpha Vineyard · Water Command Center" });
      if (created.ok) rt.analysis.sessionId = created.data.session_id;
    }
    if (rt.analysis.sessionId) {
      backend = await api.analyzeWorkbenchSession(rt.analysis.sessionId, { session_id: rt.analysis.sessionId, mode: "uploaded" });
    }
  }
  if (backend?.ok) {
    rt.analysis.backendResult = backend.data;
    updateDemo(completeAiAnalysis(rt), "Analysis complete. Recommendation ready.");
  } else {
    rt.analysis.running = false;
    rt.analysis.status = "idle";
    rt.analysis.statusLabel = "Backend intelligence unavailable. Sample package remains available for evaluation.";
    updateDemo(rt, "Backend intelligence unavailable. Sample package remains available for evaluation.");
  }
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
    if (!file) return;
    const rt = selectIntakeMode(state.demoRuntime, "upload");
    if (!rt.analysis.sessionId) {
      const created = await api.createWorkbenchSession({ mode: "uploaded", workspace_name: "Alpha Vineyard · Water Command Center" });
      if (created.ok) rt.analysis.sessionId = created.data.session_id;
    }
    const up = await api.uploadWorkbenchFile(rt.analysis.sessionId, file);
    if (up.ok) {
      rt.analysis.artifacts = [...(rt.analysis.artifacts || []), up.data];
      updateDemo(rt, `Uploaded ${file.name}`);
    } else {
      updateDemo(rt, up.error || "Upload failed");
    }
  });

  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.action;
      if (action === "reset-demo") updateDemo(resetDemo(), "Evaluation workspace reset");
      if (action === "start-guide") updateDemo(startGuidedDemo(state.demoRuntime), "Guided evaluation started");
      if (action === "next-step") updateDemo(nextStep(state.demoRuntime), "Evaluation advanced");
      if (action === "generate-demo-recommendation") updateDemo(generateDemoRecommendation(state.demoRuntime), "Recommendation generated");
      if (action === "use-connected-field") updateDemo(selectIntakeMode(state.demoRuntime, "connected"), "Connected field context selected");
      if (action === "use-upload-records") updateDemo(selectIntakeMode(state.demoRuntime, "upload"), "Upload records selected");
      if (action === "load-sample-data-package") updateDemo(selectIntakeMode(state.demoRuntime, "sample"), "Sample data package selected");
      if (action === "download-sample-package") downloadSamplePackage();
      if (action === "view-accepted-fields") showAcceptedFields();
      if (action === "view-analysis-schema") showAnalysisSchema();
      if (action === "run-ai-analysis") animateAnalysis();
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
      if (action === "live-execution-note") window.alert("Execution capture requires backend execution endpoint. The evaluation workspace can show the verification chain.");
      if (action === "integration-note") window.alert(button.dataset.message || "Runtime status details are shown in this card. Secure credential storage requires backend credential endpoints.");
      if (action === "request-backend-setup") {
        const provider = button.dataset.integration || "WiseConn";
        updateDemo(prepareBackendSetupRequest(state.demoRuntime, provider), "Backend setup request prepared");
        openBackendSetupModal(provider);
      }
      if (action === "report-readiness") window.alert(button.dataset.message || "Report generation will activate when the required backend endpoint is available.");
      if (action === "check-integrations") setActiveView("integrations");
    });
  });
}

subscribe(render);
render();
