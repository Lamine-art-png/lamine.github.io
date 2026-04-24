import { recommendationEngine } from "../services/recommendationEngine.js";

const now = new Date();
const iso = (hoursAgo = 0) => new Date(now.getTime() - hoursAgo * 3600 * 1000).toISOString();

export const mockUser = {
  id: "u-1",
  name: "Amina Diallo",
  role: "Farm Manager",
  language: "en",
  farmIds: ["farm-1"],
};

export const mockFarm = {
  id: "farm-1",
  name: "North Valley Farm",
  location: "Kaolack Region",
  timezone: "Africa/Dakar",
  acreage: 490,
  operationType: "commercial",
};

export const crops = [
  { id: "crop-maize", name: "Maize", stage: "Vegetative", idealMoistureRange: [20, 30] },
  { id: "crop-grapes", name: "Grapes", stage: "Fruit set", idealMoistureRange: [18, 28] },
  { id: "crop-tomato", name: "Tomato", stage: "Flowering", idealMoistureRange: [22, 32] },
];

export const fields = [
  {
    id: "field-1", farmId: "farm-1", name: "Field 1 - East Pivot", cropId: "crop-maize", acreage: 140,
    soilType: "Sandy loam", irrigationMethod: "Center pivot", status: "attention", waterStressLevel: "moderate",
    lastIrrigationAt: iso(42), dataSourceStatus: "weather_only",
  },
  {
    id: "field-2", farmId: "farm-1", name: "Field 2 - South Drip", cropId: "crop-grapes", acreage: 210,
    soilType: "Clay loam", irrigationMethod: "Drip", status: "critical", waterStressLevel: "high",
    lastIrrigationAt: iso(66), dataSourceStatus: "controller_connected",
  },
  {
    id: "field-3", farmId: "farm-1", name: "Field 3 - River Block", cropId: "crop-tomato", acreage: 90,
    soilType: "Loam", irrigationMethod: "Sprinkler", status: "stable", waterStressLevel: "low",
    lastIrrigationAt: iso(18), dataSourceStatus: "sensor_connected",
  },
];

export const weather = {
  condition: "Hot and dry",
  temperatureC: 35,
  humidityPct: 34,
  rainProbabilityPct: 12,
  windKph: 14,
  summary: "High evapotranspiration expected through late afternoon.",
  date: now.toISOString().slice(0, 10),
};

export const alerts = [
  { id: "a1", type: "Water stress risk", severity: "high", fieldId: "field-2", action: "Inspect root zone moisture and irrigate if soil is dry.", timeSensitivity: "Within 4 hours", message: "Field 2 may reach stress threshold by evening.", createdAt: iso(1) },
  { id: "a2", type: "Heat event", severity: "medium", fieldId: "field-1", action: "Shift irrigation to early morning cycle.", timeSensitivity: "Today", message: "Heat peak expected 14:00–17:00.", createdAt: iso(2) },
  { id: "a3", type: "Frost risk", severity: "low", fieldId: "field-3", action: "Monitor night temperature trend.", timeSensitivity: "Next 48 hours", message: "Marginal overnight cooling possible.", createdAt: iso(10) },
  { id: "a4", type: "Missed irrigation", severity: "medium", fieldId: "field-2", action: "Confirm last irrigation execution log.", timeSensitivity: "Today", message: "No controller completion record from planned run.", createdAt: iso(5) },
  { id: "a5", type: "Data sync issue", severity: "medium", fieldId: null, action: "Review connection and retry sync.", timeSensitivity: "When connected", message: "Controller sync delayed due to connectivity.", createdAt: iso(3) },
  { id: "a6", type: "Field observation needed", severity: "low", fieldId: "field-1", action: "Capture a soil surface photo before evening.", timeSensitivity: "Today", message: "Recommendation confidence is moderate due to missing ground observation.", createdAt: iso(6) },
];

export const notes = [
  { id: "n1", fieldId: "field-2", text: "Leaves curling near noon, moisture feels low at top 10 cm.", createdAt: iso(4), source: "manual", synced: true },
];

export const irrigationLogs = [
  { id: "log-1", fieldId: "field-3", amountMm: 12, durationMin: 55, method: "Sprinkler", performedAt: iso(18), source: "controller" },
  { id: "log-2", fieldId: "field-1", amountMm: 10, durationMin: 46, method: "Center pivot", performedAt: iso(42), source: "manual" },
];

export const reportSummary = {
  id: "r-1",
  periodLabel: "This week",
  recommendedMm: 74,
  loggedMm: 68,
  estimatedWaterSavedPct: null,
  fieldPerformanceSummary: "Field 2 remains highest priority; Field 3 is stable with low stress.",
};

export const dailyConsistency = { streakDays: 6, checkInsThisWeek: 5, trend: "steady" };

export function getFieldById(fieldId) {
  return fields.find((field) => field.id === fieldId);
}

export function getCrop(cropId) {
  return crops.find((crop) => crop.id === cropId);
}

export function generateRecommendations() {
  return fields.map((field) => recommendationEngine.generateRecommendation({ field, weather, crop: getCrop(field.cropId) }));
}
