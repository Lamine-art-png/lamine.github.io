import { Router } from "express";
import { aiOrchestrator } from "../ai/aiOrchestrator.js";

export const assistantRouter = Router();

assistantRouter.post("/query", async (req, res, next) => {
  try {
    const body = req.body || {};
    const result = await aiOrchestrator.run("explain recommendation", {
      decision: body.decision,
      recommendationHistory: body.recommendationHistory || [],
      language: body.language || "en",
    });
    return res.json(result);
  } catch (error) {
    return next(error);
  }
});
