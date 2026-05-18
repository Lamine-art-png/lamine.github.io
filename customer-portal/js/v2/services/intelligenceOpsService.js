import { STATUS_FLOW } from "../state/store.js";

export function filteredRecommendations(app, filters) {
  return app.recommendations.filter((item) => {
    if (filters.farm !== "all" && item.farmId !== filters.farm) return false;
    if (filters.zone !== "all" && item.zoneId !== filters.zone) return false;
    if (filters.provider !== "all" && !item.source.toLowerCase().includes(filters.provider)) return false;
    if (filters.status !== "all" && item.status !== filters.status) return false;
    return true;
  });
}

export function timelineForRecommendation(app, recommendationId) {
  const events = app.verificationLogs.filter((item) => item.recommendationId === recommendationId);
  return events.sort((a, b) => (a.at < b.at ? 1 : -1));
}

export function progressStatus(currentStatus) {
  const idx = STATUS_FLOW.indexOf(currentStatus);
  return STATUS_FLOW.map((status, index) => ({ status, reached: idx >= index }));
}
