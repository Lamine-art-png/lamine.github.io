export type PlanId = "free" | "professional" | "team" | "network" | "enterprise";

export type CommercialBoundaryDetail = {
  status?: number;
  code?: string;
  feature?: string;
  feature_state?: string;
  metric?: string;
  used?: number;
  reserved?: number;
  limit?: number;
  remaining?: number;
  recommended_plan?: string;
  message?: string;
  source?: string;
  conversion_context?: string;
};

export type CommercialPlan = {
  nameKey: string;
  priceAmount?: string;
  customPrice?: boolean;
  bullets: [string, string, string];
};

export const ORDER: PlanId[] = ["free", "professional", "team", "network", "enterprise"];

export const PLAN: Record<PlanId, CommercialPlan> = {
  free: { nameKey: "commercialBoundary.plan.free", priceAmount: "$0", bullets: ["commercialBoundary.plan.free.bullet1", "commercialBoundary.plan.free.bullet2", "commercialBoundary.plan.free.bullet3"] },
  professional: { nameKey: "commercialBoundary.plan.professional", priceAmount: "$299", bullets: ["commercialBoundary.plan.professional.bullet1", "commercialBoundary.plan.professional.bullet2", "commercialBoundary.plan.professional.bullet3"] },
  team: { nameKey: "commercialBoundary.plan.team", priceAmount: "$799", bullets: ["commercialBoundary.plan.team.bullet1", "commercialBoundary.plan.team.bullet2", "commercialBoundary.plan.team.bullet3"] },
  network: { nameKey: "commercialBoundary.plan.network", priceAmount: "$1,500", bullets: ["commercialBoundary.plan.network.bullet1", "commercialBoundary.plan.network.bullet2", "commercialBoundary.plan.network.bullet3"] },
  enterprise: { nameKey: "commercialBoundary.plan.enterprise", customPrice: true, bullets: ["commercialBoundary.plan.enterprise.bullet1", "commercialBoundary.plan.enterprise.bullet2", "commercialBoundary.plan.enterprise.bullet3"] },
};

export const FEATURE_TITLE_KEY: Record<string, string> = {
  "reports.generate": "commercialBoundary.feature.reportsGenerate",
  "reports.pdf_export": "commercialBoundary.feature.reportsPdfExport",
  "reports.email_delivery": "commercialBoundary.feature.reportsEmailDelivery",
  "connectors.manual_upload": "commercialBoundary.feature.connectorsManualUpload",
  "connectors.live": "commercialBoundary.feature.connectorsLive",
  "connectors.oauth_documents": "commercialBoundary.feature.connectorsOauthDocuments",
  "connectors.custom_api": "commercialBoundary.feature.connectorsCustomApi",
  "connectors.custom_integration": "commercialBoundary.feature.connectorsCustomIntegration",
  "team.invite": "commercialBoundary.feature.teamInvite",
  "admin.requests": "commercialBoundary.feature.adminRequests",
  "agents.execute_safe": "commercialBoundary.feature.agentsExecuteSafe",
  "agents.execute_approval_gated": "commercialBoundary.feature.agentsExecuteApproval",
  "intelligence.deep_analysis": "commercialBoundary.feature.intelligenceDeepAnalysis",
};

export const CAPABILITY_KEY: Record<string, string> = {
  "reports.generate": "commercialBoundary.capability.reportsGenerate",
  "reports.pdf_export": "commercialBoundary.capability.reportsPdfExport",
  "reports.email_delivery": "commercialBoundary.capability.reportsEmailDelivery",
  "connectors.manual_upload": "commercialBoundary.capability.connectorsManualUpload",
  "connectors.live": "commercialBoundary.capability.connectorsLive",
  "connectors.oauth_documents": "commercialBoundary.capability.connectorsOauthDocuments",
  "connectors.custom_api": "commercialBoundary.capability.connectorsCustomApi",
  "connectors.custom_integration": "commercialBoundary.capability.connectorsCustomIntegration",
  "team.invite": "commercialBoundary.capability.teamInvite",
  "admin.requests": "commercialBoundary.capability.adminRequests",
  "agents.execute_safe": "commercialBoundary.capability.agentsExecuteSafe",
  "agents.execute_approval_gated": "commercialBoundary.capability.agentsExecuteApproval",
  "intelligence.deep_analysis": "commercialBoundary.capability.intelligenceDeepAnalysis",
};

export const METRIC_KEY: Record<string, string> = {
  workspaces: "commercialBoundary.metric.workspaces",
  workspace_count: "commercialBoundary.metric.workspaces",
  seats: "commercialBoundary.metric.seats",
  seat_count: "commercialBoundary.metric.seats",
  intelligence_actions: "commercialBoundary.metric.intelligenceActions",
  agroai_actions: "commercialBoundary.metric.intelligenceActions",
  ai_actions: "commercialBoundary.metric.intelligenceActions",
  ai_action: "commercialBoundary.metric.intelligenceActions",
  evidence_upload: "commercialBoundary.metric.evidenceUploads",
  evidence_uploads: "commercialBoundary.metric.evidenceUploads",
  active_connector: "commercialBoundary.metric.activeConnectors",
  active_connectors: "commercialBoundary.metric.activeConnectors",
  connectors_active: "commercialBoundary.metric.activeConnectors",
  live_connectors: "commercialBoundary.metric.activeConnectors",
  report_generation: "commercialBoundary.metric.reportGenerations",
  report_generations: "commercialBoundary.metric.reportGenerations",
  reports_generated: "commercialBoundary.metric.reportGenerations",
  report_export: "commercialBoundary.metric.pdfExports",
  pdf_exports: "commercialBoundary.metric.pdfExports",
  report_pdf_exports: "commercialBoundary.metric.pdfExports",
  email_deliveries: "commercialBoundary.metric.emailDeliveries",
  report_email_deliveries: "commercialBoundary.metric.emailDeliveries",
  agent_run: "commercialBoundary.metric.agentRuns",
  agent_runs: "commercialBoundary.metric.agentRuns",
  deep_investigation: "commercialBoundary.metric.deepAnalyses",
  deep_analyses: "commercialBoundary.metric.deepAnalyses",
  deep_analysis_runs: "commercialBoundary.metric.deepAnalyses",
};

export function canonicalPlan(value: unknown): PlanId {
  const raw = String(value || "free").toLowerCase();
  const aliases: Record<string, PlanId> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team" };
  const candidate = aliases[raw] || raw;
  return ORDER.includes(candidate as PlanId) ? candidate as PlanId : "free";
}

export function nextPlan(value: PlanId): PlanId {
  return ORDER[Math.min(ORDER.indexOf(value) + 1, ORDER.length - 1)];
}

export function isCommercialQuota(detail: CommercialBoundaryDetail) {
  return detail.code === "quota_exceeded" || (detail.status === 429 && Boolean(detail.metric) && detail.limit !== undefined);
}

export function shouldShowCommercialBoundary(detail: CommercialBoundaryDetail) {
  if (detail.status === 429) return isCommercialQuota(detail);
  return detail.status === 402 || ["upgrade_required", "subscription_inactive", "quota_exceeded"].includes(String(detail.code || ""));
}

export function usagePercent(detail: CommercialBoundaryDetail) {
  const used = Number(detail.used || 0) + Number(detail.reserved || 0);
  const limit = Number(detail.limit || 0);
  return limit ? Math.min(100, Math.round((used / limit) * 100)) : 100;
}
