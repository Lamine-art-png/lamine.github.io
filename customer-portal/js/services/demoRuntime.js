import { demoAuditLog, demoFarms, demoRecommendation, demoWorkspace } from "../demoData.js";

const STORAGE_KEY = "AGROAI_DEMO_RUNTIME_QUANT_V1";
const ACTOR = "Demo Farm Manager";

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
      recommendationHeadline: "Hold irrigation · reassess 07:00 PT",
      recommendationSubline: "0 mm net across Block A North · rain forecast offsets ETo 4.1 mm and 18% deficit at 30 cm.",
      decision: "Hold irrigation · reassess 07:00 PT",
      timing: "07:00 PT",
      duration: "0 min",
      depth: "0 mm net",
      depthMm: 0,
      durationMin: 0,
      startTimeLocal: "07:00 PT",
      etoMm: 4.1,
      deficit30cm: "18%",
      confidence: "82%",
      confidenceScore: 82,
      dataQuality: "Verified telemetry",
      dataQualityLabel: "Verified telemetry",
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
      recommendationHeadline: "Irrigate 28 min tonight · start 22:00 PT",
      recommendationSubline: "8 mm net across Block A North · responding to ETo 5.7 mm and 31% deficit at 30 cm with partial telemetry.",
      decision: "Irrigate 28 min tonight · start 22:00 PT",
      timing: "22:00 PT",
      duration: "28 min",
      depth: "8 mm net",
      depthMm: 8,
      durationMin: 28,
      startTimeLocal: "22:00 PT",
      etoMm: 5.7,
      deficit30cm: "31%",
      confidence: "68%",
      confidenceScore: 68,
      dataQuality: "Partial telemetry",
      dataQualityLabel: "Partial telemetry",
      keyDrivers: ["Recent irrigation history available", "One moisture sensor stale", "Field observation requested"],
      missingInputs: ["One moisture sensor missing recent reading"],
      executionTask: "Schedule conservative irrigation and request sensor check.",
    },
  },
  mismatch: {
    id: "mismatch",
    name: "Planned vs applied mismatch",
    note: "Controller application differs from planned duration; verification flags follow-up.",
    recommendation: {
      ...demoRecommendation,
      recommendationHeadline: "Irrigate 36 min tonight · start 21:30 PT",
      recommendationSubline: "10 mm net across Block A North · responding to ETo 6.0 mm and 35% deficit at 30 cm with verification watch.",
      decision: "Irrigate 36 min tonight · start 21:30 PT",
      timing: "21:30 PT",
      duration: "36 min",
      depth: "10 mm net",
      depthMm: 10,
      durationMin: 36,
      startTimeLocal: "21:30 PT",
      etoMm: 6.0,
      deficit30cm: "35%",
      confidence: "79%",
      confidenceScore: 79,
      dataQuality: "Controller variance watch",
      dataQualityLabel: "Controller variance watch",
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
      confidenceScore: 91,
      dataQuality: "Verified telemetry",
      dataQualityLabel: "Verified telemetry",
      verificationPlan: "Controller event and field observation confirm expected outcome.",
    },
  },
};

function now() {
  return new Date().toISOString();
}

function findFarm(farmId) {
  return demoFarms.find((farm) => farm.id === farmId) || demoFarms[0];
}

function findZone(farm, zoneId) {
  return farm.zones.find((zone) => zone.id === zoneId) || farm.zones[0];
}

function baseChain(active = "recommended") {
  const labels = ["Recommended", "Scheduled", "Applied", "Observed", "Verified"];
  const keys = ["recommended", "scheduled", "applied", "observed", "verified"];
  return keys.map((key, index) => ({
    key,
    label: labels[index],
    status: key === active ? "Active" : "Pending",
    timestamp: key === "recommended" ? now() : "",
    owner: key === "recommended" ? "AGRO-AI Intelligence Engine" : ACTOR,
    evidence: key === "recommended" ? "Recommendation ready for review." : `${labels[index]} pending`,
    note: "Demo runtime state",
  }));
}

function addAudit(runtime, event, detail, source = runtime.activeZone?.name || "Demo Workspace") {
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
    if (stored) return JSON.parse(stored);
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
    operatingChain: baseChain("recommended"),
    auditEvents: [...demoAuditLog],
    reportSnapshots: [],
    scenario: scenarios.dry_day,
    currentStep: 0,
    guideStarted: false,
    toast: "",
  };
  addAudit(runtime, "Demo workspace launched", "Demo runtime reset and ready.");
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
  addAudit(runtime, "Zone selected", `${runtime.activeZone.name} selected.`, runtime.activeZone.name);
  return persist(runtime);
}

export function switchScenario(runtime, scenarioId) {
  runtime.scenario = scenarios[scenarioId] || scenarios.dry_day;
  runtime.activeRecommendation = null;
  runtime.operatingChain = baseChain("recommended");
  runtime.currentStep = 1;
  addAudit(runtime, "Scenario selected", runtime.scenario.name);
  return persist(runtime);
}

export function startGuidedDemo(runtime) {
  runtime.guideStarted = true;
  runtime.currentStep = 1;
  addAudit(runtime, "Guided demo started", "Sales demo guide activated.");
  return persist(runtime);
}

export function generateDemoRecommendation(runtime) {
  runtime.activeRecommendation = {
    ...runtime.scenario.recommendation,
    generatedAt: now(),
    sourceTraceSummary: `${runtime.scenario.note} Context assembled from ${runtime.activeZone.controllerSource}, crop profile, soil profile, weather, and field observation.`,
  };
  runtime.operatingChain = baseChain("scheduled");
  runtime.currentStep = 2;
  addAudit(runtime, "Recommendation generated", runtime.activeRecommendation.recommendationHeadline || runtime.activeRecommendation.decision);
  return persist(runtime);
}

export function scheduleRecommendation(runtime) {
  runtime.operatingChain[0] = { ...runtime.operatingChain[0], status: "Complete", evidence: "Recommendation accepted for schedule." };
  runtime.operatingChain[1] = { ...runtime.operatingChain[1], status: "Complete", timestamp: now(), evidence: "Irrigation scheduled in demo controller window.", owner: ACTOR };
  runtime.currentStep = 3;
  addAudit(runtime, "Recommendation scheduled", "Schedule created for selected block.");
  return persist(runtime);
}

export function markApplied(runtime) {
  runtime.operatingChain[2] = { ...runtime.operatingChain[2], status: "Complete", timestamp: now(), evidence: runtime.scenario.id === "mismatch" ? "Applied water confirmed with duration variance." : "Applied water confirmed from controller event.", owner: ACTOR };
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
  runtime.operatingChain[4] = { ...runtime.operatingChain[4], status: "Complete", timestamp: now(), evidence: runtime.scenario.id === "mismatch" ? "Verification flagged planned-vs-applied mismatch for review." : "Outcome verified against controller event and observation.", owner: "AGRO-AI Verification" };
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
    recommendation: rec.recommendationHeadline || rec.decision,
    recommendationDepth: rec.depth || `${rec.depthMm} mm net`,
    recommendationDuration: rec.duration || `${rec.durationMin} min`,
    recommendationTiming: rec.startTimeLocal || rec.timing,
    recommendationReason: rec.recommendationSubline,
    scheduledAction: runtime.operatingChain[1]?.evidence || "Awaiting schedule",
    appliedAction: runtime.operatingChain[2]?.evidence || "Awaiting controller execution",
    observedOutcome: runtime.operatingChain[3]?.evidence || "Awaiting field observation",
    verificationStatus: runtime.operatingChain[4]?.status || "Verification pending",
    confidence: rec.confidence || `${rec.confidenceScore}%`,
    dataQuality: rec.dataQualityLabel || rec.dataQuality,
    keyDrivers: rec.keyDrivers || [],
    waterEfficiencyNote: runtime.scenario.id === "rain_wait" ? "Avoided unnecessary irrigation ahead of rainfall." : "Decision supports targeted water application and verification evidence.",
  };
  runtime.reportSnapshots = [snapshot, ...(runtime.reportSnapshots || [])].slice(0, 12);
  runtime.currentStep = 7;
  addAudit(runtime, "Report generated", `${type} preview generated.`, snapshot.block);
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
