import { ApiClient } from "./apiClient.js";
import { launchDemoSession, notify, returnToEntry, setActiveView, setDemoRuntime, setLoginError, startLoginScaffold, state, subscribe, SESSION_MODES } from "./state.js";
import { loadLiveSnapshot, generateWiseConnRecommendation } from "./services/liveData.js";
import { addObservation, generateDemoRecommendation, generateDemoReport, markApplied, nextStep, resetDemo, scheduleRecommendation, selectFarm, selectZone, startGuidedDemo, switchScenario, toCsv, verifyOutcome } from "./services/demoRuntime.js";
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

function updateDemo(runtime, message = "Demo updated") {
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
    setLoginError("We could not verify those credentials. Check your email and password or launch the demo workspace.");
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

  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.action;
      if (action === "reset-demo") updateDemo(resetDemo(), "Demo reset");
      if (action === "start-guide") updateDemo(startGuidedDemo(state.demoRuntime), "Guided demo started");
      if (action === "next-step") updateDemo(nextStep(state.demoRuntime), "Demo advanced");
      if (action === "generate-demo-recommendation") updateDemo(generateDemoRecommendation(state.demoRuntime), "Recommendation generated");
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
      if (action === "live-execution-note") window.alert("Execution capture requires backend execution endpoint. This demo can simulate the verification chain.");
      if (action === "integration-note") window.alert(button.dataset.message || "Runtime status details are shown in this card. Secure credential storage requires backend credential endpoints.");
    });
  });
}

subscribe(render);
render();
