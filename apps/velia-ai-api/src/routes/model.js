import { Router } from "express";
import { modelRouter } from "../ai/modelRouter.js";
import { config } from "../config.js";

export const modelRouterApi = Router();

modelRouterApi.get("/status", (_req, res) => {
  const provider = modelRouter.llmProvider();
  return res.json({
    terrisCore: {
      enabled: config.terrisCoreEnabled,
      configured: config.terrisCoreEnabled && Boolean(config.terrisCoreBaseUrl),
      baseUrlConfigured: Boolean(config.terrisCoreBaseUrl),
      requestedProvider: config.llmProvider,
      activeProvider: provider.name,
      model: provider.model,
      mode: provider.mode,
      trafficPercent: config.terrisCoreTrafficPercent,
      fallbackProvider: config.terrisCoreFallbackProvider,
      fallbackArmed: Boolean(provider.fallback),
      fallbackReason: provider.fallbackReason || null,
    },
    policy: {
      deterministicAgronomyFirst: true,
      preserveTruthLabels: true,
      requireEvidenceForExecutionAndVerification: true,
      frontierFallbackAllowed: true,
    },
  });
});
