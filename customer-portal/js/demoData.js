export const demoWorkspace = {
  id: "demo-agroai-workspace",
  name: "AGRO-AI Demo Workspace",
  mode: "Demo",
  source: "Mixed",
  label: "Demo data — not production telemetry",
};

export const demoProviders = [
  {
    id: "wiseconn-demo",
    name: "WiseConn",
    description: "Demo connection representing live WiseConn runtime capabilities.",
    status: "Connected source live",
    connectionHealth: "Demo connection healthy",
    farmsOrTargets: "2 farms",
    zonesOrSensors: "3 zones",
    reads: "Farms, zones, irrigation events, controller context",
    generates: "Water recommendations, execution tasks, planned-vs-applied verification",
    lastChecked: "2026-05-14T15:30:00Z",
    limitation: "Demo rows are embedded and clearly separated from live WiseConn API calls.",
  },
  {
    id: "talgil-demo",
    name: "Talgil",
    description: "Demo connection representing configured Talgil controller environments.",
    status: "Connected source live",
    connectionHealth: "Demo runtime reachable",
    farmsOrTargets: "1 target",
    zonesOrSensors: "1 irrigation line + sensor catalog",
    reads: "Controller targets, sensor catalog, telemetry status",
    generates: "Normalized context for recommendations and verification workflows",
    lastChecked: "2026-05-14T15:24:00Z",
    limitation: "Talgil runtime health is surfaced separately when live status is available; demo records do not claim live telemetry.",
  },
];

export const demoFarms = [
  {
    id: "alpha-vineyard",
    name: "Alpha Vineyard",
    provider: "WiseConn demo connection",
    zones: [
      {
        id: "block-a-north",
        name: "Block A North",
        crop: "Cabernet Sauvignon",
        soil: "Clay loam",
        controllerSource: "WiseConn demo connection",
        dataQuality: "High",
        confidence: "86%",
        recommendation: "Irrigate 42 min tonight after ETo peak",
        scheduledStatus: "Scheduled",
        appliedStatus: "Awaiting controller execution",
        observedOutcome: "Awaiting field observation",
        verificationStatus: "Verification pending",
        warning: "Wind forecast elevated; confirm emitter uniformity after application.",
      },
      {
        id: "block-b-south",
        name: "Block B South",
        crop: "Merlot",
        soil: "Sandy loam",
        controllerSource: "WiseConn demo connection",
        dataQuality: "Medium",
        confidence: "78%",
        recommendation: "Hold irrigation; reassess after morning telemetry",
        scheduledStatus: "Not scheduled",
        appliedStatus: "No controller task created",
        observedOutcome: "No stress observed",
        verificationStatus: "Verified no-action",
        warning: "One moisture sensor missing recent reading; confidence reduced.",
      },
    ],
  },
  {
    id: "delta-almonds",
    name: "Delta Almonds",
    provider: "WiseConn demo connection",
    zones: [
      {
        id: "pump-zone-3",
        name: "Pump Zone 3",
        crop: "Almonds",
        soil: "Silt loam",
        controllerSource: "WiseConn demo connection",
        dataQuality: "High",
        confidence: "91%",
        recommendation: "Apply 18 mm before 05:00 local time",
        scheduledStatus: "Ready to schedule",
        appliedStatus: "Awaiting controller execution",
        observedOutcome: "Awaiting field observation",
        verificationStatus: "Verification pending",
        warning: "Pump energy tariff changes at 06:00; schedule before peak window.",
      },
    ],
  },
  {
    id: "west-citrus",
    name: "West Citrus",
    provider: "Talgil demo connection",
    zones: [
      {
        id: "citrus-east-line",
        name: "Citrus East Line",
        crop: "Citrus",
        soil: "Loam",
        controllerSource: "Talgil demo connection",
        dataQuality: "Medium",
        confidence: "74%",
        recommendation: "Apply short pulse irrigation and verify line pressure",
        scheduledStatus: "Configured controller target",
        appliedStatus: "Awaiting controller execution",
        observedOutcome: "Pressure observation required",
        verificationStatus: "Verification pending",
        warning: "Pressure sensor coverage is partial in this demo scenario.",
      },
    ],
  },
];

export const demoRecommendation = {
  decision: "Irrigate tonight",
  timing: "Start after 21:00 local time",
  duration: "42 minutes",
  depth: "14 mm",
  confidence: "86%",
  dataQuality: "High",
  keyDrivers: ["Root-zone depletion trending upward", "No meaningful rain expected", "ETo remains elevated", "Controller schedule window is available"],
  sourceTraceSummary: "Demo context assembled from WiseConn demo connection, crop profile, soil profile, weather forecast, and field observation.",
  liveInputsUsed: ["Controller zone", "Recent irrigation history", "Weather forecast", "Crop and soil profile"],
  manualOverridesUsed: ["Field observation: mild canopy stress on west rows"],
  missingInputs: ["Pressure telemetry not available for this demo zone"],
  executionTask: "Create controller task for Block A North and assign irrigation manager confirmation.",
  verificationPlan: "Compare scheduled duration with controller-applied event, then request field observation within 12 hours.",
};

export const demoChain = [
  { label: "Recommended", status: "Complete", timestamp: "2026-05-14T15:15:00Z", owner: "AGRO-AI Intelligence Engine", evidence: "Recommendation generated with 86% confidence." },
  { label: "Scheduled", status: "Scheduled", timestamp: "2026-05-14T15:20:00Z", owner: "Irrigation Manager", evidence: "Controller task queued for nighttime window." },
  { label: "Applied", status: "Awaiting controller execution", timestamp: "", owner: "Controller Runtime", evidence: "Awaiting controller execution" },
  { label: "Observed", status: "Awaiting field observation", timestamp: "", owner: "Field Team", evidence: "Awaiting field observation" },
  { label: "Verified", status: "Verification pending", timestamp: "", owner: "AGRO-AI Verification", evidence: "Verification pending" },
];

export const demoReports = [
  { name: "Irrigation Intelligence Report", purpose: "Daily decision narrative with recommendations, risks, and next actions.", status: "Demo preview available", coverage: "All demo farms", lastGenerated: "Demo preview", action: "Preview report" },
  { name: "Planned vs Applied Report", purpose: "Compares scheduled tasks against controller-applied evidence.", status: "Demo preview available", coverage: "Operating chain", lastGenerated: "Demo preview", action: "Preview report" },
  { name: "Water Efficiency Summary", purpose: "Summarizes water use by farm, block, and controller environment.", status: "Report generation is coming online for this deployment.", coverage: "Demo + live-ready", lastGenerated: "", action: "View readiness" },
  { name: "Verification Compliance Report", purpose: "Shows which recommendations were scheduled, applied, observed, and verified.", status: "Demo preview available", coverage: "Decision chain", lastGenerated: "Demo preview", action: "Preview report" },
  { name: "Integration Health Report", purpose: "Reviews provider status, sync coverage, limitations, and telemetry freshness.", status: "Runtime status live", coverage: "WiseConn + Talgil", lastGenerated: "", action: "Check integrations" },
  { name: "Executive ROI Summary", purpose: "Frames water, energy, cost, and operational value for executive stakeholders.", status: "Report generation is coming online for this deployment.", coverage: "Executive layer", lastGenerated: "", action: "View readiness" },
];

export const demoAuditLog = [
  { time: "2026-05-14T15:01:00Z", actor: "Demo user", event: "user logged in", source: "Demo Environment", detail: "Demo session launched without credentials." },
  { time: "2026-05-14T15:04:00Z", actor: "Integration service", event: "environment connected", source: "WiseConn demo connection", detail: "Alpha Vineyard and Delta Almonds available in demo tenant." },
  { time: "2026-05-14T15:08:00Z", actor: "Integration service", event: "environment connected", source: "Talgil demo connection", detail: "West Citrus controller environment configured for demo." },
  { time: "2026-05-14T15:15:00Z", actor: "Intelligence Engine", event: "recommendation generated", source: "Block A North", detail: "Irrigate tonight with high confidence." },
  { time: "2026-05-14T15:20:00Z", actor: "Irrigation Manager", event: "execution confirmed", source: "Block A North", detail: "Schedule queued; execution evidence pending." },
  { time: "2026-05-14T15:26:00Z", actor: "Verification service", event: "verification completed", source: "Block B South", detail: "No-action recommendation verified." },
];
