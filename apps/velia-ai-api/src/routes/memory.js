import { Router } from "express";
import { memoryStore } from "../ai/memoryStore.js";
import { badRequest, requireFields } from "../services/validation.js";

export const memoryRouter = Router();

memoryRouter.post("/update", (req, res, next) => {
  try {
    const body = req.body || {};
    const required = requireFields(body, ["fieldId", "event"]);
    if (!required.ok) return badRequest(res, required.missing);

    const updated = memoryStore.updateFieldMemory(body.fieldId, body.event);
    return res.json({ ok: true, fieldId: body.fieldId, summary: memoryStore.summarizeFieldMemory(body.fieldId), eventCount: (updated.events || []).length });
  } catch (error) {
    return next(error);
  }
});
