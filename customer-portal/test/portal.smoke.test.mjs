// Dependency-free smoke tests for the AGRO-AI customer portal.
// Run with:  node --test customer-portal/test/
//
// These guard the enterprise-maturity invariants of the Water Command Center
// (no scaffold language, representative package auto-loads with a verified
// decision, scenario switching, and the core render output) without a browser
// or any third-party dependency.

import { test } from "node:test";
import assert from "node:assert/strict";

// Minimal window/sessionStorage shim so the runtime module can persist state.
const store = {};
globalThis.window = {
  sessionStorage: {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  },
};

const rtm = await import("../js/services/demoRuntime.js");
const { renderShell } = await import("../js/views/shellView.js");
const { renderCommandCenter } = await import("../js/views/commandCenterView.js");
const { renderIntegrations } = await import("../js/views/integrationsView.js");
const { renderOverview } = await import("../js/views/overviewView.js");
const { renderEvidence } = await import("../js/views/evidenceView.js");
const { renderAssurance } = await import("../js/views/assuranceView.js");
const { renderAgent } = await import("../js/views/agentView.js");

function freshState() {
  const runtime = rtm.loadRepresentativePackage(rtm.resetDemo(false));
  return {
    session: { mode: "demo", workspace: { name: "Alpha Vineyard" }, userName: "Operations user", authNotice: "" },
    activeView: "overview",
    demoRuntime: runtime,
    assurance: { activePassportId: "demo-passport-alpha-vineyard", activePassport: null, readiness: null, latestExport: null, demoMode: true },
    agent: { activeRunId: "demo-agent-run-alpha-vineyard", activeRun: null, findings: [], proposedActions: [] },
  };
}

function liveNoPassportState() {
  const state = freshState();
  state.session = { mode: "live", workspace: { name: "Live Workspace" }, userName: "Operations user", authNotice: "Backend auth required" };
  state.assurance = { activePassportId: "", activePassport: null, readiness: null, latestExport: null, demoMode: false };
  state.agent = { activeRunId: "", activeRun: null, findings: [], proposedActions: [], recommendations: [], automationPlan: [], messages: [] };
  return state;
}

// Banned user-facing scaffold language (case-insensitive on rendered text).
const BANNED = ["workspace.user@agroai-pilot.com", "AI Workbench", "Demo Workspace", "Pilot data", "pilot package"];

test("representative package auto-loads with a verified decision", () => {
  const rt = freshState().demoRuntime;
  assert.equal(rt.analysis.status, "complete");
  assert.equal(rt.workspaceScenarioId, "alpha-vineyard");
  assert.match(rt.activeRecommendation.action, /Irrigate 42 min tonight/);
  assert.ok(rt.reportSnapshots[0], "a report snapshot is generated on load");
  assert.equal(rt.reconciliationRows.length, 7);
});

test("all four workspace scenarios switch and update the decision", () => {
  let rt = freshState().demoRuntime;
  const expected = {
    "alpha-vineyard": ["Cabernet Sauvignon", "86%"],
    "almond-orchard": ["Almonds", "91%"],
    "multi-farm": ["Mixed (vineyard + almond)", "88%"],
    "partner-validation": ["Trial vineyard", "73%"],
  };
  for (const sc of rtm.getWorkspaceScenarios()) {
    rt = rtm.switchWorkspaceScenario(rt, sc.id);
    const [crop, conf] = expected[sc.id];
    assert.equal(rt.activeRecommendation.crop, crop, `${sc.id} crop`);
    assert.equal(rt.activeRecommendation.confidence, conf, `${sc.id} confidence`);
    assert.equal(rt.operatingChain[0].status, "Complete", `${sc.id} chain ready`);
  }
});

test("refresh-intelligence fallback respects the active workspace scenario", () => {
  let rt = rtm.switchWorkspaceScenario(freshState().demoRuntime, "almond-orchard");
  rt = rtm.completeAiAnalysis(rtm.runAiAnalysis(rt));
  assert.match(rt.activeRecommendation.action, /Apply 18 mm/);
  assert.equal(rt.institutionalKpis.waterSavingsRate, "31%");
});

test("evidence chain actions complete and CSV export produces rows", () => {
  let rt = freshState().demoRuntime;
  rt = rtm.verifyOutcome(rtm.addObservation(rtm.markApplied(rtm.scheduleRecommendation(rt))));
  assert.deepEqual(rt.operatingChain.map((s) => s.status), Array(5).fill("Complete"));
  const csv = rtm.toCsv(rt.reportSnapshots[0]);
  assert.ok(csv.split("\n").length > 5, "CSV has multiple rows");
});

test("shell presents the Enterprise OS IA and agent rail", () => {
  const state = freshState();
  const shell = renderShell(state, "");
  assert.match(shell, /Enterprise Operating System/);
  assert.match(shell, /Overview/);
  assert.match(shell, /Operations/);
  assert.match(shell, /Assurance/);
  assert.match(shell, /Evidence/);
  assert.match(shell, /AGRO-AI Rail/);
  assert.match(shell, /Evaluation · not live · not certified/);
  assert.match(shell, /workspace-scenario-select/);
  assert.match(shell, /Operations user/);
  assert.match(shell, /Exit workspace/);
  for (const term of BANNED) assert.ok(!shell.includes(term), `shell must not contain "${term}"`);
});

test("overview and evidence workspaces render proof-centered enterprise surfaces", () => {
  const state = freshState();
  const overview = renderOverview(state);
  const evidence = renderEvidence(state);
  assert.match(overview, /Enterprise OS Overview/);
  assert.match(overview, /Action Queue/);
  assert.match(overview, /Agent Activity/);
  assert.match(overview, /Operational Health/);
  assert.match(evidence, /Evidence Vault/);
  assert.match(evidence, /Extracted Facts/);
  assert.match(evidence, /Reviewer evaluation required/);
});

test("live mode without an Assurance Passport never renders evaluation passport data", () => {
  const state = liveNoPassportState();
  const rendered = [
    renderOverview(state),
    renderAssurance(state),
    renderEvidence(state),
    renderAgent(state),
  ].join("\n");
  assert.match(rendered, /Create or connect a live Assurance Passport/);
  assert.match(rendered, /Backend auth required for live Assurance APIs\. No demo passport was loaded\./);
  assert.doesNotMatch(rendered, /Alpha Vineyard/);
  assert.doesNotMatch(rendered, /demo-passport-alpha-vineyard/);
  assert.doesNotMatch(rendered, /controller_events\.csv/);
});

test("live mode ignores a stale assurance demoMode flag", () => {
  const state = liveNoPassportState();
  state.assurance.demoMode = true;
  const rendered = [renderAssurance(state), renderEvidence(state), renderAgent(state)].join("\n");
  assert.match(rendered, /Create or connect a live Assurance Passport/);
  assert.doesNotMatch(rendered, /Alpha Vineyard/);
  assert.doesNotMatch(rendered, /demo-passport-alpha-vineyard/);
});

test("command page shows the decision, drawer entry, run state, and trace", () => {
  const state = freshState();
  const cmd = renderCommandCenter(state);
  assert.match(cmd, /Add or manage sources/);
  assert.match(cmd, /Refresh intelligence/); // auto-loaded => complete state
  assert.match(cmd, /Analysis trace/);
  assert.match(cmd, /Irrigate 42 min tonight/);
  for (const term of BANNED) assert.ok(!cmd.includes(term), `command page must not contain "${term}"`);
});

test("integrations exposes the 7-step self-serve workflow", () => {
  const integ = renderIntegrations(freshState());
  assert.match(integ, /self-serve-stepper/);
  assert.match(integ, /Choose source type/);
  assert.match(integ, /Export executive report/);
});
