export const allowedActions = ["irrigate", "wait", "check field first", "monitor", "update missing data", "escalate to advisor"];
export const allowedUrgencies = ["high", "medium", "low"];

export const decisionResponseSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    action: {
      type: "string",
      enum: allowedActions,
      description: "Recommended irrigation action, constrained by the deterministic safety layer.",
    },
    timing: { type: "string", description: "Plain-language timing window for the action." },
    urgency: { type: "string", enum: allowedUrgencies },
    estimatedDurationRange: { type: "string", description: "Range or field-check duration; never an exact guarantee." },
    reasons: { type: "array", items: { type: "string" } },
    uncertainties: { type: "array", items: { type: "string" } },
    missingData: { type: "array", items: { type: "string" } },
    fieldChecks: { type: "array", items: { type: "string" } },
    risks: { type: "array", items: { type: "string" } },
    nextBestAction: { type: "string" },
    safetyNotes: { type: "array", items: { type: "string" } },
    verificationPlan: { type: "array", items: { type: "string" } },
  },
  required: [
    "action",
    "timing",
    "urgency",
    "estimatedDurationRange",
    "reasons",
    "uncertainties",
    "missingData",
    "fieldChecks",
    "risks",
    "nextBestAction",
    "safetyNotes",
    "verificationPlan",
  ],
};

const arrayFields = ["reasons", "uncertainties", "missingData", "fieldChecks", "risks", "safetyNotes", "verificationPlan"];
const stringFields = ["action", "timing", "urgency", "estimatedDurationRange", "nextBestAction"];

export function parseDecisionJson(text) {
  if (typeof text !== "string" || !text.trim()) throw new Error("Model returned empty text");
  const trimmed = text.trim().replace(/^```json\s*/i, "").replace(/^```\s*/i, "").replace(/```$/i, "").trim();
  return JSON.parse(trimmed);
}

export function validateDecisionResponse(value) {
  const errors = [];
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, errors: ["Decision response must be an object"] };
  }

  for (const key of decisionResponseSchema.required) {
    if (!(key in value)) errors.push(`Missing ${key}`);
  }
  for (const key of stringFields) {
    if (key in value && typeof value[key] !== "string") errors.push(`${key} must be a string`);
  }
  for (const key of arrayFields) {
    if (key in value && !Array.isArray(value[key])) errors.push(`${key} must be an array`);
  }
  if (value.action && !allowedActions.includes(value.action)) errors.push(`Invalid action ${value.action}`);
  if (value.urgency && !allowedUrgencies.includes(value.urgency)) errors.push(`Invalid urgency ${value.urgency}`);

  return { ok: errors.length === 0, errors };
}

export function normalizeDecisionResponse(value, fallback = {}) {
  const normalized = {};
  for (const key of stringFields) normalized[key] = typeof value?.[key] === "string" ? value[key] : fallback[key] || "";
  for (const key of arrayFields) normalized[key] = Array.isArray(value?.[key]) ? value[key].map(String).filter(Boolean) : fallback[key] || [];
  if (!allowedActions.includes(normalized.action)) normalized.action = fallback.action || "check field first";
  if (!allowedUrgencies.includes(normalized.urgency)) normalized.urgency = fallback.urgency || "medium";
  return normalized;
}
