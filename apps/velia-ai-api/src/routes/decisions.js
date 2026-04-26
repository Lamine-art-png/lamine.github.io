import { Router } from "express";
import { aiOrchestrator } from "../ai/aiOrchestrator.js";
import { badRequest, requireFields } from "../services/validation.js";

export const decisionsRouter = Router();

decisionsRouter.post("/daily", async (req, res, next) => {
  try {
    const body = req.body || {};
    const required = requireFields(body, ["field", "weather"]);
    if (!required.ok) return badRequest(res, required.missing);

    const result = await aiOrchestrator.run("daily irrigation decision", {
      field: body.field,
      weather: body.weather,
      logs: body.logs || [],
      observations: body.observations || [],
      language: body.language || "en",
    });

    return res.json(result);
  } catch (error) {
    return next(error);
  }
});
