export const demoScenarios = {
  baseline: {
    weatherOverride: { heatRisk: "low", frostRisk: "low", rainChance: 18, forecastSummary: "Stable weather expected." },
    observation: "Looks normal",
    stress: "moderate",
  },
  hotDry: {
    weatherOverride: { heatRisk: "elevated", frostRisk: "low", rainChance: 6, forecastSummary: "Hot and dry. Water demand is elevated." },
    observation: "Looks dry",
    stress: "high",
  },
  coolWet: {
    weatherOverride: { heatRisk: "low", frostRisk: "low", rainChance: 68, forecastSummary: "Cool and wet. Delay irrigation unless soil dries." },
    observation: "Looks too wet",
    stress: "low",
  },
};

export const demoProfile = {
  role: "farmer",
  farm: { name: "Demo Farm", location: "Napa Valley", units: "metric", hardware: "connected" },
  language: "en",
  fields: [
    {
      id: "demo-field-1",
      name: "Field 1",
      crop: "Grapes",
      acreage: 45,
      irrigationMethod: "Drip",
      soilType: "Loam",
      location: "North parcel",
      coordinates: { lat: 38.53, lon: -122.27 },
      dataSource: "controller",
      lastIrrigationAt: new Date(Date.now() - 36 * 3600000).toISOString(),
      usualDurationMin: 90,
      waterSource: "Borehole",
      waterStressLevel: "moderate",
      lastObservation: "Looks dry",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    },
  ],
  irrigationLogs: [],
  fieldNotes: [],
  observations: [],
};
