export const seedKnowledgeDocuments = [
  {
    id: "kb-irrigation-principles",
    title: "Irrigation Decision Principles",
    text: "Irrigation recommendations should balance crop demand, weather risk, recent irrigation, and field observations. When uncertainty is high, recommend a field check before watering.",
    topic: "irrigation",
  },
  {
    id: "kb-soil-holding",
    title: "Soil Water Holding Basics",
    text: "Soil type influences water holding and irrigation frequency. Unknown soil type should lower confidence and trigger data collection guidance.",
    topic: "soil",
  },
  {
    id: "kb-crop-demand",
    title: "Crop Water Demand",
    text: "Crop stage and heat load affect evapotranspiration. Elevated heat risk increases water demand and urgency checks.",
    topic: "crop",
  },
  {
    id: "kb-weather-risk",
    title: "Weather Risk Interpretation",
    text: "Rain probability and forecasted rainfall can justify waiting before irrigation. Stale weather data should be clearly disclosed.",
    topic: "weather",
  },
  {
    id: "kb-confidence",
    title: "Confidence and Missing Data",
    text: "Confidence should reflect data quality: sensor availability, observation recency, weather freshness, and log completeness.",
    topic: "confidence",
  },
  {
    id: "kb-observation-guidance",
    title: "Field Observation Guidance",
    text: "Simple farmer observations such as looks dry or leaves stressed provide high practical value and should influence urgency.",
    topic: "observation",
  },
  {
    id: "kb-safe-wording",
    title: "Safe Wording and Limitations",
    text: "Never guarantee yields or exact savings. Distinguish recommendation from instruction. Show uncertainty and suggest checks when data is weak.",
    topic: "safety",
  },
];

export const knowledgeGraph = {
  entities: [
    "crop",
    "soil_type",
    "irrigation_method",
    "weather_risk",
    "field_observation",
    "recommendation",
    "confidence_factor",
  ],
  relationships: [
    { from: "weather_risk", to: "recommendation", type: "increases_risk" },
    { from: "soil_type", to: "confidence_factor", type: "reduces_confidence_when_unknown" },
    { from: "field_observation", to: "recommendation", type: "requires_check" },
    { from: "crop", to: "recommendation", type: "affects_water_demand" },
    { from: "confidence_factor", to: "recommendation", type: "supports_recommendation" },
  ],
};

export function traverseKnowledgeGraph(startEntity) {
  return knowledgeGraph.relationships.filter((edge) => edge.from === startEntity || edge.to === startEntity);
}
