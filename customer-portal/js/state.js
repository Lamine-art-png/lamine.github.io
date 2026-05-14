import { demoWorkspace } from "./demoData.js";

export const SESSION_MODES = {
  ENTRY: "entry",
  DEMO: "demo",
  LIVE: "live",
};

export const state = {
  session: {
    mode: SESSION_MODES.ENTRY,
    workspace: null,
    authNotice: "Customer login is an auth-ready scaffold until backend authentication and credential storage are enabled.",
    userEmail: "",
  },
  activeView: "command-center",
  live: {
    auth: null,
    farms: [],
    zonesByFarm: new Map(),
    integrations: [],
    recommendation: null,
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

export function launchDemoSession() {
  state.session = {
    mode: SESSION_MODES.DEMO,
    workspace: demoWorkspace,
    authNotice: "Demo data is embedded and isolated from live production API data.",
    userEmail: "demo@agroai.local",
  };
  state.activeView = "command-center";
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
  };
  state.activeView = "command-center";
  notify();
}

export function returnToEntry() {
  state.session.mode = SESSION_MODES.ENTRY;
  state.session.workspace = null;
  state.activeView = "command-center";
  notify();
}
