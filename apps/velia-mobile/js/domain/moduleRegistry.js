const env = globalThis?.TERRIS_FLAGS || {};

function rawFlag(name, legacyName, fallback) {
  const value = env[name] ?? env[legacyName];
  if (value === undefined || value === null) return fallback;
  return value === true || String(value).toLowerCase() === "true";
}

export const TERRIS_FEATURE_FLAGS = Object.freeze({
  TERRIS_WATER_ENABLED: rawFlag("TERRIS_WATER_ENABLED", "VELIA_WATER_ENABLED", true),
  TERRIS_NUTRIENTS_ENABLED: rawFlag("TERRIS_NUTRIENTS_ENABLED", "VELIA_NUTRIENTS_ENABLED", false),
  TERRIS_ENERGY_ENABLED: rawFlag("TERRIS_ENERGY_ENABLED", "VELIA_ENERGY_ENABLED", false),
  TERRIS_OPS_ENABLED: rawFlag("TERRIS_OPS_ENABLED", "VELIA_OPS_ENABLED", false),
  TERRIS_PROOF_ENABLED: rawFlag("TERRIS_PROOF_ENABLED", "VELIA_PROOF_ENABLED", false),
  TERRIS_PROTECT_ENABLED: rawFlag("TERRIS_PROTECT_ENABLED", "VELIA_PROTECT_ENABLED", false),
  TERRIS_RISK_API_ENABLED: rawFlag("TERRIS_RISK_API_ENABLED", "VELIA_RISK_API_ENABLED", false),
});

const baseRegistry = [
  {
    key: "water",
    label: "Terris Water",
    description: "Operational water recommendations, approvals, execution records, verification, and proof.",
    status: "active",
    flag: "TERRIS_WATER_ENABLED",
    route: "water",
    capabilities: ["observe", "recommend", "approve", "schedule", "record_applied", "verify"],
    requiredInputs: ["field", "crop context", "weather", "recent observations"],
    generatedEvents: ["irrigation_recommendation", "irrigation_approval", "irrigation_schedule", "irrigation_applied", "irrigation_verified", "field_observation"],
  },
  {
    key: "nutrients",
    label: "Terris Nutrients",
    description: "Beta nutrient and fertigation ledger linked to irrigation and field evidence.",
    status: "beta",
    flag: "TERRIS_NUTRIENTS_ENABLED",
    route: "nutrients",
    capabilities: ["record_nutrient_application", "track_fertigation", "identify_missing_inputs"],
    requiredInputs: ["field", "crop cycle", "nutrient source", "quantity", "unit"],
    generatedEvents: ["fertigation_plan", "fertigation_applied", "nutrient_application"],
    limitations: ["Does not prescribe fertilizer rates as authoritative."],
  },
  {
    key: "energy",
    label: "Terris Energy",
    description: "Beta irrigation execution cost context using pump and tariff evidence.",
    status: "beta",
    flag: "TERRIS_ENERGY_ENABLED",
    route: "energy",
    capabilities: ["compare_eligible_windows", "record_pump_runtime", "estimate_cost"],
    requiredInputs: ["pump relationship", "runtime", "tariff context"],
    generatedEvents: ["pumping_runtime", "pumping_cost_estimate"],
    limitations: ["Cost optimization never overrides agronomic constraints."],
  },
  {
    key: "ops",
    label: "Terris Ops",
    description: "Beta last-mile field tasks from recommendations, anomalies, and missing evidence.",
    status: "beta",
    flag: "TERRIS_OPS_ENABLED",
    route: "tasks",
    capabilities: ["create_task", "acknowledge", "start", "complete", "attach_evidence"],
    requiredInputs: ["field", "task type", "priority", "status"],
    generatedEvents: ["task_created", "task_completed"],
    limitations: ["Not payroll, HR, or generic scheduling."],
  },
  {
    key: "proof",
    label: "Terris Proof",
    description: "Beta evidence packets generated from operational field-ledger events.",
    status: "beta",
    flag: "TERRIS_PROOF_ENABLED",
    route: "ledger",
    capabilities: ["generate_packet", "export_json", "preserve_truth_labels"],
    requiredInputs: ["event IDs", "date window", "scope"],
    generatedEvents: ["evidence_attached", "evidence_packet_generated"],
    limitations: ["Evidence packets are not official regulatory filings or legal advice."],
  },
  {
    key: "protect",
    label: "Terris Protect",
    description: "Preview boundary for future crop-protection observations and tasking.",
    status: "preview",
    flag: "TERRIS_PROTECT_ENABLED",
    capabilities: ["preview_event_taxonomy"],
    requiredInputs: ["future pest, disease, weather, and label-safe context"],
    generatedEvents: ["crop_protection_task"],
    limitations: ["No chemical prescription, pesticide recommendation, or regulatory claim."],
  },
  {
    key: "risk_api",
    label: "Terris Risk API",
    description: "Reserved institutional contract boundary for future portfolio risk summaries.",
    status: "reserved",
    flag: "TERRIS_RISK_API_ENABLED",
    capabilities: ["reserved_contract_documentation"],
    requiredInputs: ["portfolio scope", "risk signals", "evidence references"],
    generatedEvents: [],
    limitations: ["No public endpoint or fake portfolio metrics in this pass."],
  },
];

export function terrisModuleRegistryForMode(mode = "real") {
  return baseRegistry.map((module) => {
    const flagged = TERRIS_FEATURE_FLAGS[module.flag];
    const demoEnabled = mode === "demo" && module.status === "beta";
    const enabled = module.key === "water"
      ? flagged
      : module.key === "protect" || module.key === "risk_api"
        ? flagged
        : Boolean(flagged || demoEnabled);
    return {
      ...module,
      enabled,
      representativeDemo: Boolean(demoEnabled && !flagged),
    };
  });
}

export const terrisModuleRegistry = terrisModuleRegistryForMode("real");
export const enabledTerrisModules = (mode = "real") => terrisModuleRegistryForMode(mode).filter((module) => module.enabled);
