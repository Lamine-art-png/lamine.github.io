import { ApiClient } from "./apiClient.js";
import { launchDemoSession, notify, returnToEntry, setActiveView, setDemoRuntime, setLoginError, startLoginScaffold, state, subscribe, SESSION_MODES } from "./state.js";
import { loadLiveSnapshot, generateWiseConnRecommendation } from "./services/liveData.js";
import { addObservation, completeAiAnalysis, generateDemoRecommendation, generateDemoReport, markApplied, nextStep, resetDemo, runAiAnalysis, scheduleRecommendation, selectFarm, selectIntakeMode, selectZone, startGuidedDemo, switchScenario, toCsv, verifyOutcome } from "./services/demoRuntime.js";
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
    setLoginError("We could not verify those credentials. Check your email and password or launch the pilot workspace.");
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
  if (!rt.analysis.sessionId) {
    const created = await api.createWorkbenchSession({ mode: rt.intakeMode === "connected" ? "live" : "uploaded" });
    if (created.ok) rt.analysis.sessionId = created.data.session_id;
  }
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
  } else if (rt.analysis.sessionId) {
    backend = await api.analyzeWorkbenchSession(rt.analysis.sessionId, { session_id: rt.analysis.sessionId, mode: "uploaded" });
  }
  if (backend?.ok) {
    rt.analysis.backendResult = backend.data;
    updateDemo(completeAiAnalysis(rt), "Analysis complete. Decision ready.");
  } else {
    rt.analysis.running = false;
    updateDemo(rt, backend?.error || "Analysis failed. You can use pilot data package fallback.");
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
    const rt = state.demoRuntime;
    if (!rt.analysis.sessionId) {
      const created = await api.createWorkbenchSession({ mode: "uploaded" });
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
      if (action === "reset-demo") updateDemo(resetDemo(), "Workspace reset");
      if (action === "start-guide") updateDemo(startGuidedDemo(state.demoRuntime), "Guided run started");
      if (action === "next-step") updateDemo(nextStep(state.demoRuntime), "Run advanced");
      if (action === "generate-demo-recommendation") updateDemo(generateDemoRecommendation(state.demoRuntime), "Recommendation generated");
      if (action === "use-connected-field") updateDemo(selectIntakeMode(state.demoRuntime, "connected"), "Connected field context selected");
      if (action === "mode-connected") updateDemo(selectIntakeMode(state.demoRuntime, "connected"), "Connected source selected");
      if (action === "mode-upload") updateDemo(selectIntakeMode(state.demoRuntime, "uploaded"), "Upload records selected");
      if (action === "mode-pilot") updateDemo(selectIntakeMode(state.demoRuntime, "pilot"), "Pilot data package selected");
      if (action === "load-demo-data-package") updateDemo(selectIntakeMode(state.demoRuntime, "pilot"), "Pilot data package selected");
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
      if (action === "live-execution-note") window.alert("Execution capture requires backend execution endpoint. This workspace can simulate the verification chain.");
      if (action === "integration-note") window.alert(button.dataset.message || "Runtime status details are shown in this card. Secure credential storage requires backend credential endpoints.");

      if (action === "open-setup-brief") { document.getElementById("setup-brief-drawer")?.classList.remove("hidden"); updateDemo(state.demoRuntime, "Integration setup brief prepared"); }
      if (action === "close-setup-brief") document.getElementById("setup-brief-drawer")?.classList.add("hidden");
      if (action === "copy-setup-brief") { const text = document.getElementById("setup-brief-text")?.textContent || ""; navigator.clipboard?.writeText(text); updateDemo(state.demoRuntime, "Integration setup brief prepared"); }
      if (action === "download-setup-brief") { const text = document.getElementById("setup-brief-text")?.textContent || ""; const blob = new Blob([text], { type: "text/plain" }); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href=url; a.download="integration-setup-brief.txt"; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url); updateDemo(state.demoRuntime, "Integration setup brief prepared"); }

    });
  });
}

subscribe(render);
render();
