export const fieldReasoningAgent = {
  evaluateDataQuality(field, context) {
    const missingData = [];
    if (!field.soilType) missingData.push("soil type");
    if (!field.lastIrrigationAt) missingData.push("last irrigation");
    if (!field.dataSource || field.dataSource === "neither") missingData.push("sensor/controller data");
    if (!context.weather || context.weather.stale) missingData.push("fresh weather");
    return {
      missingData,
      confidenceDrivers: [
        field.lastObservation ? "recent observation" : "no recent observation",
        field.dataSource && field.dataSource !== "neither" ? "connected data source" : "manual-only inputs",
      ],
    };
  },
};
