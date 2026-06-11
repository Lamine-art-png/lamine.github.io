const env = globalThis?.TERRIS_FLAGS || {};

function flag(name, fallback) {
  const value = env[name];
  if (value === undefined || value === null) return fallback;
  return value === true || String(value).toLowerCase() === "true";
}

export const TERRIS_FEATURE_FLAGS = {
  TERRIS_WATER_ENABLED: flag("TERRIS_WATER_ENABLED", true),
  TERRIS_NUTRIENTS_ENABLED: flag("TERRIS_NUTRIENTS_ENABLED", true),
  TERRIS_ENERGY_ENABLED: flag("TERRIS_ENERGY_ENABLED", true),
  TERRIS_OPS_ENABLED: flag("TERRIS_OPS_ENABLED", true),
  TERRIS_PROOF_ENABLED: flag("TERRIS_PROOF_ENABLED", true),
  TERRIS_PROTECT_ENABLED: flag("TERRIS_PROTECT_ENABLED", false),
  TERRIS_RISK_API_ENABLED: flag("TERRIS_RISK_API_ENABLED", false),
};

export const terrisModuleRegistry = [
  {
    key: "water",
    label: "Terris Water",
    description: "Operational water recommendations, approvals, execution records, verification, and proof.",
    status: "active",
    enabled: TERRIS_FEATURE_FLAGS.TERRIS_WATER_ENABLED,
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
    enabled: TERRIS_FEATURE_FLAGS.TERRIS_NUTRIENTS_ENABLED,
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
    enabled: TERRIS_FEATURE_FLAGS.TERRIS_ENERGY_ENABLED,
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
    enabled: TERRIS_FEATURE_FLAGS.TERRIS_OPS_ENABLED,
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
    enabled: TERRIS_FEATURE_FLAGS.TERRIS_PROOF_ENABLED,
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
    enabled: TERRIS_FEATURE_FLAGS.TERRIS_PROTECT_ENABLED,
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
    enabled: TERRIS_FEATURE_FLAGS.TERRIS_RISK_API_ENABLED,
    capabilities: ["reserved_contract_documentation"],
    requiredInputs: ["portfolio scope", "risk signals", "evidence references"],
    generatedEvents: [],
    limitations: ["No public endpoint or fake portfolio metrics in this pass."],
  },
];

export const enabledTerrisModules = () => terrisModuleRegistry.filter((module) => module.enabled);
