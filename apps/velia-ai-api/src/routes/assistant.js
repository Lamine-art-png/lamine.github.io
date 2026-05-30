import { Router } from "express";
import { aiOrchestrator } from "../ai/aiOrchestrator.js";

export const assistantRouter = Router();

assistantRouter.post("/query", async (req, res, next) => {
  try {
    const body = req.body || {};
    const result = await aiOrchestrator.run("assistant query", {
      query: body.query || body.question || "Why?",
      decision: body.decision,
      fieldId: body.fieldId,
      field: body.field,
      verification: body.verification,
      recommendationHistory: body.recommendationHistory || [],
      language: body.language || "en",
    });
    return res.json(result);
  } catch (error) {
    return next(error);
  }
});
