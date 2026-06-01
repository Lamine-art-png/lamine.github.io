import { useSyncExternalStore } from "react";
import { apiClient } from "../api/client";
import { probeBackend } from "../api/health";
import { loadRuntimeStatuses } from "../api/runtimeStatus";
import type {
  AnalysisMode,
  BackendStatus,
  Decision,
  EvidenceStep,
  ReconciliationRow,
  RecommendationOrigin,
  ProviderStatus,
  SourceRow,
  TraceStep,
  WorkbenchAnalysisResult,
} from "../api/contracts";

export type ScenarioId = "alpha-vineyard" | "almond-orchard" | "multi-farm" | "partner-validation";
export type Route = "command" | "sources" | "reports" | "integrations" | "audit" | "settings";

export interface ReportModel {
  farm: string;
  block: string;
  recommendation: string;
  plannedWater: string;
  appliedWater: string;
  variance: string;
  evidenceCompleteness: string;
  estimatedWaterSavings: string;
  verification: string;
}

export interface UploadedFileState {
  name: string;
  detectedType: string;
  parseStatus: string;
  rows: string;
  fields: string;
  warnings: string;
}

export interface AuditEvent {
  time: string;
  actor: string;
  event: string;
  detail: string;
}

export interface CommandState {
  entryState: "entry" | "workspace";
  onboardingOpen: boolean;
  productionSignInMessage: string | null;
  walkthroughActive: boolean;
  walkthroughStep: number;
  route: Route;
  backend: { status: BackendStatus; detail: string; checkedAt: string };
  sessionId: string | null;
  providerStatuses: ProviderStatus[];
  providerStatusPhase: "idle" | "loading" | "ready" | "error";
  scenarioId: ScenarioId;
  analysisMode: AnalysisMode;
  analysisPhase: "idle" | "running" | "complete" | "error";
  pipelineMessage: string;
  recommendationOrigin: RecommendationOrigin;
  decision: Decision;
  sources: SourceRow[];
  reconciliation: ReconciliationRow[];
  trace: TraceStep[];
  evidence: EvidenceStep[];
  report: ReportModel;
  toast: string | null;
  drawerOpen: boolean;
  uploaded: UploadedFileState | null;
  audit: AuditEvent[];
}

// ---------------------------------------------------------------------------
// Representative scenarios (clearly marked as representative data in the UI).
// ---------------------------------------------------------------------------

interface Scenario {
  id: ScenarioId;
  name: string;
  liveEntity: { source: string; entityId: string };
  decision: Omit<Decision, "recommendationOrigin">;
  sources: SourceRow[];
  reconciliation: ReconciliationRow[];
  report: ReportModel;
}

const REP_SOURCES_ALPHA: SourceRow[] = [
  { source: "Controller history", latestSignal: "Last irrigation event: 36 min", records: "1,248", contribution: "+0.22", status: "Matched" },
  { source: "Weather demand", latestSignal: "ETo 6.4 mm, rain 0 mm", records: "336", contribution: "+0.18", status: "Matched" },
  { source: "Soil moisture", latestSignal: "38% deficit at 30 cm", records: "412", contribution: "+0.17", status: "Matched" },
  { source: "Flow meter", latestSignal: "Actual flow within 8% of plan", records: "298", contribution: "+0.11", status: "Matched" },
  { source: "Field observation", latestSignal: "Mild afternoon stress", records: "26", contribution: "+0.09", status: "Matched" },
  { source: "Earth observation layer", latestSignal: "Elevated canopy stress index", records: "84", contribution: "+0.09", status: "Matched" },
  { source: "Uploaded records", latestSignal: "Awaiting CSV, XLSX, JSON, or TXT", records: "0", contribution: "Pending", status: "Pending" },
];

function recon(rows: [string, string, string, ReconciliationRow["status"]][]): ReconciliationRow[] {
  return rows.map(([source, signal, interpretation, status]) => ({ source, signal, interpretation, status }));
}

const SCENARIOS: Record<ScenarioId, Scenario> = {
  "alpha-vineyard": {
    id: "alpha-vineyard",
    name: "Alpha Vineyard",
    liveEntity: { source: "wiseconn", entityId: "162803" },
    decision: {
      action: "Irrigate 42 min tonight",
      start: "21:00 PT",
      appliedWater: "12 mm net",
      crop: "Cabernet Sauvignon",
      block: "Block A North",
      driver: "ETo 6.4 mm and 38% root-zone deficit",
      confidence: "86%",
      evidenceCompleteness: "92%",
      estimatedWaterSavings: "27%",
      verification: "Required",
    },
    sources: REP_SOURCES_ALPHA,
    reconciliation: recon([
      ["Controller history", "Last irrigation event: 36 min", "Valid recent controller event", "Matched"],
      ["Weather demand", "ETo 6.4 mm, rain 0 mm", "High water demand", "Matched"],
      ["Soil moisture", "38% deficit at 30 cm", "Root-zone deficit supports irrigation", "Matched"],
      ["Flow meter", "Actual flow within 8% of plan", "Applied water consistent", "Matched"],
      ["Field observation", "Mild afternoon stress", "Supports irrigation recommendation", "Matched"],
      ["Earth observation layer", "Elevated canopy stress index", "Supports water demand signal", "Matched"],
      ["Talgil", "Runtime reachable, no selected production target", "Integration available, target selection pending", "Pending target"],
    ]),
    report: {
      farm: "Alpha Vineyard",
      block: "Block A North",
      recommendation: "Irrigate 42 min tonight",
      plannedWater: "12 mm net",
      appliedWater: "Pending confirmation",
      variance: "Within 8%",
      evidenceCompleteness: "92%",
      estimatedWaterSavings: "27% vs historical baseline",
      verification: "Required",
    },
  },
  "almond-orchard": {
    id: "almond-orchard",
    name: "Almond Orchard",
    liveEntity: { source: "wiseconn", entityId: "204411" },
    decision: {
      action: "Apply 18 mm before 05:00",
      start: "03:15 local",
      appliedWater: "18 mm net",
      crop: "Almonds",
      block: "Almond Block 4",
      driver: "ETo 6.5 mm and 42% root-zone deficit",
      confidence: "91%",
      evidenceCompleteness: "94%",
      estimatedWaterSavings: "31%",
      verification: "Required",
    },
    sources: [
      { source: "Controller history", latestSignal: "Last set 55 min, mild applied variance", records: "980", contribution: "+0.21", status: "Matched" },
      { source: "Weather demand", latestSignal: "ETo 6.5 mm, rain 0 mm", records: "288", contribution: "+0.19", status: "Matched" },
      { source: "Soil moisture", latestSignal: "42% deficit at 30 cm", records: "366", contribution: "+0.18", status: "Matched" },
      { source: "Flow meter", latestSignal: "Prior set +12.3% over plan", records: "212", contribution: "+0.08", status: "Review" },
      { source: "Field observation", latestSignal: "Mild leaf curl, southwest corner", records: "18", contribution: "+0.08", status: "Matched" },
      { source: "Earth observation layer", latestSignal: "Vegetation stress index 0.52", records: "60", contribution: "+0.10", status: "Matched" },
      { source: "Uploaded records", latestSignal: "Awaiting CSV, XLSX, JSON, or TXT", records: "0", contribution: "Pending", status: "Pending" },
    ],
    reconciliation: recon([
      ["Controller history", "Last set 55 min, mild applied variance", "Valid controller event", "Matched"],
      ["Weather demand", "ETo 6.5 mm, rain 0 mm", "High water demand", "Matched"],
      ["Soil moisture", "42% deficit at 30 cm", "Root-zone deficit supports irrigation", "Matched"],
      ["Flow meter", "Prior set +12.3% over plan", "Applied-water variance flagged", "Review"],
      ["Field observation", "Mild leaf curl at southwest corner", "Supports irrigation recommendation", "Matched"],
      ["Earth observation layer", "Vegetation stress index 0.52", "Supports water demand signal", "Matched"],
      ["Talgil", "Not used for this orchard", "WiseConn-managed orchard", "Pending target"],
    ]),
    report: {
      farm: "Delta Almonds",
      block: "Almond Block 4",
      recommendation: "Apply 18 mm before 05:00",
      plannedWater: "18 mm net",
      appliedWater: "Pending confirmation",
      variance: "Prior set +12.3%",
      evidenceCompleteness: "94%",
      estimatedWaterSavings: "31% vs historical baseline",
      verification: "Required",
    },
  },
  "multi-farm": {
    id: "multi-farm",
    name: "Multi-Farm Portfolio",
    liveEntity: { source: "wiseconn", entityId: "162803" },
    decision: {
      action: "3 blocks irrigate tonight, 1 hold",
      start: "Tonight, staggered windows",
      appliedWater: "12–18 mm net",
      crop: "Mixed (vineyard + almond)",
      block: "4 active blocks",
      driver: "Portfolio root-zone deficit across 3 of 4 blocks",
      confidence: "88%",
      evidenceCompleteness: "90%",
      estimatedWaterSavings: "26%",
      verification: "Required",
    },
    sources: [
      { source: "Controller history", latestSignal: "12 controller events across 3 farms", records: "3,140", contribution: "+0.20", status: "Matched" },
      { source: "Weather demand", latestSignal: "ETo 6.0–6.8 mm by region", records: "910", contribution: "+0.18", status: "Matched" },
      { source: "Soil moisture", latestSignal: "Deficit 28–44% by block", records: "1,120", contribution: "+0.16", status: "Matched" },
      { source: "Flow meter", latestSignal: "One block over plan, others in range", records: "744", contribution: "+0.10", status: "Review" },
      { source: "Field observation", latestSignal: "Stress notes on 2 blocks", records: "52", contribution: "+0.08", status: "Matched" },
      { source: "Earth observation layer", latestSignal: "Elevated stress on vineyard blocks", records: "168", contribution: "+0.09", status: "Matched" },
      { source: "Uploaded records", latestSignal: "Awaiting CSV, XLSX, JSON, or TXT", records: "0", contribution: "Pending", status: "Pending" },
    ],
    reconciliation: recon([
      ["Controller history", "12 controller events across 3 farms", "Recent events validated", "Matched"],
      ["Weather demand", "ETo 6.0–6.8 mm by region", "High demand in 3 of 4 blocks", "Matched"],
      ["Soil moisture", "Deficit 28–44% by block", "Mixed deficit, one block adequate", "Matched"],
      ["Flow meter", "One block over plan, others in range", "Applied-water variance localized", "Review"],
      ["Field observation", "Stress notes on 2 blocks", "Supports irrigation in those blocks", "Matched"],
      ["Earth observation layer", "Elevated stress on vineyard blocks", "Supports water demand signal", "Matched"],
      ["Talgil", "North Ridge runtime reachable", "Target selection pending", "Pending target"],
    ]),
    report: {
      farm: "Portfolio (3 farms)",
      block: "4 active blocks",
      recommendation: "3 blocks irrigate tonight, 1 hold",
      plannedWater: "12–18 mm net",
      appliedWater: "Pending confirmation",
      variance: "Localized to 1 block",
      evidenceCompleteness: "90%",
      estimatedWaterSavings: "26% vs historical baseline",
      verification: "Required",
    },
  },
  "partner-validation": {
    id: "partner-validation",
    name: "Partner Data Validation",
    liveEntity: { source: "talgil", entityId: "trial-11" },
    decision: {
      action: "Validate partner feed before scheduling",
      start: "Pending partner feed authorization",
      appliedWater: "Awaiting validation",
      crop: "Trial vineyard",
      block: "Vineyard Block Trial",
      driver: "Partner feed ingested as representative data; pressure coverage partial",
      confidence: "73%",
      evidenceCompleteness: "78%",
      estimatedWaterSavings: "—",
      verification: "Partner feed authorization required for production use",
    },
    sources: [
      { source: "Controller history", latestSignal: "Talgil trial rows ingested", records: "210", contribution: "+0.14", status: "Matched" },
      { source: "Weather demand", latestSignal: "ETo within seasonal range", records: "120", contribution: "+0.12", status: "Matched" },
      { source: "Soil moisture", latestSignal: "Partial sensor coverage", records: "64", contribution: "+0.06", status: "Review" },
      { source: "Flow meter", latestSignal: "Prior set variance +23%", records: "40", contribution: "Review", status: "Review" },
      { source: "Field observation", latestSignal: "Trial rows watched separately", records: "12", contribution: "+0.05", status: "Matched" },
      { source: "Earth observation layer", latestSignal: "Partner-provided sample layer", records: "30", contribution: "Pending", status: "Pending target" },
      { source: "Uploaded records", latestSignal: "Awaiting CSV, XLSX, JSON, or TXT", records: "0", contribution: "Pending", status: "Pending" },
    ],
    reconciliation: recon([
      ["Controller history", "Talgil trial rows ingested", "Trial block, separated from commercial", "Matched"],
      ["Weather demand", "ETo within seasonal range", "Demand evaluated", "Matched"],
      ["Soil moisture", "Partial sensor coverage", "Coverage gap flagged", "Review"],
      ["Flow meter", "Prior set variance +23%", "Applied-water variance flagged", "Review"],
      ["Field observation", "Trial rows watched separately", "Supports cautious recommendation", "Matched"],
      ["Earth observation layer", "Partner-provided sample layer", "Representative until authorized", "Pending target"],
      ["Talgil", "Runtime reachable, trial target", "Production authorization required", "Pending target"],
    ]),
    report: {
      farm: "West Citrus",
      block: "Vineyard Block Trial",
      recommendation: "Validate partner feed before scheduling",
      plannedWater: "Awaiting validation",
      appliedWater: "Awaiting validation",
      variance: "Partner feed unverified",
      evidenceCompleteness: "78%",
      estimatedWaterSavings: "—",
      verification: "Partner feed authorization required for production use",
    },
  },
};

export const SCENARIO_OPTIONS = Object.values(SCENARIOS).map((s) => ({ id: s.id, name: s.name }));

// ---------------------------------------------------------------------------
// Trace + evidence builders
// ---------------------------------------------------------------------------

const TRACE_TITLES: { title: string; detail: string; records: number }[] = [
  { title: "Source records ingested", detail: "Controller, weather, soil, flow, observation, and earth-observation records collected", records: 2404 },
  { title: "Schema detected", detail: "Field schemas and aliases mapped to the canonical model", records: 8 },
  { title: "Units normalized", detail: "Units, timestamps, and identifiers standardized", records: 2404 },
  { title: "Field context assembled", detail: "Farm, block, crop, soil, and irrigation context assembled", records: 1 },
  { title: "Source conflicts reconciled", detail: "Planned vs applied water and cross-source signals reconciled", records: 7 },
  { title: "Confidence scored", detail: "Evidence completeness and confidence computed", records: 1 },
  { title: "Recommendation prepared", detail: "Operational recommendation and timing prepared", records: 1 },
  { title: "Verification plan prepared", detail: "Recommended → Scheduled → Applied → Observed → Verified", records: 5 },
];

function buildTrace(now: string, complete: boolean): TraceStep[] {
  return TRACE_TITLES.map((t) => ({
    title: t.title,
    status: complete ? "complete" : "pending",
    recordsProcessed: t.records,
    detail: t.detail,
    timestamp: complete ? now : "—",
  }));
}

const EVIDENCE_TYPES_UI: Record<EvidenceStep["key"], string> = {
  recommended: "system_generated",
  scheduled: "operator_attestation",
  applied: "operator_attestation",
  observed: "field_observation",
  verified: "operator_attestation",
};

function baseEvidence(now: string): EvidenceStep[] {
  const steps: Array<[EvidenceStep["key"], string, string]> = [
    ["recommended", "Recommended", "AGRO-AI Intelligence Engine"],
    ["scheduled", "Scheduled", "Operations user"],
    ["applied", "Applied", "Operations user"],
    ["observed", "Observed", "Operations user"],
    ["verified", "Verified", "AGRO-AI Verification"],
  ];
  return steps.map(([key, label, owner], i) => ({
    key,
    label,
    owner,
    status: i === 0 ? "Complete" : "Pending",
    timestamp: i === 0 ? now : "",
    evidence: i === 0 ? "Verified water decision produced from current source set." : `${label} pending`,
    evidenceType: i === 0 ? "system_generated" : undefined,
  }));
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

function scenarioState(id: ScenarioId, mode: AnalysisMode, origin: RecommendationOrigin): Partial<CommandState> {
  const sc = SCENARIOS[id];
  const now = new Date().toISOString();
  return {
    scenarioId: id,
    analysisMode: mode,
    analysisPhase: "complete",
    recommendationOrigin: origin,
    pipelineMessage: "Decision refreshed",
    decision: { ...sc.decision, recommendationOrigin: origin },
    sources: sc.sources,
    reconciliation: sc.reconciliation,
    trace: buildTrace(now, true),
    evidence: baseEvidence(now),
    report: sc.report,
  };
}

function initialState(): CommandState {
  const seeded = scenarioState("alpha-vineyard", "representative", "representative_fallback");
  return {
    ...seeded,
    entryState: "entry",
    onboardingOpen: false,
    productionSignInMessage: null,
    walkthroughActive: false,
    walkthroughStep: 0,
    route: "command",
    backend: { status: "limited", detail: "Checking backend…", checkedAt: "" },
    sessionId: null,
    providerStatuses: [],
    providerStatusPhase: "idle",
    toast: null,
    drawerOpen: false,
    uploaded: null,
    audit: [{ time: new Date().toISOString(), actor: "Operations user", event: "Workspace launched", detail: "Representative package loaded." }],
  } as CommandState;
}

let state: CommandState = initialState();
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function set(patch: Partial<CommandState>) {
  state = { ...state, ...patch };
  emit();
}

function addAudit(event: string, detail: string) {
  const entry: AuditEvent = { time: new Date().toISOString(), actor: "Operations user", event, detail };
  set({ audit: [entry, ...state.audit].slice(0, 60) });
}

function toast(message: string) {
  set({ toast: message });
  setTimeout(() => {
    if (state.toast === message) set({ toast: null });
  }, 3200);
}

// ---- Backend mapping ------------------------------------------------------

function pct(value: unknown, fallback: string): string {
  if (typeof value === "number") return value <= 1 ? `${Math.round(value * 100)}%` : `${Math.round(value)}%`;
  if (typeof value === "string" && value.trim()) return value;
  return fallback;
}

function applyBackendResult(result: WorkbenchAnalysisResult, mode: AnalysisMode) {
  const sc = SCENARIOS[state.scenarioId];
  const rec = (result.recommendation ?? {}) as Record<string, unknown>;
  const summary = (result.report_summary ?? {}) as Record<string, unknown>;
  const origin: RecommendationOrigin = result.recommendation_origin ?? (mode === "live" ? "live_intelligence_engine" : "deterministic_engine");
  const now = new Date().toISOString();

  // Only inherit representative scenario values when the engine explicitly signals
  // a representative fallback. For live, uploaded, and deterministic results use
  // honest "pending" labels so representative precision cannot leak into a real result.
  const useRepresentative = origin === "representative_fallback";

  const action = (rec.action as string) || (rec.decision as string) || (summary.recommendation as string) || (useRepresentative ? sc.decision.action : "Decision pending source review");
  const decision: Decision = {
    action,
    start: (rec.start_time as string) || (rec.timing as string) || (useRepresentative ? sc.decision.start : "Pending evidence"),
    appliedWater: (rec.depth as string) || (summary.planned_water as string) || (useRepresentative ? sc.decision.appliedWater : "Withheld pending validation"),
    grossWater: (rec.gross_depth as string) || undefined,
    estimatedVolume: (rec.estimated_volume as string) || undefined,
    duration: (rec.duration as string) || (rec.no_fabricated_duration ? "Withheld until flow is validated" : (useRepresentative ? undefined : "Withheld pending validation")),
    crop: (rec.crop as string) || (useRepresentative ? sc.decision.crop : "Source context incomplete"),
    block: (rec.block as string) || (useRepresentative ? sc.decision.block : "Source context incomplete"),
    driver: Array.isArray(rec.key_drivers) && rec.key_drivers.length ? String((rec.key_drivers as unknown[])[0]) : (useRepresentative ? sc.decision.driver : "Tenant baseline required"),
    confidence: pct(rec.confidence ?? summary.confidence, useRepresentative ? sc.decision.confidence : "—"),
    evidenceCompleteness: pct(result.reconciliation?.evidence_completeness ?? summary.evidence_completeness, useRepresentative ? sc.decision.evidenceCompleteness : "—"),
    estimatedWaterSavings: useRepresentative ? sc.decision.estimatedWaterSavings : "—",
    verification: (rec.verification_requirement as string) || (useRepresentative ? sc.decision.verification : "Required"),
    recommendationOrigin: origin,
    calibrationStatus: (rec.calibration_status as string) || undefined,
    calibrationPackVersion: (rec.calibration_pack_version as string) || undefined,
    verificationStatus: "Required",
  };

  const trace: TraceStep[] = Array.isArray(result.analysis_trace) && result.analysis_trace.length
    ? result.analysis_trace.map((t) => ({
        title: t.title,
        status: t.status === "review" ? "review" : "complete",
        recordsProcessed: t.objects_processed ?? 0,
        detail: t.details ?? "",
        timestamp: now,
      }))
    : buildTrace(now, true);

  set({
    analysisMode: mode,
    analysisPhase: "complete",
    recommendationOrigin: origin,
    pipelineMessage: "Decision refreshed",
    decision,
    trace,
    evidence: baseEvidence(now),
    report: { ...sc.report, recommendation: action, plannedWater: decision.grossWater || decision.appliedWater, evidenceCompleteness: decision.evidenceCompleteness },
  });
}

// ---- Public actions -------------------------------------------------------

export const actions = {
  async init() {
    const health = await probeBackend();
    set({ backend: { status: health.status, detail: health.detail, checkedAt: health.checkedAt } });
    void actions.refreshProviderStatuses();
  },

  async openEvaluationWorkspace() {
    set({
      entryState: "workspace",
      productionSignInMessage: null,
      analysisPhase: "running",
      pipelineMessage: "Loading representative source package…",
      trace: buildTrace(new Date().toISOString(), false),
    });
    addAudit("Evaluation workspace opened", "Representative package analysis started for sales-call evaluation.");
    if (state.backend.status !== "unavailable") {
      try {
        const sample = await apiClient.createSamplePackage();
        const sessionId = sample.data?.session?.session_id || sample.data?.session_id || "";
        if (sample.ok && sessionId) {
          set({ sessionId, pipelineMessage: "Analyzing representative source package…" });
          addAudit("Evaluation session created", "Backend evaluation-session persistence enabled.");
          const analysis = await apiClient.analyzeSession(sessionId);
          if (analysis.ok && analysis.data) {
            applyBackendResult(analysis.data, "representative");
            addAudit("Representative package analyzed", "Decision, evidence chain, reconciliation, and report preview populated.");
            toast("Evaluation workspace ready.");
            return;
          }
        }
      } catch {
        // Falls through to the honest representative fallback.
      }
    }
    set(scenarioState(state.scenarioId, "representative", "representative_fallback"));
    set({ pipelineMessage: "Backend analysis unavailable. Representative fallback is active." });
    addAudit("Representative fallback active", "Backend analysis failed or was unavailable; local representative records remain loaded.");
    toast("Workspace opened with representative fallback.");
  },

  submitProductionSignIn() {
    set({ productionSignInMessage: "Production identity provisioning is required for this workspace." });
  },

  openOnboarding() {
    set({ onboardingOpen: true });
  },

  closeOnboarding() {
    set({ onboardingOpen: false });
  },

  startWalkthrough() {
    set({ walkthroughActive: true, walkthroughStep: 0 });
  },

  resetWalkthrough() {
    set({ walkthroughActive: false, walkthroughStep: 0 });
  },

  nextWalkthrough() {
    if (state.walkthroughStep >= 4) {
      set({ walkthroughActive: false, walkthroughStep: 0 });
    } else {
      set({ walkthroughStep: state.walkthroughStep + 1 });
    }
  },

  async refreshProviderStatuses() {
    set({ providerStatusPhase: "loading" });
    try {
      const providerStatuses = await loadRuntimeStatuses();
      set({ providerStatuses, providerStatusPhase: "ready" });
    } catch {
      set({ providerStatusPhase: "error" });
    }
  },

  navigate(route: Route) {
    set({ route });
  },

  switchScenario(id: ScenarioId) {
    set(scenarioState(id, "representative", "representative_fallback"));
    addAudit("Workspace scenario loaded", `${SCENARIOS[id].name} representative records loaded.`);
    toast(`${SCENARIOS[id].name} loaded`);
  },

  async refreshIntelligence() {
    if (state.analysisPhase === "running") return;
    set({ analysisPhase: "running", pipelineMessage: "Analyzing source records…", trace: buildTrace(new Date().toISOString(), false) });
    addAudit("Intelligence analysis started", `Mode: ${state.analysisMode}.`);

    // Prefer a real backend result when reachable; otherwise representative.
    let result: WorkbenchAnalysisResult | null = null;
    if (state.backend.status !== "unavailable") {
      try {
        const sc = SCENARIOS[state.scenarioId];
        const res = await apiClient.analyzeLive(sc.liveEntity.source, sc.liveEntity.entityId);
      if (res.ok && res.data) result = res.data;
      } catch {
        result = null;
      }
    }

    // brief pause so the pipeline animation is legible
    await new Promise((r) => setTimeout(r, 900));

    if (result) {
      set({ sessionId: result.session_id || state.sessionId });
      applyBackendResult(result, "live");
      addAudit("Intelligence analysis completed", "Live Workbench result applied.");
      toast("Analysis complete. Decision ready.");
    } else {
      set(scenarioState(state.scenarioId, "representative", "representative_fallback"));
      set({ pipelineMessage: "Backend unavailable. Representative analysis remains active." });
      addAudit("Intelligence analysis completed", "Representative-data analysis applied.");
      toast("Representative analysis refreshed.");
    }
  },

  async uploadRecords(file: File) {
    // Optimistically surface the file so the drawer always shows status.
    set({
      pipelineMessage: "Analyzing source records…",
      analysisPhase: "running",
      uploaded: { name: file.name, detectedType: detectType(file.name), parseStatus: "Uploading…", rows: "—", fields: "—", warnings: "—" },
    });
    let sessionId = "";
    const created = await apiClient.createSession("uploaded");
    if (created.ok) sessionId = created.data?.session_id || created.data?.session?.session_id || "";
    if (!sessionId) {
      set({ analysisPhase: "complete", pipelineMessage: "Backend unavailable. Representative analysis remains active." });
      set({ uploaded: { name: file.name, detectedType: detectType(file.name), parseStatus: "Backend upload endpoint unavailable", rows: "—", fields: "—", warnings: "Representative analysis remains active." } });
      toast("Backend upload unavailable. Representative analysis remains active.");
      return;
    }
    set({ sessionId });
    const up = await apiClient.uploadFile(sessionId, file);
    if (up.ok && up.data) {
      const a = up.data;
      set({
        uploaded: {
          name: a.filename || file.name,
          detectedType: a.source_kind || detectType(file.name),
          parseStatus: a.parse_status || "parsed",
          rows: String(a.rows_detected ?? "—"),
          fields: Array.isArray(a.columns_detected) ? String(a.columns_detected.length) : "—",
          warnings: a.warnings?.length ? a.warnings.join("; ") : "None",
        },
      });
      const analysis = await apiClient.analyzeSession(sessionId);
      if (analysis.ok && analysis.data) {
        applyBackendResult(analysis.data, "uploaded");
        addAudit("Uploaded records analyzed", `${file.name} analyzed via Workbench.`);
        toast("Uploaded records analyzed.");
        return;
      }
    }
    set({ analysisPhase: "complete", pipelineMessage: "Backend unavailable. Representative analysis remains active." });
    toast("Upload analysis unavailable. Representative analysis remains active.");
  },

  openDrawer() {
    set({ drawerOpen: true });
  },
  closeDrawer() {
    set({ drawerOpen: false });
  },

  async advanceEvidence(key: EvidenceStep["key"]) {
    const order: EvidenceStep["key"][] = ["recommended", "scheduled", "applied", "observed", "verified"];
    const idx = order.indexOf(key);
    const now = new Date().toISOString();
    const evidenceText: Record<EvidenceStep["key"], string> = {
      recommended: "Verified water decision produced from current source set.",
      scheduled: "Schedule approval recorded.",
      applied: "Operator applied-water confirmation recorded.",
      observed: "Field observation recorded.",
      verified: "Outcome verification recorded for review.",
    };
    const evidence = state.evidence.map((step, i) =>
      i <= idx
        ? { ...step, status: "Complete" as const, timestamp: step.timestamp || now, evidence: evidenceText[step.key], evidenceType: EVIDENCE_TYPES_UI[step.key] }
        : step,
    );
    const backendAction: Record<EvidenceStep["key"], "schedule" | "applied" | "observe" | "verify" | null> = {
      recommended: null,
      scheduled: "schedule",
      applied: "applied",
      observed: "observe",
      verified: "verify",
    };
    const actionName = backendAction[key];
    if (state.sessionId && actionName && state.backend.status !== "unavailable") {
      const res = await apiClient.recordEvidenceAction(state.sessionId, actionName, evidenceText[key]);
      if (res.ok && res.data?.updated_evidence_chain) {
        set({ evidence: res.data.updated_evidence_chain });
        addAudit(`${order[idx]} recorded`, `Backend evidence action recorded in evaluation-session storage.`);
        toast(`${state.evidence[idx]?.label ?? "Step"} recorded`);
        return;
      }
      addAudit("Backend evidence action unavailable", "Local representative evidence fallback used.");
    }
    set({ evidence });
    addAudit(`${order[idx]} recorded`, evidenceText[key]);
    toast(`${state.evidence[idx]?.label ?? "Step"} recorded`);
  },

  dismissToast() {
    set({ toast: null });
  },
};

function detectType(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase();
  const map: Record<string, string> = { csv: "Tabular records (CSV)", xlsx: "Spreadsheet export (XLSX)", json: "Structured records (JSON)", txt: "Field notes (TXT)" };
  return (ext && map[ext]) || "Detected on upload";
}

// ---- React binding --------------------------------------------------------

export function useCommandStore<T>(selector: (s: CommandState) => T): T {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => selector(state),
    () => selector(state),
  );
}

export function getState(): CommandState {
  return state;
}

// Test seam: reset store to a clean initial state.
export function __resetForTest() {
  state = initialState();
  emit();
}
