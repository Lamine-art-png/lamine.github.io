export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

export function confidenceText(value) {
  if (value == null || value === "") return "Moderate";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "Moderate";
    if (value >= 0.75) return "High";
    if (value >= 0.5) return "Moderate";
    return "Low";
  }
  const text = String(value).trim();
  if (!text || text.toLowerCase() === "undefined" || text.toLowerCase() === "nan") return "Moderate";
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Moderate";
}

export function confidencePresentation(value, rec = {}) {
  const label = confidenceText(value);
  const numeric = typeof value === "number" && Number.isFinite(value) ? Math.round(value * 100) : null;
  const missing = rec.missingData || [];
  const fieldChecks = rec.fieldChecks || [];
  const explanation = rec.confidenceExplanation
    || (label === "High"
      ? "Velia has enough recent field and weather context for this recommendation."
      : label === "Low"
        ? "Velia needs fresher or more complete field evidence before confidence improves."
        : "Velia has usable context, with a few details that would improve certainty.");
  const improve = rec.improveConfidence
    || fieldChecks[0]
    || (missing.length ? `Add ${missing.slice(0, 2).join(" and ")}.` : "Record a field check to improve today's recommendation.");
  return { label, numeric, explanation, improve };
}

export const actionMappings = {
  irrigate: { primary: "Log irrigation", secondary: "Review reasoning", primaryAction: "log", secondaryAction: "reasoning" },
  "check field first": { primary: "Record field check", secondary: "Ask Velia", primaryAction: "condition", secondaryAction: "assistant" },
  wait: { primary: "Set reminder", secondary: "View weather risk", primaryAction: "reminder", secondaryAction: "weather" },
  monitor: { primary: "Update field condition", secondary: "Ask Velia", primaryAction: "condition", secondaryAction: "assistant" },
  "update missing data": { primary: "Complete field data", secondary: "Ask Velia", primaryAction: "field-detail", secondaryAction: "assistant" },
};

export function normalizeDecisionAction(action = "") {
  const text = String(action || "").toLowerCase().trim().replaceAll("_", " ").replaceAll("-", " ");
  if (text.includes("check") || text.includes("field first")) return "check field first";
  if (text.includes("missing") || text.includes("update data") || text.includes("complete")) return "update missing data";
  if (text.includes("wait")) return "wait";
  if (text.includes("irrigate") || text.includes("water now")) return "irrigate";
  return "monitor";
}

export function actionMappingFor(action) {
  return actionMappings[normalizeDecisionAction(action)] || actionMappings.monitor;
}

export function dedupeActivityRows(rows, { windowMinutes = 45, limit = 5 } = {}) {
  const sorted = rows
    .filter((row) => row?.at && row?.title)
    .sort((a, b) => new Date(b.at) - new Date(a.at));
  const kept = [];
  for (const row of sorted) {
    const isDuplicate = kept.some((existing) => {
      const sameKind = existing.title === row.title && existing.fieldId === row.fieldId && existing.body === row.body;
      const close = Math.abs(new Date(existing.at) - new Date(row.at)) <= windowMinutes * 60000;
      return sameKind && close;
    });
    if (!isDuplicate) kept.push(row);
    if (kept.length >= limit) break;
  }
  return kept;
}

export function alertPriority(alert) {
  const severity = { critical: 4, high: 3, medium: 2, low: 1 }[String(alert?.severity || "low").toLowerCase()] || 1;
  const type = String(alert?.type || "").toLowerCase();
  const urgency = type.includes("frost") || type.includes("verification") || type.includes("heat") ? 3 : type.includes("stale") || type.includes("confidence") ? 2 : 1;
  return { severity, urgency };
}

export function alertGroup(alert) {
  const p = alertPriority(alert);
  if (p.severity >= 3 || p.urgency >= 3) return "Act now";
  if (p.severity >= 2 || p.urgency >= 2) return "Review today";
  return "Monitoring";
}

export function sortAlerts(alerts) {
  return [...alerts].sort((a, b) => {
    const pa = alertPriority(a);
    const pb = alertPriority(b);
    return pb.severity - pa.severity || pb.urgency - pa.urgency || new Date(b.createdAt || 0) - new Date(a.createdAt || 0);
  });
}

export function shortDate(date = new Date()) {
  return new Intl.DateTimeFormat(undefined, { weekday: "long", month: "short", day: "numeric" }).format(new Date(date));
}

export function relativeTime(value) {
  if (!value) return "Not logged";
  const date = new Date(value);
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
  if (!Number.isFinite(minutes)) return "Recently";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} hr ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function weatherAgeLabel(weather) {
  const sourceTs = weather?.weatherTimestamp || weather?.lastUpdated || weather?.cachedAt;
  const minutes = weather?.freshness?.ageMinutes ?? (sourceTs ? Math.max(0, Math.round((Date.now() - new Date(sourceTs).getTime()) / 60000)) : null);
  if (minutes == null || !Number.isFinite(minutes)) return "Weather age unknown";
  if (minutes < 60) return `${minutes} min old`;
  return `${Math.round(minutes / 60)} hr old`;
}
