import {
  demoAgroAiExplainer,
  demoAiDecisionPipeline,
  demoAuditLog,
  demoFarms,
  demoInstitutionalKpis,
  demoReconciliationRows,
  demoRecommendation,
  demoTransformation,
  demoWorkspace,
} from "../demoData.js";

const STORAGE_KEY = "AGROAI_EVALUATION_RUNTIME";
const ACTOR = "Operations Manager";

const scenarios = {
  dry_day: {
    id: "dry_day",
    name: "Dry day, irrigation recommended",
    note: "Root-zone depletion and high ETo support irrigation tonight.",
    recommendation: { ...demoRecommendation },
  },
  rain_wait: {
    id: "rain_wait",
    name: "Rain forecast, wait recommended",
    note: "Rain forecast reduces irrigation need; AGRO-AI recommends waiting.",
    recommendation: {
      ...demoRecommendation,
      action: "Wait for forecast rain",
      decision: "Wait for forecast rain",
      timing: "Reassess tomorrow morning",
      start_time: "Reassess tomorrow morning",
      duration: "0 minutes",
      duration_min: 0,
      depth: "0 mm",
      depth_mm: 0,
      confidence: "82%",
      dataQuality: "High",
      keyDrivers: ["Rain forecast within 12 hours", "Root-zone moisture adequate", "Avoid unnecessary water application"],
      executionTask: "No controller schedule required; review after forecast window.",
      verificationPlan: "Confirm rainfall and inspect canopy condition after forecast window.",
    },
  },
  partial_telemetry: {
    id: "partial_telemetry",
    name: "Partial telemetry, confidence reduced",
    note: "A missing sensor reading reduces confidence and triggers observation follow-up.",
    recommendation: {
      ...demoRecommendation,
      confidence: "68%",
      dataQuality: "Partial telemetry",
      keyDrivers: ["Recent irrigation history available", "One moisture sensor stale", "Field observation requested"],
      missingInputs: ["One moisture sensor missing recent reading"],
      limitations: ["One moisture sensor missing recent reading"],
      executionTask: "Schedule conservative irrigation and request sensor check.",
    },
  },
  mismatch: {
    id: "mismatch",
    name: "Planned vs applied mismatch",
    note: "Controller application differs from planned duration; verification flags follow-up.",
    recommendation: {
      ...demoRecommendation,
      action: "Irrigate with verification watch",
      decision: "Irrigate with verification watch",
      confidence: "79%",
      dataQuality: "Medium",
      keyDrivers: ["Water deficit present", "Controller history shows prior mismatch", "Verification follow-up required"],
      verificationPlan: "Compare scheduled duration with applied event and flag variance above 10%.",
    },
  },
  verified_success: {
    id: "verified_success",
    name: "Verification completed successfully",
    note: "Recommendation has moved through scheduling, application, observation, and verification.",
    recommendation: {
      ...demoRecommendation,
      confidence: "91%",
      dataQuality: "High",
      verificationPlan: "Controller event and field observation confirm expected outcome.",
    },
  },
};

// Representative evaluation workspaces used for founder-led sales calls.
// Each loads representative records and remains clearly marked as representative data.
export const workspaceScenarios = {
  "alpha-vineyard": {
    id: "alpha-vineyard",
    name: "Alpha Vineyard",
    farmId: "alpha-vineyard",
    zoneId: "block-a-north",
    savings: "27%",
    evidence: "92%",
    recommendation: {
      ...demoRecommendation,
      action: "Irrigate 42 min tonight",
      decision: "Irrigate 42 min tonight",
      timing: "21:00 PT",
      start_time: "21:00 PT",
      duration: "42 min",
      depth: "12 mm net",
      confidence: "86%",
      dataQuality: "92%",
      crop: "Cabernet Sauvignon",
      block: "Block A North",
      keyDrivers: ["ETo 6.4 mm and 38 percent root-zone deficit", "No rain window available", "Controller schedule matched"],
      verificationPlan: "Required",
    },
    reconciliation: [
      ["Controller history", "Last irrigation event: 36 min", "Valid recent controller event", "Matched"],
      ["Weather demand", "ETo 6.4 mm, rain 0 mm", "High water demand", "Matched"],
      ["Soil moisture", "38 percent deficit at 30 cm", "Root-zone deficit supports irrigation", "Matched"],
      ["Flow meter", "Actual flow within 8 percent of plan", "Applied water consistent", "Matched"],
      ["Field observation", "Mild afternoon stress", "Supports irrigation recommendation", "Matched"],
      ["Earth observation layer", "Elevated canopy stress index", "Supports water demand signal", "Matched"],
      ["Talgil", "Runtime reachable, no selected production target", "Integration available, target selection pending", "Pending target"],
    ],
  },
  "almond-orchard": {
    id: "almond-orchard",
    name: "Almond Orchard",
    farmId: "delta-almonds",
    zoneId: "almond-block-4",
    savings: "31%",
    evidence: "94%",
    recommendation: {
      ...demoRecommendation,
      action: "Apply 18 mm before 05:00",
      decision: "Apply 18 mm before 05:00",
      timing: "03:15 local",
      start_time: "03:15 local",
      duration: "50 min",
      depth: "18 mm net",
      confidence: "91%",
      dataQuality: "94%",
      crop: "Almonds",
      block: "Almond Block 4",
      keyDrivers: ["ETo 6.5 mm and 42 percent root-zone deficit", "Pump tariff peak at 06:00", "Kernel-fill water demand"],
      verificationPlan: "Required",
    },
    reconciliation: [
      ["Controller history", "Last set 55 min, mild applied variance", "Valid controller event", "Matched"],
      ["Weather demand", "ETo 6.5 mm, rain 0 mm", "High water demand", "Matched"],
      ["Soil moisture", "42 percent deficit at 30 cm", "Root-zone deficit supports irrigation", "Matched"],
      ["Flow meter", "Prior set +12.3 percent over plan", "Applied-water variance flagged", "Review"],
      ["Field observation", "Mild leaf curl at southwest corner", "Supports irrigation recommendation", "Matched"],
      ["Earth observation layer", "Vegetation stress index 0.52", "Supports water demand signal", "Matched"],
      ["Talgil", "Not used for this orchard", "WiseConn-managed orchard", "Pending target"],
    ],
  },
  "multi-farm": {
    id: "multi-farm",
    name: "Multi-Farm Portfolio",
    farmId: "alpha-vineyard",
    zoneId: "block-a-north",
    savings: "26%",
    evidence: "90%",
    recommendation: {
      ...demoRecommendation,
      action: "3 blocks irrigate tonight, 1 hold",
      decision: "3 blocks irrigate tonight, 1 hold",
      timing: "Tonight, staggered windows",
      start_time: "Tonight, staggered windows",
      duration: "Per-block schedule",
      depth: "12–18 mm net",
      confidence: "88%",
      dataQuality: "90%",
      crop: "Mixed (vineyard + almond)",
      block: "4 active blocks",
      keyDrivers: ["Portfolio root-zone deficit across 3 of 4 blocks", "One block within forecast rain window", "Energy tariff windows respected"],
      verificationPlan: "Required",
    },
    reconciliation: [
      ["Controller history", "12 controller events across 3 farms", "Recent events validated", "Matched"],
      ["Weather demand", "ETo 6.0–6.8 mm by region", "High demand in 3 of 4 blocks", "Matched"],
      ["Soil moisture", "Deficit 28–44 percent by block", "Mixed deficit, one block adequate", "Matched"],
      ["Flow meter", "One block over plan, others within range", "Applied-water variance localized", "Review"],
      ["Field observation", "Stress notes on 2 blocks", "Supports irrigation in those blocks", "Matched"],
      ["Earth observation layer", "Elevated stress on vineyard blocks", "Supports water demand signal", "Matched"],
      ["Talgil", "North Ridge runtime reachable", "Target selection pending", "Pending target"],
    ],
  },
  "partner-validation": {
    id: "partner-validation",
    name: "Partner Data Validation",
    farmId: "west-citrus",
    zoneId: "vineyard-block-trial",
    savings: "—",
    evidence: "78%",
    recommendation: {
      ...demoRecommendation,
      action: "Validate partner feed before scheduling",
      decision: "Validate partner feed before scheduling",
      timing: "Pending partner feed authorization",
      start_time: "Pending partner feed authorization",
      duration: "Awaiting validation",
      depth: "Awaiting validation",
      confidence: "73%",
      dataQuality: "78%",
      crop: "Trial vineyard",
      block: "Vineyard Block Trial",
      keyDrivers: ["Partner feed records ingested as representative data", "Pressure sensor coverage is partial", "Production authorization required before scheduling"],
      verificationPlan: "Partner feed authorization required for production use",
    },
    reconciliation: [
      ["Controller history", "Talgil trial rows ingested", "Trial block, separated from commercial", "Matched"],
      ["Weather demand", "ETo within seasonal range", "Demand evaluated", "Matched"],
      ["Soil moisture", "Partial sensor coverage", "Coverage gap flagged", "Review"],
      ["Flow meter", "Prior set variance +23 percent", "Applied-water variance flagged", "Review"],
      ["Field observation", "Trial rows watched separately", "Supports cautious recommendation", "Matched"],
      ["Earth observation layer", "Partner-provided sample layer", "Representative until authorized", "Pending target"],
      ["Talgil", "Runtime reachable, trial target", "Production authorization required", "Pending target"],
    ],
  },
};

export function getWorkspaceScenarios() {
  return Object.values(workspaceScenarios);
}

function now() {
  return new Date().toISOString();
}

function findFarm(farmId) {
  return demoFarms.find((farm) => farm.id === farmId) || demoFarms[0];
}

function findZone(farm, zoneId) {
  return farm.zones.find((zone) => zone.id === zoneId) || farm.zones[0];
}

function baseChain(active = "") {
  const labels = ["Recommended", "Scheduled", "Applied", "Observed", "Verified"];
  const keys = ["recommended", "scheduled", "applied", "observed", "verified"];
  const activeIndex = keys.indexOf(active);
  return keys.map((key, index) => ({
    key,
    label: labels[index],
    status: activeIndex >= 0 && index <= activeIndex ? "Complete" : "Pending",
    timestamp: activeIndex >= 0 && index <= activeIndex ? now() : "",
    owner: key === "recommended" ? "AGRO-AI Intelligence Engine" : ACTOR,
    evidence: activeIndex >= 0 && index <= activeIndex ? `${labels[index]} evidence captured.` : `${labels[index]} pending`,
    note: "Representative runtime state",
  }));
}

export function getAnalysisSteps() {
  return [
    ["Sources", "Waiting for source records"],
    ["Normalize", "Standardize units, aliases, and timestamps"],
    ["Reconcile", "Compare controller, weather, soil, flow, and observations"],
    ["Decide", "Prepare recommendation and confidence"],
    ["Verify", "Prepare evidence chain and report"],
  ].map(([title, detail]) => ({
    title,
    label: title,
    status: "pending",
    statusLabel: "Pending",
    detail,
    objectsProcessed: 0,
  }));
}

function normalizeStoredRuntime(runtime) {
  if (!runtime || !runtime.activeWorkspace) return resetDemo(false);
  runtime.activeWorkspace = demoWorkspace;
  runtime.activeFarm = runtime.activeFarm || findFarm("alpha-vineyard");
  runtime.activeZone = runtime.activeZone || findZone(runtime.activeFarm, "block-a-north");
  runtime.scenario = runtime.scenario || scenarios.dry_day;
  runtime.workspaceScenarioId = runtime.workspaceScenarioId || "alpha-vineyard";
  runtime.operatingChain = runtime.operatingChain || baseChain();
  runtime.auditEvents = runtime.auditEvents || [...demoAuditLog];
  runtime.reportSnapshots = runtime.reportSnapshots || [];
  runtime.intakeMode = runtime.intakeMode === "uploaded" ? "sample" : runtime.intakeMode || "";
  runtime.intakeModeLabel = runtime.intakeModeLabel && !/demo|sample data/i.test(runtime.intakeModeLabel) ? runtime.intakeModeLabel : "No source selected";
  runtime.analysis = {
    status: runtime.analysis?.status || "idle",
    running: Boolean(runtime.analysis?.running),
    statusLabel: runtime.analysis?.statusLabel && !/demo|sample package|AI context/i.test(runtime.analysis.statusLabel) ? runtime.analysis.statusLabel : "Waiting for source",
    steps: runtime.analysis?.steps?.length ? runtime.analysis.steps.map((step) => ({ ...step, title: step.title || step.label })) : getAnalysisSteps(),
    backendResult: runtime.analysis?.backendResult || null,
    backendError: runtime.analysis?.backendError || "",
    sessionId: runtime.analysis?.sessionId || "",
    artifacts: runtime.analysis?.artifacts || [],
    sampleLoaded: Boolean(runtime.analysis?.sampleLoaded),
  };
  runtime.sourceState = runtime.sourceState || {
    provider: "WiseConn",
    entityId: "162803",
    status: runtime.intakeMode ? "Source selected" : "Waiting for source",
    uploadedFileName: "",
    uploadedType: "",
    parseStatus: "",
  };
  return runtime;
}

export function resetAnalysis(runtime) {
  runtime.analysis = {
    status: "idle",
    running: false,
    statusLabel: runtime.intakeMode ? "Source selected" : "Waiting for source",
    steps: getAnalysisSteps(),
    backendResult: null,
    backendError: "",
    sessionId: runtime.analysis?.sessionId || "",
    artifacts: runtime.analysis?.artifacts || [],
    sampleLoaded: runtime.analysis?.sampleLoaded || false,
  };
  runtime.activeRecommendation = null;
  runtime.reconciliationRows = demoReconciliationRows;
  runtime.operatingChain = baseChain("recommended");
  return runtime;
}

export function runAiAnalysis(runtime) {
  runtime.analysis.running = true;
  runtime.analysis.status = "running";
  runtime.analysis.statusLabel = "Analyzing source records";
  runtime.analysis.backendError = "";
  runtime.analysis.steps = getAnalysisSteps().map((step, index) => index === 0 ? { ...step, status: "running", statusLabel: "Active" } : step);
  addAudit(runtime, "Intelligence analysis started", "AGRO-AI began processing selected intake context.");
  return persist(runtime);
}

function confidenceLabel(value) {
  if (typeof value === "number") return `${Math.round(value * 100)}%`;
  return value || "Source pending";
}

function recommendationFromBackend(result) {
  const rec = result?.recommendation || result?.report_summary?.recommendation || {};
  const summary = result?.report_summary || {};
  return {
    ...demoRecommendation,
    ...rec,
    action: rec.action || rec.decision || summary.recommendation || demoRecommendation.action,
    decision: rec.action || rec.decision || summary.recommendation || demoRecommendation.decision,
    timing: rec.start_time || rec.start || rec.timing || demoRecommendation.timing,
    start_time: rec.start_time || rec.start || rec.timing || demoRecommendation.start_time,
    duration: rec.duration || (rec.duration_min ? `${rec.duration_min} min` : demoRecommendation.duration),
    depth: rec.depth || (rec.depth_mm ? `${rec.depth_mm} mm net` : demoRecommendation.depth),
    confidence: confidenceLabel(rec.confidence || summary.confidence),
    dataQuality: result?.reconciliation?.evidence_completeness || summary.evidence_completeness || rec.confidence_label || demoRecommendation.dataQuality,
    keyDrivers: rec.key_drivers || rec.keyDrivers || demoRecommendation.keyDrivers,
    missingInputs: rec.limitations || result?.limitations || result?.reconciliation?.missing_inputs || [],
    limitations: rec.limitations || result?.limitations || [],
    sourceTraceSummary: summary.executive_summary || demoRecommendation.sourceTraceSummary,
    executionTask: "Schedule review required before controller execution.",
    verificationPlan: rec.verification_requirement || result?.verification_plan?.requirement || demoRecommendation.verificationPlan,
  };
}

function reconciliationRowsFromBackend(result) {
  const recon = result?.reconciliation || {};
  const candidateRows = Array.isArray(recon)
    ? recon
    : recon.rows || recon.source_reconciliation || result?.source_reconciliation || [];
  if (Array.isArray(candidateRows) && candidateRows.length) {
    return candidateRows.map((row) => {
      if (Array.isArray(row)) return row;
      return [
        row.source || row.name || "Source",
        row.signal || row.value || row.evidence || "Signal received",
        row.interpretation || row.meaning || row.summary || "Interpreted by reconciliation engine",
        row.status || row.state || "Matched",
      ];
    });
  }
  return [
    ["Planned vs applied", recon.planned_vs_applied_variance || "Not available", "Variance checked against controller and flow-meter evidence", recon.conflicts_detected?.length ? "Review" : "Matched"],
    ["Controller validity", recon.controller_event_validity || "Not available", "Controller event integrity and missing pressure cases checked", recon.controller_event_validity ? "Checked" : "Pending"],
    ["Flow-meter agreement", recon.flow_meter_agreement || "Not available", "Flow-meter volume compared with planned application", recon.flow_meter_agreement ? "Checked" : "Pending"],
    ["Weather demand", recon.weather_demand || "Not available", "ETo and rain forecast evaluated", recon.weather_demand ? "Matched" : "Pending"],
    ["Soil deficit", recon.soil_moisture_deficit || "Not available", "Root-zone deficit evaluated across depths", recon.soil_moisture_deficit ? "Matched" : "Pending"],
    ["Field observation", recon.field_observation_support || "Not available", "Grower notes and field observations reconciled", recon.field_observation_support ? "Matched" : "Pending"],
    ["Earth observation layer", recon.satellite_stress_support || "Not available", "Canopy stress layer evaluated without claiming live telemetry", recon.satellite_stress_support ? "Checked" : "Pending"],
  ];
}

function traceStepsFromBackend(result) {
  const trace = result?.analysis_trace || [];
  if (!trace.length) return getAnalysisSteps();
  return trace.map((step) => ({
    title: step.title,
    label: step.title,
    status: step.status === "review" || step.status === "limited" ? "running" : "complete",
    statusLabel: step.status === "review" ? "Review" : step.status === "limited" ? "Limited" : "Complete",
    detail: step.details || "",
    objectsProcessed: step.objects_processed || 0,
    confidenceDelta: step.confidence_delta,
  }));
}

function reportSnapshotFromBackend(runtime, result) {
  const rec = recommendationFromBackend(result);
  const context = result?.normalized_context || {};
  return {
    id: `report-${Date.now()}`,
    type: "Irrigation Intelligence Report",
    generatedAt: now(),
    farm: context.farm || runtime.activeFarm.name,
    block: context.block || runtime.activeZone.name,
    crop: context.crop || runtime.activeZone.crop,
    controllerSource: context.provider_context || runtime.activeZone.controllerSource,
    waterSavedYtd: runtime.institutionalKpis?.waterSavedYtd,
    waterSavingsRate: runtime.institutionalKpis?.waterSavingsRate,
    dollarValueAvoided: runtime.institutionalKpis?.dollarValueAvoided,
    pricingAssumption: runtime.institutionalKpis?.pricingAssumption,
    compliancePosture: result?.report_summary?.compliance_posture || runtime.institutionalKpis?.compliancePosture,
    evidenceCompleteness: result?.report_summary?.evidence_completeness || runtime.institutionalKpis?.evidenceCompleteness,
    portfolioCoverage: runtime.institutionalKpis?.portfolioCoverage,
    recommendation: rec.action,
    scheduledAction: runtime.operatingChain[1]?.evidence || "Awaiting schedule",
    appliedAction: runtime.operatingChain[2]?.evidence || "Awaiting controller execution",
    observedOutcome: runtime.operatingChain[3]?.evidence || "Awaiting field observation",
    verificationStatus: runtime.operatingChain[4]?.status || "Verification pending",
    confidence: rec.confidence,
    dataQuality: rec.dataQuality,
    keyDrivers: rec.keyDrivers || rec.key_drivers || [],
    waterEfficiencyNote: result?.report_summary?.water_saved_assumption || "Decision supports targeted water application and verification evidence.",
  };
}

export function completeAiAnalysis(runtime) {
  runtime.analysis.running = false;
  runtime.analysis.status = "complete";
  runtime.analysis.statusLabel = "Decision ready";
  if (runtime.analysis.backendResult) {
    runtime.analysis.steps = traceStepsFromBackend(runtime.analysis.backendResult);
    runtime.activeRecommendation = recommendationFromBackend(runtime.analysis.backendResult);
    runtime.reconciliationRows = reconciliationRowsFromBackend(runtime.analysis.backendResult);
    runtime.operatingChain = baseChain("recommended");
    runtime.operatingChain[0] = { ...runtime.operatingChain[0], evidence: "Verified water decision produced from selected source records." };
    runtime.reportSnapshots = [reportSnapshotFromBackend(runtime, runtime.analysis.backendResult), ...(runtime.reportSnapshots || [])].slice(0, 12);
  } else {
    const workspace = runtime.workspaceScenarioId ? workspaceScenarios[runtime.workspaceScenarioId] : null;
    runtime.analysis.steps = runtime.analysis.steps.map((step) => ({ ...step, status: "complete", statusLabel: "Complete", detail: "Source reconciliation complete" }));
    runtime.activeRecommendation = {
      ...(workspace ? workspace.recommendation : runtime.scenario.recommendation),
      generatedAt: now(),
      sourceTraceSummary: `Context assembled from ${runtime.activeZone.controllerSource}, crop profile, soil profile, weather, and field observation.`,
    };
    runtime.reconciliationRows = workspace ? workspace.reconciliation : demoReconciliationRows;
    runtime.operatingChain = baseChain("recommended");
    runtime.operatingChain[0] = { ...runtime.operatingChain[0], evidence: "Representative-data analysis produced a verified water decision." };
    runtime.reportSnapshots = [reportSnapshotFromActiveRecommendation(runtime), ...(runtime.reportSnapshots || [])].slice(0, 12);
  }
  addAudit(runtime, "Intelligence analysis completed", "Recommendation ready with verification required.");
  return persist(runtime);
}

function addAudit(runtime, event, detail, source = runtime.activeZone?.name || "Evaluation workspace") {
  runtime.auditEvents = [{ time: now(), actor: ACTOR, event, source, detail }, ...(runtime.auditEvents || [])].slice(0, 80);
}

function persist(runtime) {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(runtime));
  } catch (_error) {
    // Runtime still works in memory when sessionStorage is unavailable.
  }
  return runtime;
}

export function createDemoRuntime() {
  try {
    const stored = window.sessionStorage.getItem(STORAGE_KEY);
    if (stored) return normalizeStoredRuntime(JSON.parse(stored));
  } catch (_error) {
    // Ignore corrupt or unavailable sessionStorage.
  }
  return resetDemo(false);
}

export function resetDemo(shouldPersist = true) {
  const farm = findFarm("alpha-vineyard");
  const zone = findZone(farm, "block-a-north");
  const runtime = {
    activeWorkspace: demoWorkspace,
    activeFarm: farm,
    activeZone: zone,
    activeRecommendation: null,
    institutionalKpis: { ...demoInstitutionalKpis },
    aiDecisionPipeline: demoAiDecisionPipeline,
    intelligenceTransformation: demoTransformation,
    reconciliationRows: demoReconciliationRows,
    agroAiExplainer: demoAgroAiExplainer,
    operatingChain: baseChain(),
    auditEvents: [...demoAuditLog],
    reportSnapshots: [],
    scenario: scenarios.dry_day,
    currentStep: 0,
    guideStarted: false,
    toast: "",
    intakeMode: "",
    intakeModeLabel: "No intake selected",
    analysis: {
      status: "idle",
      running: false,
      statusLabel: "Waiting for source",
      steps: getAnalysisSteps(),
      backendResult: null,
      backendError: "",
      sessionId: "",
      artifacts: [],
      sampleLoaded: false,
    },
    sourceState: {
      provider: "WiseConn",
      entityId: "162803",
      status: "Waiting for source",
      uploadedFileName: "",
      uploadedType: "",
      parseStatus: "",
    },
  };
  addAudit(runtime, "Workspace launched", "Evaluation workspace reset and ready.");
  return shouldPersist ? persist(runtime) : runtime;
}

export function getScenarios() {
  return Object.values(scenarios);
}

export function selectFarm(runtime, farmId) {
  runtime.activeFarm = findFarm(farmId);
  runtime.activeZone = runtime.activeFarm.zones[0];
  addAudit(runtime, "Farm selected", `${runtime.activeFarm.name} selected.`, runtime.activeFarm.name);
  return persist(runtime);
}

export function selectZone(runtime, zoneId) {
  runtime.activeZone = findZone(runtime.activeFarm, zoneId);
  addAudit(runtime, "Block selected", `${runtime.activeZone.name} selected.`, runtime.activeZone.name);
  return persist(runtime);
}

export function switchScenario(runtime, scenarioId) {
  runtime.scenario = scenarios[scenarioId] || scenarios.dry_day;
  resetAnalysis(runtime);
  runtime.currentStep = 1;
  addAudit(runtime, "Scenario selected", runtime.scenario.name);
  return persist(runtime);
}

export function startGuidedDemo(runtime) {
  runtime.guideStarted = true;
  runtime.currentStep = 1;
  addAudit(runtime, "Guided workflow started", "Enterprise workflow activated.");
  return persist(runtime);
}

export function generateDemoRecommendation(runtime) {
  runtime.activeRecommendation = {
    ...runtime.scenario.recommendation,
    generatedAt: now(),
    sourceTraceSummary: `${runtime.scenario.note} Context assembled from ${runtime.activeZone.controllerSource}, crop profile, soil profile, weather, and field observation.`,
  };
  runtime.operatingChain = baseChain("recommended");
  runtime.operatingChain[0] = { ...runtime.operatingChain[0], evidence: "Recommendation ready with field context assembled." };
  runtime.currentStep = 2;
  addAudit(runtime, "Recommendation generated", runtime.activeRecommendation.decision || "Recommendation ready");
  return persist(runtime);
}

export function scheduleRecommendation(runtime) {
  runtime.operatingChain[0] = { ...runtime.operatingChain[0], status: "Complete", evidence: "Recommendation ready; schedule accepted." };
  runtime.operatingChain[1] = { ...runtime.operatingChain[1], status: "Complete", timestamp: now(), evidence: "Irrigation scheduled in controller window.", owner: ACTOR };
  runtime.currentStep = 3;
  addAudit(runtime, "Recommendation scheduled", "Schedule created for selected block.");
  return persist(runtime);
}

export function markApplied(runtime) {
  runtime.operatingChain[2] = {
    ...runtime.operatingChain[2],
    status: "Complete",
    timestamp: now(),
    evidence: runtime.scenario.id === "mismatch" ? "Applied water confirmed with duration variance." : "Applied water confirmed from controller event.",
    owner: ACTOR,
  };
  runtime.currentStep = 4;
  addAudit(runtime, "Applied water confirmed", runtime.operatingChain[2].evidence);
  return persist(runtime);
}

export function addObservation(runtime, note = "Field team observed stable canopy response after irrigation.") {
  runtime.operatingChain[3] = { ...runtime.operatingChain[3], status: "Complete", timestamp: now(), evidence: note, owner: ACTOR };
  runtime.currentStep = 5;
  addAudit(runtime, "Observation recorded", note);
  return persist(runtime);
}

export function verifyOutcome(runtime) {
  runtime.operatingChain[4] = {
    ...runtime.operatingChain[4],
    status: "Complete",
    timestamp: now(),
    evidence: runtime.scenario.id === "mismatch" ? "Verification flagged planned-vs-applied mismatch for review." : "Outcome verified against controller event and observation.",
    owner: "AGRO-AI Verification",
  };
  runtime.currentStep = 6;
  addAudit(runtime, "Outcome verified", runtime.operatingChain[4].evidence);
  return persist(runtime);
}

export function generateDemoReport(runtime, type = "Irrigation Intelligence Report") {
  const rec = runtime.activeRecommendation || runtime.scenario.recommendation;
  const snapshot = {
    id: `report-${Date.now()}`,
    type,
    generatedAt: now(),
    farm: runtime.activeFarm.name,
    block: runtime.activeZone.name,
    crop: runtime.activeZone.crop,
    controllerSource: runtime.activeZone.controllerSource,
    waterSavedYtd: runtime.institutionalKpis?.waterSavedYtd,
    waterSavingsRate: runtime.institutionalKpis?.waterSavingsRate,
    dollarValueAvoided: runtime.institutionalKpis?.dollarValueAvoided,
    pricingAssumption: runtime.institutionalKpis?.pricingAssumption,
    compliancePosture: runtime.institutionalKpis?.compliancePosture,
    evidenceCompleteness: runtime.institutionalKpis?.evidenceCompleteness,
    portfolioCoverage: runtime.institutionalKpis?.portfolioCoverage,
    recommendation: rec.action || rec.decision,
    scheduledAction: runtime.operatingChain[1]?.evidence || "Awaiting schedule",
    appliedAction: runtime.operatingChain[2]?.evidence || "Awaiting controller execution",
    observedOutcome: runtime.operatingChain[3]?.evidence || "Awaiting field observation",
    verificationStatus: runtime.operatingChain[4]?.status || "Verification pending",
    confidence: rec.confidence,
    dataQuality: rec.dataQuality,
    keyDrivers: rec.keyDrivers || rec.key_drivers || [],
    waterEfficiencyNote: runtime.scenario.id === "rain_wait" ? "Avoided unnecessary irrigation ahead of rainfall." : "Decision supports targeted water application and verification evidence.",
  };
  runtime.reportSnapshots = [snapshot, ...(runtime.reportSnapshots || [])].slice(0, 12);
  runtime.currentStep = 7;
  addAudit(runtime, "Report generated", `${type} preview generated.`, snapshot.block);
  return persist(runtime);
}

export function prepareBackendSetupRequest(runtime, integration = "WiseConn") {
  addAudit(runtime, "Backend setup request prepared", `${integration} backend setup brief prepared.`, integration);
  return persist(runtime);
}

export function nextStep(runtime) {
  if (!runtime.guideStarted) return startGuidedDemo(runtime);
  if (!runtime.activeRecommendation) return generateDemoRecommendation(runtime);
  if (runtime.operatingChain[1]?.status !== "Complete") return scheduleRecommendation(runtime);
  if (runtime.operatingChain[2]?.status !== "Complete") return markApplied(runtime);
  if (runtime.operatingChain[3]?.status !== "Complete") return addObservation(runtime);
  if (runtime.operatingChain[4]?.status !== "Complete") return verifyOutcome(runtime);
  return generateDemoReport(runtime);
}

export function toCsv(snapshot) {
  const rows = Object.entries(snapshot).map(([key, value]) => [key, Array.isArray(value) ? value.join("; ") : value]);
  return rows.map((row) => row.map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`).join(",")).join("\n");
}

export function selectIntakeMode(runtime, mode) {
  const normalizedMode = mode === "uploaded" ? "upload" : mode;
  runtime.intakeMode = normalizedMode;
  runtime.intakeModeLabel =
    normalizedMode === "connected"
      ? "Connected source"
      : normalizedMode === "upload"
        ? "Uploaded records"
        : "Representative data";
  runtime.sourceState = {
    ...(runtime.sourceState || {}),
    provider: normalizedMode === "connected" ? "WiseConn" : runtime.sourceState?.provider || "WiseConn",
    entityId: normalizedMode === "connected" ? "162803" : runtime.sourceState?.entityId || "162803",
    status: normalizedMode === "upload" && runtime.sourceState?.uploadedFileName ? "Uploaded records ready" : "Source selected",
  };
  runtime.analysis.statusLabel = "Source selected";
  addAudit(runtime, "Data intake selected", runtime.intakeModeLabel);
  return persist(runtime);
}

export function attachUploadArtifact(runtime, artifact, file) {
  runtime.intakeMode = "upload";
  runtime.intakeModeLabel = "Uploaded records";
  runtime.analysis.artifacts = [...(runtime.analysis.artifacts || []), artifact].slice(-8);
  runtime.sourceState = {
    ...(runtime.sourceState || {}),
    status: "Uploaded records ready",
    uploadedFileName: file?.name || artifact?.filename || artifact?.name || "Uploaded records",
    uploadedType: file?.name?.split(".").pop()?.toUpperCase() || artifact?.content_type || artifact?.type || "Records",
    parseStatus: artifact?.parse_status || artifact?.status || "Accepted for analysis",
  };
  runtime.analysis.statusLabel = "Source selected";
  addAudit(runtime, "Records uploaded", `${runtime.sourceState.uploadedFileName} accepted for analysis.`, "Uploaded records");
  return persist(runtime);
}

function reportSnapshotFromActiveRecommendation(runtime, type = "Irrigation Intelligence Report") {
  const rec = runtime.activeRecommendation || runtime.scenario.recommendation;
  return {
    id: `report-${Date.now()}`,
    type,
    generatedAt: now(),
    farm: runtime.activeFarm.name,
    block: rec.block || runtime.activeZone.name,
    crop: rec.crop || runtime.activeZone.crop,
    controllerSource: runtime.activeZone.controllerSource,
    waterSavedYtd: runtime.institutionalKpis?.waterSavedYtd,
    waterSavingsRate: runtime.institutionalKpis?.waterSavingsRate,
    dollarValueAvoided: runtime.institutionalKpis?.dollarValueAvoided,
    pricingAssumption: runtime.institutionalKpis?.pricingAssumption,
    compliancePosture: runtime.institutionalKpis?.compliancePosture,
    evidenceCompleteness: runtime.institutionalKpis?.evidenceCompleteness,
    portfolioCoverage: runtime.institutionalKpis?.portfolioCoverage,
    plannedWater: rec.depth,
    recommendation: rec.action || rec.decision,
    scheduledAction: runtime.operatingChain[1]?.evidence || "Awaiting schedule",
    appliedAction: runtime.operatingChain[2]?.evidence || "Awaiting controller execution",
    observedOutcome: runtime.operatingChain[3]?.evidence || "Awaiting field observation",
    verificationStatus: runtime.operatingChain[4]?.status || "Verification pending",
    confidence: rec.confidence,
    dataQuality: rec.dataQuality,
    keyDrivers: rec.keyDrivers || rec.key_drivers || [],
    waterEfficiencyNote: "Decision supports targeted water application and verification evidence.",
  };
}

// Apply a representative evaluation workspace and produce a ready decision so the
// Command page is immediately functional. Always marked as representative data.
export function applyWorkspaceScenario(runtime, key) {
  const scenario = workspaceScenarios[key] || workspaceScenarios["alpha-vineyard"];
  runtime.workspaceScenarioId = scenario.id;
  runtime.activeFarm = findFarm(scenario.farmId);
  runtime.activeZone = findZone(runtime.activeFarm, scenario.zoneId);
  runtime.activeRecommendation = { ...scenario.recommendation, generatedAt: now() };
  runtime.reconciliationRows = scenario.reconciliation;
  runtime.institutionalKpis = {
    ...demoInstitutionalKpis,
    ...(runtime.institutionalKpis || {}),
    waterSavingsRate: scenario.savings,
    evidenceCompleteness: scenario.evidence,
  };
  runtime.intakeMode = runtime.intakeMode || "sample";
  runtime.intakeModeLabel = "Representative data";
  runtime.analysis = {
    ...runtime.analysis,
    status: "complete",
    running: false,
    statusLabel: "Decision ready",
    backendError: "",
    steps: getAnalysisSteps().map((step) => ({ ...step, status: "complete", statusLabel: "Complete", detail: "Source reconciliation complete" })),
  };
  runtime.operatingChain = baseChain("recommended");
  runtime.operatingChain[0] = { ...runtime.operatingChain[0], evidence: "Representative-data analysis produced a verified water decision." };
  runtime.reportSnapshots = [reportSnapshotFromActiveRecommendation(runtime), ...(runtime.reportSnapshots || [])].slice(0, 12);
  addAudit(runtime, "Workspace scenario loaded", `${scenario.name} representative records loaded.`, scenario.name);
  return persist(runtime);
}

export function loadRepresentativePackage(runtime) {
  runtime.intakeMode = "sample";
  runtime.intakeModeLabel = "Representative data";
  return applyWorkspaceScenario(runtime, runtime.workspaceScenarioId || "alpha-vineyard");
}

export function switchWorkspaceScenario(runtime, key) {
  return applyWorkspaceScenario(runtime, key);
}

export function markBackendUnavailable(runtime, message = "Backend intelligence unavailable. Representative-data analysis remains available.") {
  runtime.analysis.running = false;
  runtime.analysis.status = runtime.activeRecommendation ? "complete" : "idle";
  runtime.analysis.backendError = message;
  runtime.analysis.statusLabel = message;
  addAudit(runtime, "Backend intelligence unavailable", message, runtime.intakeModeLabel || "Water Command Center");
  return persist(runtime);
}
