import { Router } from "express";
import { evaluateDecision, scenarios } from "../ai/evaluationHarness.js";

export const evaluationRouter = Router();

evaluationRouter.post("/run", (req, res, next) => {
  try {
    const decision = req.body?.decision || {};
    return res.json({
      scenarioCount: scenarios.length,
      scenarios,
      evaluation: evaluateDecision(decision),
    });
  } catch (error) {
    return next(error);
  }
});
