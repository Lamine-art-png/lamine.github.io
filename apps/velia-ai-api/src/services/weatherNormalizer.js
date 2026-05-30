export function normalizeWeatherContext(input = {}) {
  const lat = input.lat ?? input.latitude ?? input.coordinates?.lat ?? null;
  const lon = input.lon ?? input.longitude ?? input.coordinates?.lon ?? null;
  const location = input.location || (lat != null && lon != null ? `${lat},${lon}` : "unknown");
  return {
    location,
    lat,
    lon,
    stale: Boolean(input.stale),
    source: input.source || "mock",
  };
}
