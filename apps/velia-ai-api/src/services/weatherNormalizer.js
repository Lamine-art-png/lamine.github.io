export function normalizeWeatherContext(input = {}) {
  const lat = input.lat ?? null;
  const lon = input.lon ?? null;
  const location = input.location || (lat && lon ? `${lat},${lon}` : "unknown");
  return {
    location,
    lat,
    lon,
    stale: Boolean(input.stale),
    source: input.source || "mock",
  };
}
