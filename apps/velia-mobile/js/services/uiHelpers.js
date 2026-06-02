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
    if (value >= 0.75) return "High";
    if (value >= 0.5) return "Moderate";
    return "Low";
  }
  const text = String(value).trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Moderate";
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
