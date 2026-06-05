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

export type ScenarioId = "alpha-vineyard" | "almond-orchard" | "multi-farm" | "partner-validation" | "incomplete-evidence";
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

export interface BackendMeta {
  normalizedContext: Record<string, unknown>;
  warnings: string[];
  uploadedArtifacts: string[];
  liveInputsUsed: string[];
  flowValidationNotes: string[];
  recentIrrigationCreditNotes: string[];
  baselineCalculationNote: string | null;
  baselineLabel: string | null;
  evaluationReferenceTime: string | null;
  sessionId: string | null;
  availableFarms: string[];
  availableBlocksByFarm: Record<string, string[]>;
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
  displayFarmName: string;
  backendMeta: BackendMeta | null;
  // Farm / block scope selectors
  selectedFarm: string | null;
  selectedBlock: string | null;
  availableFarms: string[];
  availableBlocksByFarm: Record<string, string[]>;
  scopeDefaulted: boolean;
  // Scope selection pending: true after farm selection until both are analyzed by the backend
  scopeSelectionPending: boolean;
  activeAnalyzedFarm: string | null;
  activeAnalyzedBlock: string | null;
  // Multi-file upload package tracking
  uploadedPackageSessionId: string | null;
  uploadedPackageArtifacts: UploadedFileState[];
}

// ---------------------------------------------------------------------------
// Representative scenarios (clearly marked as representative data in the UI).
// ---------------------------------------------------------------------------

interface Scenario {
  id: ScenarioId;
  name: string;
  customerName: string;
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
    customerName: "Validated operating block",
    liveEntity: { source: "wiseconn", entityId: "162803" },
    decision: {
      // Offline fallback — precision fields are withheld until backend analysis completes.
      action: "Irrigate Block A North — pending backend analysis for timing",
      start: "Pending — backend analysis required",
      appliedWater: "Pending — backend analysis required",
      grossWater: undefined,
      duration: undefined,
      estimatedVolume: undefined,
      area: "3.2 ha",
      irrigationMethod: "Drip",
      controller: "WiseConn evaluation connector",
      crop: "Cabernet Sauvignon",
      block: "Block A North",
      driver: "ETo · root-zone deficit · Canopy stress — backend analysis required for values",
      confidence: "—",
      evidenceCompleteness: "—",
      estimatedWaterSavings: "—",
      verification: "Required",
      calibrationStatus: "Calibrated v0.2 — transparent defaults",
      flowValidationState: "Pending analysis",
      // Scheduling requires backend analysis — not pre-set in representative fallback.
      schedulable: undefined,
    },
    sources: REP_SOURCES_ALPHA,
    reconciliation: recon([
      ["Controller history", "Last irrigation event: 36 min", "Valid recent controller event", "Matched"],
      ["Weather demand", "ETo within range — backend analysis required for values", "Water demand signal available", "Matched"],
      ["Soil moisture", "Root-zone deficit — backend analysis required for values", "Deficit signal supports irrigation", "Matched"],
      ["Flow meter", "Flow signal present — backend analysis required for values", "Flow evidence available", "Matched"],
      ["Field observation", "Mild afternoon stress", "Supports irrigation recommendation", "Matched"],
      ["Earth observation layer", "Elevated canopy stress index", "Supports water demand signal", "Matched"],
      ["Talgil", "Target selection pending — runtime status not verified in offline evaluation", "Integration available, target selection pending", "Pending target"],
    ]),
    report: {
      farm: "Alpha Vineyard",
      block: "Block A North",
      recommendation: "Irrigate Block A North — pending backend analysis for timing",
      plannedWater: "Pending backend analysis",
      appliedWater: "Pending confirmation",
      variance: "Pending backend analysis",
      evidenceCompleteness: "—",
      estimatedWaterSavings: "—",
      verification: "Required",
    },
  },
  "incomplete-evidence": {
    id: "incomplete-evidence",
    name: "Incomplete evidence review",
    customerName: "Incomplete evidence review",
    liveEntity: { source: "wiseconn", entityId: "999999" },
    decision: {
      action: "Evidence review required before scheduling",
      start: "Withheld — timing requires complete evidence",
      appliedWater: "Withheld — area validation required",
      grossWater: undefined,
      duration: undefined,
      estimatedVolume: undefined,
      area: "Not provided",
      irrigationMethod: "Pending block mapping",
      controller: "Not connected",
      crop: "Unconfirmed — crop mapping incomplete",
      block: "Block C South — mapping incomplete",
      driver: "Missing area, unvalidated flow, incomplete block and crop mapping",
      confidence: "—",
      evidenceCompleteness: "41%",
      estimatedWaterSavings: "—",
      verification: "Complete evidence before scheduling",
      calibrationStatus: "Not applicable — evidence incomplete",
      flowValidationState: "Flow incomplete",
      schedulable: false,
      schedulingBlockReasons: ["Kernel action is not 'irrigate'", "Flow evidence is not validated for execution timing"],
      limitations: [
        "Block area not provided — estimated volume and duration withheld",
        "Crop mapping incomplete — agronomic demand requires crop and growth stage",
        "Block mapping incomplete — field context cannot be fully assembled",
        "Flow evidence unvalidated — execution timing withheld",
      ],
      nextEvidenceRequired: [
        "Provide block area with explicit unit (ha or ac)",
        "Complete crop and variety mapping",
        "Complete block boundary mapping",
        "Validate flow evidence for this block",
      ],
    },
    sources: [
      { source: "Controller history", latestSignal: "No validated controller event for this block", records: "14", contribution: "—", status: "Review" },
      { source: "Weather demand", latestSignal: "ETo within seasonal range — region-level only", records: "60", contribution: "+0.07", status: "Matched" },
      { source: "Soil moisture", latestSignal: "Partial sensor coverage — one zone missing", records: "22", contribution: "+0.05", status: "Review" },
      { source: "Flow meter", latestSignal: "Prior set variance +28% — unvalidated", records: "8", contribution: "—", status: "Review" },
      { source: "Field observation", latestSignal: "No field observation on record", records: "0", contribution: "—", status: "Pending" },
      { source: "Earth observation layer", latestSignal: "Block boundary not mapped — layer unavailable", records: "0", contribution: "—", status: "Pending" },
      { source: "Uploaded records", latestSignal: "Crop profile missing — agronomic context incomplete", records: "0", contribution: "—", status: "Pending" },
    ],
    reconciliation: recon([
      ["Controller history", "No validated event for this block", "Block mapping incomplete — cannot confirm event", "Review"],
      ["Weather demand", "ETo within seasonal range", "Regional demand available; block-level demand requires crop context", "Matched"],
      ["Soil moisture", "Partial sensor coverage", "Coverage gap flagged — one zone sensor missing", "Review"],
      ["Flow meter", "Prior set variance +28%", "Flow evidence unvalidated — exceeds 20% threshold", "Review"],
      ["Field observation", "No observation on record", "Field observation required before scheduling", "Pending"],
      ["Earth observation layer", "Block boundary not mapped", "Earth observation layer unavailable without block boundary", "Pending"],
      ["Crop profile", "Missing — agronomic demand blocked", "Agronomic demand cannot be calculated without crop profile", "Pending"],
    ]),
    report: {
      farm: "Unnamed block",
      block: "Block C South — mapping incomplete",
      recommendation: "Evidence review required before scheduling",
      plannedWater: "Withheld — area validation required",
      appliedWater: "Withheld",
      variance: "Flow evidence unvalidated",
      evidenceCompleteness: "41%",
      estimatedWaterSavings: "—",
      verification: "Complete evidence before scheduling",
    },
  },
  "almond-orchard": {
    id: "almond-orchard",
    name: "Almond Orchard",
    customerName: "Almond Orchard",
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
    customerName: "Multi-Farm Portfolio",
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
      ["Talgil", "Target selection pending — runtime status not verified in offline evaluation", "Target selection pending", "Pending target"],
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
    customerName: "Partner Data Validation",
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
      ["Talgil", "Target selection pending — runtime status not verified in offline evaluation", "Production authorization required", "Pending target"],
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

export const SCENARIO_OPTIONS: { id: ScenarioId; name: string }[] = [
  { id: "alpha-vineyard", name: "Validated operating block" },
  { id: "incomplete-evidence", name: "Incomplete evidence review" },
];

export function getScenarioFarmName(id: ScenarioId): string {
  return SCENARIOS[id]?.name ?? "Alpha Vineyard";
}

// ---------------------------------------------------------------------------
// Trace + evidence builders
// ---------------------------------------------------------------------------

const TRACE_TITLES: { title: string; detail: string; records: number }[] = [
  { title: "Collecting source records", detail: "Controller, weather, soil, flow, field-observation, and earth-observation records collected from connected sources", records: 2404 },
  { title: "Normalizing field context", detail: "Field schemas and aliases mapped; units, timestamps, and identifiers standardized to canonical model", records: 2404 },
  { title: "Reconciling source evidence", detail: "Cross-source signals reconciled; planned vs applied water variance resolved; conflicts flagged for review", records: 7 },
  { title: "Calculating agronomic demand", detail: "ETo, root-zone deficit, crop growth stage, and soil profile used to compute net irrigation demand", records: 1 },
  { title: "Validating execution evidence", detail: "Flow validation status, pressure state, applied-water variance, and recent irrigation credit assessed", records: 4 },
  { title: "Publishing water recommendation", detail: "Recommendation, timing window, gross depth, duration, and estimated volume assembled with confidence score", records: 1 },
  { title: "Preparing verification plan", detail: "Recommended → Scheduled → Applied → Observed → Verified evidence chain prepared for operator review", records: 5 },
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
  const effectiveOrigin: RecommendationOrigin = id === "incomplete-evidence" ? "insufficient_context" : origin;
  return {
    scenarioId: id,
    analysisMode: mode,
    analysisPhase: "complete",
    recommendationOrigin: effectiveOrigin,
    pipelineMessage: id === "incomplete-evidence" ? "Evidence review required — decision withheld" : "Decision refreshed",
    decision: { ...sc.decision, recommendationOrigin: effectiveOrigin },
    sources: sc.sources,
    reconciliation: sc.reconciliation,
    trace: buildTrace(now, true),
    evidence: baseEvidence(now),
    report: sc.report,
    // Clear stale backend-driven state on scenario transition
    displayFarmName: sc.name || "Alpha Vineyard",
    backendMeta: null,
    sessionId: null,
    selectedFarm: null,
    selectedBlock: null,
    availableFarms: [],
    availableBlocksByFarm: {},
    scopeDefaulted: false,
    scopeSelectionPending: false,
    activeAnalyzedFarm: null,
    activeAnalyzedBlock: null,
    uploadedPackageSessionId: null,
    uploadedPackageArtifacts: [],
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
    displayFarmName: "Alpha Vineyard",
    backendMeta: null,
    selectedFarm: null,
    selectedBlock: null,
    availableFarms: [],
    availableBlocksByFarm: {},
    scopeDefaulted: false,
    scopeSelectionPending: false,
    activeAnalyzedFarm: null,
    activeAnalyzedBlock: null,
    uploadedPackageSessionId: null,
    uploadedPackageArtifacts: [],
  } as CommandState;
}

let state: CommandState = initialState();
const listeners = new Set<() => void>();
// Monotonic counter — older scope responses cannot overwrite newer scope selections.
let _scopeAnalysisGen = 0;
let switchGen = 0; // incremented each time switchScenario is called; guards stale async results

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

export const FLOW_VALIDATION_LABELS: Record<string, string> = {
  validated: "Flow validated for execution timing",
  inconsistent: "Flow inconsistent",
  unavailable: "Flow incomplete",
  detected: "Flow signal detected",
  reconciled: "Flow reconciled",
};

export const ORIGIN_LABEL: Record<string, string> = {
  representative_fallback: "Representative evaluation mode",
  deterministic_engine: "Calibrated agronomic context",
  live_intelligence_engine: "Live connected analysis",
  uploaded_intelligence_engine: "Evaluation package analysis",
  insufficient_context: "Evidence incomplete",
};

function mapSourceStatus(raw: string): SourceRow["status"] {
  const s = (raw || "").toLowerCase();
  if (s === "validated" || s === "accepted" || s === "matched") return "Matched";
  if (s === "inconsistent" || s === "review") return "Review";
  if (s === "unavailable" || s === "pending") return "Pending";
  if (s === "connected source") return "Connected source";
  return "Pending";
}

function buildBackendSources(result: WorkbenchAnalysisResult): SourceRow[] {
  if (Array.isArray(result.source_rows) && result.source_rows.length > 0) {
    const rows: SourceRow[] = result.source_rows.map((r) => ({
      source: r.source_label,
      latestSignal: r.latest_signal_summary,
      records: `${r.selected_scope_record_count} / ${r.package_record_count}`,
      contribution: r.contribution_label,
      status: mapSourceStatus(r.status),
      // Preserve full backend metadata — do not discard after receiving.
      sourceKind: r.source_kind,
      selectedScopeRecordCount: r.selected_scope_record_count,
      packageRecordCount: r.package_record_count,
      latestTimestamp: r.latest_timestamp,
      limitations: r.limitations,
    }));
    const nc = (result.normalized_context ?? {}) as Record<string, unknown>;
    if (nc.live_request) {
      rows.push({
        source: "Live provider",
        latestSignal: (nc.provider_context as string) || "Live provider request",
        records: "Live",
        contribution: "Not scored",
        status: "Connected source",
      });
    }
    return rows;
  }

  const recon = (result.reconciliation ?? {}) as Record<string, unknown>;
  const nc = (result.normalized_context ?? {}) as Record<string, unknown>;
  const counts = (result.signal_summary ?? {}) as Record<string, unknown>;

  const flowStatus = (recon.flow_meter_agreement as string) || "";
  const soilStatus = (recon.soil_moisture_deficit as string) || "";
  const weatherStatus = (recon.weather_demand as string) || "";
  const satelliteStatus = (recon.satellite_stress_support as string) || "";
  const fieldNoteStatus = (recon.field_observation_support as string) || "";

  const flowTone: SourceRow["status"] =
    flowStatus.includes("unavailable") ? "Pending" :
    flowStatus.includes("inconsistent") ? "Review" :
    "Matched";

  const rows: SourceRow[] = [
    {
      source: "Controller history",
      latestSignal: (recon.controller_event_validity as string) || "Controller events analyzed",
      records: String(counts.controller_events_read ?? "—"),
      contribution: "Not scored",
      status: "Matched",
    },
    {
      source: "Weather demand",
      latestSignal: weatherStatus || "Weather demand analyzed",
      records: String(counts.weather_records_read ?? "—"),
      contribution: "Not scored",
      status: weatherStatus.includes("not available") ? "Pending" : "Matched",
    },
    {
      source: "Soil moisture",
      latestSignal: soilStatus || "Soil deficit analyzed",
      records: String(counts.soil_readings_read ?? "—"),
      contribution: "Not scored",
      status: soilStatus.includes("not available") ? "Pending" : "Matched",
    },
    {
      source: "Flow meter",
      latestSignal: flowStatus || "Flow evidence analyzed",
      records: String(counts.flow_meter_records_read ?? "—"),
      contribution: "Not scored",
      status: flowTone,
    },
    {
      source: "Field observation",
      latestSignal: fieldNoteStatus || "Field notes analyzed",
      records: String(counts.field_notes_parsed ?? "—"),
      contribution: "Not scored",
      status: counts.field_notes_parsed ? "Matched" : "Pending",
    },
    {
      source: "Earth observation layer",
      latestSignal: satelliteStatus || "Earth observation layer analyzed",
      records: String(counts.satellite_observations_read ?? "—"),
      contribution: "Not scored",
      status: counts.satellite_observations_read ? "Matched" : "Pending",
    },
  ];

  if (nc.live_request) {
    rows.push({
      source: "Live provider",
      latestSignal: (nc.provider_context as string) || "Live provider request",
      records: "Live",
      contribution: "Not scored",
      status: "Connected source",
    });
  }

  return rows;
}

const _RAW_INTERNAL_KEY_LABELS: Record<string, string> = {
  field_area_ha: "Provide the block area with an explicit unit (hectares or acres)",
  validated_flow_or_application_rate: "Upload or connect validated flow evidence for this block",
  recent_verified_applied_water_credit: "Upload or connect a recent controller-confirmed or flow-meter-confirmed applied-water event for this block",
  crop_type: "Complete crop mapping — specify the crop species for this block",
  soil_type: "Complete soil mapping — specify the soil type for this block",
  irrigation_method: "Confirm the irrigation method for this block",
  block_boundary_mapping: "Map the block boundary before enabling earth observation",
  current_field_observation: "Add a current field observation for this block",
  block_mapping: "Complete block mapping before scheduling",
  farm_mapping: "Complete farm mapping before scheduling",
  variety_mapping: "Complete variety mapping for this crop",
};

function _readableMissingInput(raw: string): string {
  return _RAW_INTERNAL_KEY_LABELS[raw]
    // If the string already reads like a sentence, use it directly.
    ?? (raw.includes(" ") ? raw : "Additional evidence is required before scheduling is enabled.");
}

function buildBackendReconciliation(result: WorkbenchAnalysisResult): ReconciliationRow[] {
  const recon = (result.reconciliation ?? {}) as Record<string, unknown>;
  const matched = Array.isArray(recon.matched_signals) ? recon.matched_signals as string[] : [];
  const conflicts = Array.isArray(recon.conflicts_detected) ? recon.conflicts_detected as string[] : [];
  const missing = Array.isArray(recon.missing_inputs) ? recon.missing_inputs as string[] : [];

  const rows: ReconciliationRow[] = [];

  const _PENDING_PATTERNS = ["not available", "missing", "no selected-block", "no field", "unavailable", "none on record", "0 record", "withheld"];
  function _signalStatus(signal: string, extraReviewPatterns: string[] = []): ReconciliationRow["status"] {
    const low = signal.toLowerCase();
    if (extraReviewPatterns.some(p => low.includes(p))) return "Review";
    if (_PENDING_PATTERNS.some(p => low.includes(p))) return "Pending";
    return "Matched";
  }

  if (typeof recon.controller_event_validity === "string") {
    rows.push({ source: "Controller history", signal: recon.controller_event_validity, interpretation: "Controller telemetry processed", status: _signalStatus(recon.controller_event_validity) });
  }
  if (typeof recon.weather_demand === "string") {
    rows.push({ source: "Weather demand", signal: recon.weather_demand, interpretation: "ETo and rainfall demand computed", status: _signalStatus(recon.weather_demand) });
  }
  if (typeof recon.soil_moisture_deficit === "string") {
    rows.push({ source: "Soil moisture", signal: recon.soil_moisture_deficit, interpretation: "Root-zone deficit assessed", status: _signalStatus(recon.soil_moisture_deficit) });
  }
  if (typeof recon.flow_meter_agreement === "string") {
    rows.push({ source: "Flow meter", signal: recon.flow_meter_agreement, interpretation: "Applied-water variance assessed", status: _signalStatus(recon.flow_meter_agreement, ["inconsistent"]) });
  }
  if (typeof recon.field_observation_support === "string") {
    rows.push({ source: "Field observation", signal: recon.field_observation_support, interpretation: "Field note corroboration assessed", status: _signalStatus(recon.field_observation_support) });
  }
  if (typeof recon.satellite_stress_support === "string") {
    rows.push({ source: "Earth observation layer", signal: recon.satellite_stress_support, interpretation: "Vegetation stress index assessed", status: _signalStatus(recon.satellite_stress_support) });
  }

  for (const conflict of conflicts) {
    rows.push({ source: "Conflict flagged", signal: conflict, interpretation: "Source conflict detected during reconciliation", status: "Review" });
  }
  // Prefer next_evidence_required (already customer-readable) over raw missing_inputs.
  const nextEvidence = Array.isArray((result.recommendation as Record<string, unknown>)?.next_evidence_required)
    ? (result.recommendation as Record<string, unknown>).next_evidence_required as string[]
    : [];
  const missingItems = nextEvidence.length > 0 ? nextEvidence : missing;
  for (const miss of missingItems.slice(0, 3)) {
    rows.push({ source: "Action required", signal: _readableMissingInput(miss), interpretation: "Required input not available in uploaded package", status: "Pending" });
  }

  return rows.length > 0 ? rows : matched.slice(0, 6).map((m) => ({ source: m, signal: "Signal matched", interpretation: "Reconciled from uploaded package", status: "Matched" as ReconciliationRow["status"] }));
}

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
  const nc = (result.normalized_context ?? {}) as Record<string, unknown>;
  const recon = (result.reconciliation ?? {}) as Record<string, unknown>;

  // Only inherit representative scenario values when the engine explicitly signals
  // a representative fallback. For live, uploaded, and deterministic results use
  // honest "pending" labels so representative precision cannot leak into a real result.
  const useRepresentative = origin === "representative_fallback";

  const action = (rec.action as string) || (rec.decision as string) || (summary.recommendation as string) || (useRepresentative ? sc.decision.action : "Decision pending source review");
  const flowValidationRaw = (rec.flow_validation_status as string) || undefined;
  const flowValidationState = flowValidationRaw
    ? FLOW_VALIDATION_LABELS[flowValidationRaw] ?? flowValidationRaw
    : (useRepresentative ? sc.decision.flowValidationState : "Flow incomplete");

  // Savings: use backend computed value if action is irrigate, else "—"
  let estimatedWaterSavings = useRepresentative ? sc.decision.estimatedWaterSavings : "—";
  const savingsPct = rec.estimated_water_savings_percent;
  if (typeof savingsPct === "number" && savingsPct >= 0) {
    estimatedWaterSavings = `${Math.round(savingsPct)}% vs evaluation baseline`;
  }

  // Area: prefer backend normalized_context area_ha; fall back to scenario representative value
  let areaDisplay: string | undefined = useRepresentative ? sc.decision.area : undefined;
  const areaHa = nc.area_ha;
  const areaUnit = nc.area_unit;
  if (typeof areaHa === "number") {
    areaDisplay = `${areaHa} ${areaUnit ?? "ha"}`;
  }

  // Irrigation method: from normalized context
  const irrigationMethod = (nc.irrigation_method as string) || (useRepresentative ? sc.decision.irrigationMethod : undefined);
  const method = irrigationMethod && irrigationMethod !== "not available"
    ? irrigationMethod.charAt(0).toUpperCase() + irrigationMethod.slice(1)
    : (useRepresentative ? sc.decision.irrigationMethod : undefined);

  // Provider context from normalized_context
  const providerCtx = (nc.provider_context as string) || undefined;
  const controller = providerCtx && providerCtx !== "not available"
    ? providerCtx
    : (useRepresentative ? sc.decision.controller : undefined);

  // Crop and variety
  const crop = (nc.crop as string) && (nc.crop as string) !== "not available"
    ? (nc.crop as string)
    : (useRepresentative ? sc.decision.crop : "Source context incomplete");
  const variety = (nc.variety as string) || undefined;
  const displayCrop = variety && variety !== "not available" ? variety : crop;

  // Block
  const block = (nc.block as string) || (useRepresentative ? sc.decision.block : "Source context incomplete");

  // Farm name — data-driven from backend; use scenario representative as offline fallback
  const backendFarm = (nc.farm as string) || null;
  const displayFarmName = backendFarm && !useRepresentative ? backendFarm : (sc.name || "Alpha Vineyard");

  const decision: Decision = {
    action,
    start: (rec.start_time as string) || (rec.timing as string) || (useRepresentative ? sc.decision.start : "Pending evidence"),
    appliedWater: (rec.depth as string) || (summary.planned_water as string) || (useRepresentative ? sc.decision.appliedWater : "Withheld pending validation"),
    grossWater: (rec.gross_depth as string) || (useRepresentative ? sc.decision.grossWater : undefined),
    estimatedVolume: (rec.estimated_volume as string) || (useRepresentative ? sc.decision.estimatedVolume : undefined),
    duration: (rec.duration as string) || (rec.no_fabricated_duration ? "Withheld until flow is validated" : (useRepresentative ? sc.decision.duration : "Withheld pending validation")),
    area: areaDisplay,
    irrigationMethod: method,
    controller,
    crop: displayCrop,
    block,
    driver: Array.isArray(rec.key_drivers) && rec.key_drivers.length ? String((rec.key_drivers as unknown[])[0]) : (useRepresentative ? sc.decision.driver : "Tenant baseline required"),
    confidence: pct(rec.confidence ?? summary.confidence, useRepresentative ? sc.decision.confidence : "—"),
    evidenceCompleteness: pct(result.reconciliation?.evidence_completeness ?? summary.evidence_completeness, useRepresentative ? sc.decision.evidenceCompleteness : "—"),
    estimatedWaterSavings,
    verification: (rec.verification_requirement as string) || (useRepresentative ? sc.decision.verification : "Required"),
    recommendationOrigin: origin,
    calibrationStatus: (rec.calibration_status as string) || (useRepresentative ? sc.decision.calibrationStatus : undefined),
    calibrationPackVersion: (rec.calibration_pack_version as string) || undefined,
    verificationStatus: "Required",
    flowValidationState,
    flowValidationNotes: Array.isArray(rec.flow_validation_notes) ? rec.flow_validation_notes as string[] : undefined,
    recentIrrigationCreditStatus: (rec.recent_irrigation_credit_status as string) || undefined,
    recentIrrigationCreditNotes: Array.isArray(rec.recent_irrigation_credit_notes) ? rec.recent_irrigation_credit_notes as string[] : undefined,
    limitations: Array.isArray(result.limitations) ? result.limitations : undefined,
    nextEvidenceRequired: Array.isArray(rec.next_evidence_required) ? rec.next_evidence_required as string[] : undefined,
    variety: variety && variety !== "not available" ? variety : undefined,
    farmName: backendFarm || undefined,
    region: (nc.region as string) || undefined,
    baselineLabel: (rec.baseline_label as string) || undefined,
    baselineValueMm: typeof rec.baseline_value_mm === "number" ? rec.baseline_value_mm : undefined,
    baselineCalculationNote: (rec.baseline_calculation_note as string) || undefined,
    schedulable: rec.schedulable === true,
    schedulingBlockReason: (rec.scheduling_block_reason as string) || undefined,
    schedulingBlockReasons: Array.isArray(rec.scheduling_block_reasons) ? rec.scheduling_block_reasons as string[] : undefined,
  };

  const trace: TraceStep[] = Array.isArray(result.analysis_trace) && result.analysis_trace.length
    ? result.analysis_trace.map((t) => ({
        title: t.title,
        status: (["complete", "running", "pending", "review", "limited"].includes(t.status ?? "") ? t.status : "complete") as TraceStep["status"],
        recordsProcessed: t.objects_processed ?? 0,
        detail: t.details ?? "",
        timestamp: now,
      }))
    : buildTrace(now, true);

  const report: ReportModel = useRepresentative
    ? { ...sc.report, recommendation: action, plannedWater: decision.grossWater || decision.appliedWater, evidenceCompleteness: decision.evidenceCompleteness }
    : {
        farm: (nc.farm as string) || "Source context incomplete",
        block: (nc.block as string) || "Source context incomplete",
        recommendation: action,
        plannedWater: decision.grossWater || decision.appliedWater || "Withheld pending validation",
        appliedWater: "Pending confirmation",
        variance: (recon.planned_vs_applied_variance as string) || "Withheld pending validation",
        evidenceCompleteness: decision.evidenceCompleteness || "—",
        estimatedWaterSavings,
        verification: (rec.verification_requirement as string) || "Required",
      };

  // Extract available scope options from normalized context for farm/block selectors.
  const availableFarms = Array.isArray(nc.available_farms) ? nc.available_farms as string[] : [];
  const availableBlocksByFarm = (nc.available_blocks_by_farm && typeof nc.available_blocks_by_farm === "object")
    ? nc.available_blocks_by_farm as Record<string, string[]>
    : {};
  const scopeDefaulted = nc.scope_defaulted === true;

  // Persist backend metadata for technical trace expansion.
  const backendMeta: BackendMeta = {
    normalizedContext: nc,
    warnings: Array.isArray(result.warnings) ? result.warnings : [],
    uploadedArtifacts: Array.isArray(result.uploaded_artifacts_used) ? result.uploaded_artifacts_used : [],
    liveInputsUsed: Array.isArray(result.live_inputs_used) ? result.live_inputs_used : [],
    flowValidationNotes: Array.isArray(rec.flow_validation_notes) ? rec.flow_validation_notes as string[] : [],
    recentIrrigationCreditNotes: Array.isArray(rec.recent_irrigation_credit_notes) ? rec.recent_irrigation_credit_notes as string[] : [],
    baselineCalculationNote: (rec.baseline_calculation_note as string) || null,
    baselineLabel: (rec.baseline_label as string) || null,
    evaluationReferenceTime: (rec.evaluation_reference_time as string) || null,
    sessionId: result.session_id || null,
    availableFarms,
    availableBlocksByFarm,
  };

  // Build source and reconciliation rows from backend response when not in representative fallback.
  const backendSources = useRepresentative ? null : buildBackendSources(result);
  const backendReconciliation = useRepresentative ? null : buildBackendReconciliation(result);

  set({
    analysisMode: mode,
    analysisPhase: "complete",
    recommendationOrigin: origin,
    pipelineMessage: "Decision refreshed",
    decision,
    trace,
    evidence: baseEvidence(now),
    report,
    displayFarmName,
    backendMeta,
    availableFarms,
    availableBlocksByFarm,
    scopeDefaulted,
    ...(backendSources ? { sources: backendSources } : {}),
    ...(backendReconciliation ? { reconciliation: backendReconciliation } : {}),
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

  async switchScenario(id: ScenarioId) {
    // Increment generation so any in-flight backend calls from the prior scenario are discarded.
    switchGen++;
    const gen = switchGen;

    // Set local representative state immediately so the UI reflects the new scenario
    // without a blank loading flash. Backend analysis will override this if reachable.
    const immediateOrigin: RecommendationOrigin = id === "incomplete-evidence" ? "insufficient_context" : "representative_fallback";
    set({
      ...scenarioState(id, "representative", immediateOrigin),
      analysisPhase: "running",
      pipelineMessage: "Loading scenario source package…",
    });

    if (state.backend.status !== "unavailable") {
      try {
        const backendScenario = id === "incomplete-evidence" ? "incomplete_evidence_review" : "validated_operating_block";
        const sample = await apiClient.createSamplePackage(backendScenario);
        if (gen !== switchGen) return; // superseded by a later switchScenario call
        const sessionId = sample.data?.session?.session_id || sample.data?.session_id || "";
        if (sample.ok && sessionId) {
          set({ sessionId, pipelineMessage: "Analyzing scenario source package…" });
          const analysis = await apiClient.analyzeSession(sessionId);
          if (gen !== switchGen) return; // superseded by a later switchScenario call
          if (analysis.ok && analysis.data) {
            applyBackendResult(analysis.data, "representative");
            addAudit("Scenario loaded via backend", `${SCENARIOS[id].name} analyzed from backend.`);
            toast(`${SCENARIOS[id].name} loaded`);
            return;
          }
        }
      } catch {
        // Falls through to the local representative fallback.
      }
    }

    if (gen !== switchGen) return;
    set({ ...scenarioState(id, "representative", immediateOrigin), pipelineMessage: "Backend unavailable. Offline representative fallback active." });
    addAudit("Workspace scenario loaded", `${SCENARIOS[id].name} offline representative records loaded.`);
    toast(`${SCENARIOS[id].name} loaded`);
  },

  async refreshIntelligence() {
    if (state.analysisPhase === "running") return;
    set({ analysisPhase: "running", pipelineMessage: "Re-analyzing evaluation source records…", trace: buildTrace(new Date().toISOString(), false) });
    addAudit("Evaluation refresh started", `Re-running analyzeSession for session: ${state.sessionId ?? "none"}.`);

    // For evaluation mode, re-run the existing session rather than switching to a live provider.
    // Live-provider refresh is a separate explicit action the user must invoke.
    let result: WorkbenchAnalysisResult | null = null;
    if (state.backend.status !== "unavailable" && state.sessionId) {
      try {
        // Only pass scope when both are set — never issue a partial-scope request.
        const scopeFarm = (state.selectedFarm && state.selectedBlock) ? state.selectedFarm : undefined;
        const scopeBlock = (state.selectedFarm && state.selectedBlock) ? state.selectedBlock : undefined;
        const res = await apiClient.analyzeSession(state.sessionId, scopeFarm, scopeBlock);
        if (res.ok && res.data) result = res.data;
      } catch {
        result = null;
      }
    }

    // brief pause so the pipeline animation is legible
    await new Promise((r) => setTimeout(r, 900));

    if (result) {
      applyBackendResult(result, state.analysisMode);
      addAudit("Evaluation refresh completed", "Decision refreshed from evaluation session.");
      toast("Decision refreshed.");
    } else {
      set(scenarioState(state.scenarioId, "representative", "representative_fallback"));
      set({ pipelineMessage: "Backend unavailable. Representative analysis remains active." });
      addAudit("Evaluation refresh completed", "Representative-data analysis applied.");
      toast("Representative analysis remains active.");
    }
  },

  async runLiveRefresh() {
    if (state.analysisPhase === "running") return;
    set({ analysisPhase: "running", pipelineMessage: "Connecting to live provider sources…", trace: buildTrace(new Date().toISOString(), false) });
    addAudit("Live refresh started", "Requesting live connected-source intelligence from backend.");
    let result: WorkbenchAnalysisResult | null = null;
    if (state.backend.status !== "unavailable") {
      try {
        const sc = SCENARIOS[state.scenarioId];
        const liveRes = await apiClient.analyzeLive(sc.liveEntity.source, sc.liveEntity.entityId);
        if (liveRes.ok && liveRes.data) result = liveRes.data;
      } catch {
        result = null;
      }
    }
    await new Promise((r) => setTimeout(r, 900));
    if (result) {
      applyBackendResult(result, "live");
      addAudit("Live refresh completed", "Decision updated from live connected-source intelligence.");
      toast("Live intelligence refreshed.");
    } else {
      set({ analysisPhase: "complete", pipelineMessage: "Live provider unavailable. Evaluation session remains active." });
      addAudit("Live refresh failed", "Live provider unreachable; evaluation session analysis remains active.");
      toast("Live provider unavailable. Evaluation session remains active.");
    }
  },

  // Single-file convenience wrapper — delegates to uploadFiles.
  async uploadRecords(file: File) {
    return actions.uploadFiles([file]);
  },

  // Upload multiple files to the current package session (or create a new one if none exists).
  async uploadFiles(files: File[]) {
    if (!files.length) return;
    set({ pipelineMessage: "Uploading source records…", analysisPhase: "running" });

    // Show placeholders immediately so filenames are visible before any API call.
    const placeholders: UploadedFileState[] = files.map(file => ({
      name: file.name, detectedType: detectType(file.name), parseStatus: "Uploading…", rows: "—", fields: "—", warnings: "—",
    }));
    set({
      uploaded: placeholders[placeholders.length - 1],
      uploadedPackageArtifacts: [...state.uploadedPackageArtifacts, ...placeholders],
    });

    // Reuse the existing uploaded-package session rather than creating a new one per file.
    // Never mix a representative sample session with a user-uploaded package session.
    let sessionId = state.uploadedPackageSessionId ?? "";
    if (!sessionId) {
      const created = await apiClient.createSession("uploaded");
      if (created.ok) sessionId = created.data?.session_id || created.data?.session?.session_id || "";
      if (!sessionId) {
        const failedArtifacts = placeholders.map(p => ({ ...p, parseStatus: "Upload failed", warnings: "Backend unavailable." }));
        const prevArtifacts = state.uploadedPackageArtifacts.filter(a => !files.some(f => f.name === a.name && a.parseStatus === "Uploading…"));
        set({
          analysisPhase: "complete",
          pipelineMessage: "Backend unavailable. Representative analysis remains active.",
          uploadedPackageArtifacts: [...prevArtifacts, ...failedArtifacts],
          uploaded: failedArtifacts[failedArtifacts.length - 1],
        });
        toast("Backend upload unavailable. Representative analysis remains active.");
        return;
      }
      set({ sessionId, uploadedPackageSessionId: sessionId });
      addAudit("Upload package session created", `New uploaded package session: ${sessionId}`);
    } else {
      set({ sessionId });
    }

    const newArtifacts: UploadedFileState[] = [];
    for (const file of files) {
      const placeholder = placeholders.find(p => p.name === file.name) ?? placeholders[0];
      set({ uploaded: placeholder });

      const up = await apiClient.uploadFile(sessionId, file);
      const artifact: UploadedFileState = up.ok && up.data
        ? {
            name: up.data.filename || file.name,
            detectedType: up.data.source_kind || detectType(file.name),
            parseStatus: up.data.parse_status || "parsed",
            rows: String(up.data.rows_detected ?? "—"),
            fields: Array.isArray(up.data.columns_detected) ? String(up.data.columns_detected.length) : "—",
            warnings: up.data.warnings?.length ? up.data.warnings.join("; ") : "None",
          }
        : { ...placeholder, parseStatus: "Upload failed", warnings: "File could not be uploaded." };
      newArtifacts.push(artifact);
      set({ uploaded: artifact });
    }

    // Replace the placeholder entries with final artifact records.
    const prevArtifacts = state.uploadedPackageArtifacts.filter(a => !files.some(f => f.name === a.name && a.parseStatus === "Uploading…"));
    set({ uploadedPackageArtifacts: [...prevArtifacts, ...newArtifacts] });

    // Only pass scope if both farm and block are selected — never partial scope.
    const scopeFarm = (state.selectedFarm && state.selectedBlock) ? state.selectedFarm : undefined;
    const scopeBlock = (state.selectedFarm && state.selectedBlock) ? state.selectedBlock : undefined;
    const analysis = await apiClient.analyzeSession(sessionId, scopeFarm, scopeBlock);
    if (analysis.ok && analysis.data) {
      applyBackendResult(analysis.data, "uploaded");
      addAudit("Uploaded package analyzed", `${files.map(f => f.name).join(", ")} analyzed via Workbench.`);
      toast(`${files.length === 1 ? files[0].name : `${files.length} files`} analyzed.`);
      return;
    }
    set({ analysisPhase: "complete", pipelineMessage: "Backend unavailable. Representative analysis remains active." });
    toast("Upload analysis unavailable. Representative analysis remains active.");
  },

  // Reset the upload package — the next upload will create a fresh session.
  startNewPackage() {
    set({
      uploadedPackageSessionId: null,
      uploadedPackageArtifacts: [],
      uploaded: null,
      selectedFarm: null,
      selectedBlock: null,
      backendMeta: null,
      scopeSelectionPending: false,
    });
    addAudit("Upload package reset", "New package session will be created on next upload.");
    toast("Upload package cleared. Drop files to start a new package.");
  },

  openDrawer() {
    set({ drawerOpen: true });
  },
  closeDrawer() {
    set({ drawerOpen: false });
  },

  setSelectedFarm(farm: string | null) {
    // Changing farm clears the block selection, stale backend metadata, and marks scope pending.
    set({ selectedFarm: farm, selectedBlock: null, backendMeta: null, scopeSelectionPending: farm !== null });
    addAudit("Farm scope selected", `Selected farm: ${farm ?? "none"}`);
  },

  setSelectedBlock(block: string | null) {
    set({ selectedBlock: block });
    addAudit("Block scope selected", `Selected block: ${block ?? "none"}`);
  },

  async reanalyzeSelectedScope() {
    // Require both farm and block — never issue a partial-scope request.
    if (!state.selectedFarm || !state.selectedBlock) {
      addAudit("Scope re-analysis blocked", "Both farm and block must be selected before re-analysis.");
      return;
    }
    if (!state.sessionId || state.analysisPhase === "running") return;
    // Capture scope and generation before any async work to guard against race conditions.
    const capturedFarm = state.selectedFarm;
    const capturedBlock = state.selectedBlock;
    const gen = ++_scopeAnalysisGen;
    set({ analysisPhase: "running", backendMeta: null, pipelineMessage: "Re-analyzing with selected scope…", trace: buildTrace(new Date().toISOString(), false) });
    addAudit("Scope re-analysis started", `Farm: ${capturedFarm}, Block: ${capturedBlock}`);
    if (state.backend.status === "unavailable") {
      set({ analysisPhase: "complete", pipelineMessage: "Backend unavailable — scope re-analysis blocked.", scopeSelectionPending: true });
      toast("Backend unavailable. Scope re-analysis blocked.");
      return;
    }
    try {
      const res = await apiClient.analyzeSession(state.sessionId, capturedFarm, capturedBlock);
      // Discard stale responses — a newer scope selection was made while this request was in flight.
      if (gen !== _scopeAnalysisGen) return;
      if (res.ok && res.data) {
        applyBackendResult(res.data, state.analysisMode);
        set({ activeAnalyzedFarm: capturedFarm, activeAnalyzedBlock: capturedBlock, scopeSelectionPending: false });
        addAudit("Scope re-analysis completed", `Analysis updated for ${capturedFarm} / ${capturedBlock}.`);
        toast("Analysis updated for selected scope.");
        return;
      }
    } catch {
      if (gen !== _scopeAnalysisGen) return;
    }
    // On failure keep scopeSelectionPending so operational actions remain blocked.
    set({ analysisPhase: "complete", pipelineMessage: "Scope re-analysis failed. Previous result remains active.", scopeSelectionPending: true });
    toast("Scope re-analysis failed.");
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
    // For representative fallback: always simulate locally — never call backend.
    if (state.recommendationOrigin === "representative_fallback") {
      set({ evidence });
      addAudit(`Walkthrough simulation: ${order[idx]}`, "Walkthrough simulation — not an operational evidence record.");
      toast(`${state.evidence[idx]?.label ?? "Step"} (walkthrough simulation)`);
      return;
    }
    // Uploaded and live origins must never advance local state without backend persistence.
    if (!state.sessionId) {
      addAudit("Evidence step not recorded", "No session ID — backend persistence required for uploaded/live origins.");
      toast("Evidence step was not recorded. A backend session is required.");
      return;
    }
    if (state.scopeSelectionPending) {
      addAudit("Evidence step not recorded", "Scope selection pending — analyze the selected block before recording evidence.");
      toast("Evidence step was not recorded. Analyze the selected block first.");
      return;
    }
    if (state.backend.status === "unavailable" || !actionName) {
      addAudit("Evidence step not recorded", "Backend unavailable — local evidence advance blocked for uploaded/live origins.");
      toast("Evidence step was not recorded. Backend is unavailable.");
      return;
    }
    const res = await apiClient.recordEvidenceAction(state.sessionId, actionName, evidenceText[key]);
    if (res.ok && res.data?.updated_evidence_chain) {
      set({ evidence: res.data.updated_evidence_chain });
      addAudit(`${order[idx]} recorded`, `Backend evidence action recorded in evaluation-session storage.`);
      toast(`${state.evidence[idx]?.label ?? "Step"} recorded`);
      return;
    }
    // Backend was reachable but rejected (e.g. 409 ordering violation or scheduling gate).
    addAudit("Evidence step not recorded", "Backend rejected the evidence action; local state not advanced.");
    toast("Evidence step was not recorded. Refresh the workspace and try again.");
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

export function getProvenanceBadge(mode: AnalysisMode, origin: RecommendationOrigin): { label: string; tone: "gold" | "ok" | "warn" | "neutral" } {
  if (origin === "representative_fallback") return { label: "Offline representative fallback", tone: "gold" };
  if (origin === "insufficient_context") return { label: "Offline representative fallback", tone: "gold" };
  if (mode === "representative") return { label: "Representative evaluation records", tone: "gold" };
  if (mode === "uploaded") return { label: "Uploaded package", tone: "ok" };
  if (mode === "live") return { label: "Live connected sources", tone: "ok" };
  return { label: "Representative evaluation records", tone: "gold" };
}

// Test seam: reset store to a clean initial state.
export function __resetForTest() {
  state = initialState();
  emit();
}

export function __applyBackendResult(
  scenarioId: ScenarioId,
  result: WorkbenchAnalysisResult,
  sessionId: string | null,
) {
  state = { ...state, scenarioId };
  applyBackendResult(result, (result.analysis_mode as AnalysisMode) ?? "uploaded");
  if (sessionId) {
    state = { ...state, sessionId, backendMeta: state.backendMeta ? { ...state.backendMeta, sessionId } : null };
  }
  emit();
}

// Test seam: set backend status directly (without going through the async health check).
export function __setBackendStatusForTest(status: BackendStatus) {
  state = { ...state, backend: { ...state.backend, status } };
  emit();
}

// Test seam: set selected farm/block directly.
export function __setSelectedScopeForTest(farm: string | null, block: string | null) {
  state = { ...state, selectedFarm: farm, selectedBlock: block, scopeSelectionPending: false };
  emit();
}
