export const fieldReasoningAgent = {
  evaluate(field, weather) {
    const missingData = [];
    if (!field.soilType) missingData.push("soil type");
    if (!field.lastIrrigationAt) missingData.push("last irrigation");
    if (!weather || weather.stale) missingData.push("fresh weather");
    return { missingData, confidenceDrivers: [field.lastObservation ? "recent observation" : "no recent observation"] };
  },
};
