export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

export function formatValue(value, fallback = "—") {
  if (value === undefined || value === null || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.join(", ") : fallback;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function statusClass(status = "") {
  const normalized = String(status).toLowerCase();
  if (["live", "connected", "verified", "complete", "ready", "ok", "active", "applied"].some((key) => normalized.includes(key))) return "success";
  if (["pending", "awaiting", "configured", "scheduled", "partial"].some((key) => normalized.includes(key))) return "warning";
  if (["failed", "error", "disconnected", "missing"].some((key) => normalized.includes(key))) return "danger";
  return "neutral";
}

export function listItems(items = []) {
  if (!items.length) return '<li class="muted">None reported.</li>';
  return items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}
