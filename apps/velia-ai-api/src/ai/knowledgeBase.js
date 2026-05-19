export const seedDocs = [
  { id: "irrigation-principles", text: "Balance crop demand, weather, irrigation logs, and observations before recommending action.", topic: "irrigation" },
  { id: "soil-holding", text: "Unknown soil type lowers confidence and should trigger field checks.", topic: "soil" },
  { id: "crop-demand", text: "Crop demand increases under high heat and high evapotranspiration.", topic: "crop" },
  { id: "weather-risk", text: "Expected rain may support wait or check-first actions.", topic: "weather" },
  { id: "observation", text: "Farmer observations such as looks dry or stressed improve practical recommendations.", topic: "observation" },
  { id: "uncertainty-safety", text: "Show uncertainty. Never guarantee yield or savings. Distinguish recommendation from instruction.", topic: "safety" },
  { id: "agroai-principles", text: "AGRO-AI principles: simple, trust-building, fast daily use, clear next actions.", topic: "product" },
];

export const graphSchema = {
  entities: ["crop", "soil_type", "irrigation_method", "weather_risk", "field_observation", "recommendation", "confidence_factor"],
  relationships: [
    { from: "weather_risk", to: "recommendation", type: "increases_risk" },
    { from: "soil_type", to: "confidence_factor", type: "reduces_confidence" },
    { from: "field_observation", to: "recommendation", type: "requires_check" },
    { from: "crop", to: "recommendation", type: "affects_water_demand" },
  ],
};

export function traverseGraph(entity) {
  return graphSchema.relationships.filter((edge) => edge.from === entity || edge.to === entity);
}
