import { demoWorkspace } from "./demoData.js";
import { createDemoRuntime, loadRepresentativePackage, resetDemo as resetDemoRuntime } from "./services/demoRuntime.js";

export const SESSION_MODES = {
  ENTRY: "entry",
  // Internal value kept as "demo" for backward compatibility with stored runtimes;
  // never shown to users. The workspace is presented as an "Evaluation workspace".
  EVALUATION: "demo",
  LIVE: "live",
};

export const state = {
  session: {
    mode: SESSION_MODES.ENTRY,
    workspace: null,
    authNotice: "Customer login is an auth-ready scaffold until backend authentication and credential storage are enabled.",
    userEmail: "",
    userName: "Operations user",
    loginError: "",
  },
  activeView: "overview",
  demoRuntime: createDemoRuntime(),
  compliance: {
    loading: false,
    status: null,
    error: "",
  },
  assurance: {
    loading: false,
    error: "",
    activePassportId: "",
    activePassport: null,
    rulePacks: {},
    readiness: null,
    latestExport: null,
    demoMode: true,
  },
  agent: {
    loading: false,
    error: "",
    activeRunId: "",
    activeRun: null,
    findings: [],
    recommendations: [],
    proposedActions: [],
    automationPlan: [],
    messages: [],
  },
  live: {
    auth: null,
    farms: [],
    zonesByFarm: new Map(),
    integrations: [],
    recommendation: null,
    auditEvents: [],
    recommendationError: "",
    recommendationLoading: false,
    selectedFarmId: "",
    selectedZoneId: "162803",
  },
};

const listeners = new Set();

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notify() {
  listeners.forEach((listener) => listener(state));
}

export function setActiveView(view) {
  state.activeView = view;
  notify();
}

export function setLoginError(message) {
  state.session.loginError = message;
  notify();
}

export function setDemoRuntime(runtime) {
  state.demoRuntime = runtime;
  notify();
}

export function launchDemoSession() {
  // Open the Command page with the representative package preloaded so the
  // workspace is immediately functional in a founder-led customer call.
  state.demoRuntime = loadRepresentativePackage(resetDemoRuntime(false));
  state.session = {
    mode: SESSION_MODES.EVALUATION,
    workspace: demoWorkspace,
    authNotice: "Representative records are isolated from production telemetry.",
    userEmail: "",
    userName: "Operations user",
    loginError: "",
  };
  state.activeView = "overview";
  state.assurance.demoMode = true;
  state.assurance.activePassportId = "demo-passport-alpha-vineyard";
  state.agent.activeRunId = "demo-agent-run-alpha-vineyard";
  notify();
}

export function startLoginScaffold(email) {
  state.session = {
    mode: SESSION_MODES.LIVE,
    workspace: {
      id: "customer-auth-ready",
      name: "Customer Workspace",
      mode: "Live",
      source: "WiseConn",
      label: "Auth-ready scaffold — backend authentication required",
    },
    authNotice: "Authentication UI is ready, but production authentication and organization selection require backend auth endpoints.",
    userEmail: email || "customer@example.com",
    loginError: "",
  };
  state.activeView = "overview";
  state.assurance = {
    ...state.assurance,
    loading: false,
    error: "",
    activePassportId: "",
    activePassport: null,
    readiness: null,
    latestExport: null,
    demoMode: false,
  };
  state.agent = {
    ...state.agent,
    loading: false,
    error: "",
    activeRunId: "",
    activeRun: null,
    findings: [],
    recommendations: [],
    proposedActions: [],
    automationPlan: [],
    messages: [],
  };
  notify();
}

export function returnToEntry() {
  state.session.mode = SESSION_MODES.ENTRY;
  state.session.workspace = null;
  state.activeView = "overview";
  notify();
}
