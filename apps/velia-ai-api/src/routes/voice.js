import { Router } from "express";
import { detectIntent } from "../services/voiceIntent.js";

export const voiceRouter = Router();

voiceRouter.post("/interpret", async (req, res, next) => {
  try {
    const transcript = String(req.body?.transcript || "");
    const fieldId = req.body?.fieldId || null;
    const intent = detectIntent(transcript);

    return res.json({
      type: "voice_intent",
      transcript,
      intent,
      action: {
        type: intent === "LOG_IRRIGATION" ? "log_irrigation" : intent === "UPDATE_CONDITION" ? "update_condition" : "noop",
        payload: { fieldId, source: "voice" },
      },
    });
  } catch (error) {
    return next(error);
  }
});
