const planMap = {
  "daily irrigation decision": ["getFarmProfile", "getFieldProfile", "getWeather", "getIrrigationLogs", "getFieldObservations", "retrieveKnowledge", "estimateIrrigationNeed", "calculateConfidence"],
  "explain recommendation": ["getRecommendationHistory", "generateExplanation", "retrieveKnowledge"],
  "log irrigation": ["saveIrrigationLog"],
  "update field condition": ["saveFieldObservation"],
  "answer agronomic question": ["retrieveKnowledge"],
  "analyze field note": ["retrieveKnowledge"],
  "verify action": ["verifyRecommendationOutcome"],
  "translate response": ["translateText"],
  "detect missing data": ["calculateConfidence"],
};

export const agentPlanner = {
  plan(goal) {
    const tools = planMap[goal] || ["retrieveKnowledge"];
    return { goal, tools, decisionTrace: { phases: ["Reason", "Act", "Observe", "Decide"], tools } };
  },
};
