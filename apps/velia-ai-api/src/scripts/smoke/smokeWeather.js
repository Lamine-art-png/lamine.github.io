import "dotenv/config";
import { OpenWeatherProvider } from "../../providers/OpenWeatherProvider.js";

const apiKey = process.env.OPENWEATHER_API_KEY || "";
if (!apiKey) {
  console.error(`SMOKE FAIL: OPENWEATHER_API_KEY is not set. Add it to .env to run this smoke test.`);
  process.exit(1);
}
const lat = Number(process.env.SMOKE_LAT || "36.7783");
const lon = Number(process.env.SMOKE_LON || "-119.4179");
const location = process.env.SMOKE_LOCATION || "California Central Valley";

console.log(`Provider: openweather  location: ${location}  lat=${lat}  lon=${lon}`);
const provider = new OpenWeatherProvider({ apiKey });
const start = Date.now();
let weather;
try {
  weather = await provider.getContext({ lat, lon, location });
} catch (err) {
  console.error(`SMOKE FAIL: OpenWeather error: ${err.message}`);
  process.exit(1);
}
const latencyMs = Date.now() - start;

console.log(`Latency      : ${latencyMs} ms`);
console.log(`Provider used: ${weather.weatherSource || "(unknown)"}`);
console.log(`Fallback state: ${weather.fallbackStatus || "live — no fallback"}`);
console.log(`Stale        : ${weather.stale}`);
console.log(`Cached       : ${weather.cached}`);
console.log(`Temperature  : ${weather.temperature}°C`);
console.log(`Rain chance  : ${weather.rainChance}%`);
console.log(`Heat risk    : ${weather.heatRisk}`);
console.log(`ET label     : ${weather.etLabel}`);
console.log(`Timestamp    : ${weather.weatherTimestamp}`);

if (!weather.weatherTimestamp) {
  console.error("SMOKE FAIL: Missing weatherTimestamp in response.");
  process.exit(1);
}
if (weather.fallbackStatus) {
  console.warn(`WARNING: Fallback was used — ${weather.fallbackStatus}`);
}
console.log("Weather smoke test passed.");
