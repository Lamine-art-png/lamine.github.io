const GOAL_MAP = {
  "daily irrigation decision": ["getFieldProfile", "getWeather", "getIrrigationLogs", "getFieldObservations", "retrieveKnowledge", "estimateIrrigationNeed", "calculateConfidence"],
  "explain recommendation": ["getRecommendationHistory", "retrieveKnowledge", "generateExplanation"],
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
    const tools = GOAL_MAP[goal] || ["retrieveKnowledge"];
    return {
      goal,
      steps: [
        { phase: "Reason", note: `Assess goal: ${goal}` },
        { phase: "Act", tools },
        { phase: "Observe", note: "Review tool outputs and data quality" },
        { phase: "Decide", note: "Generate grounded decision and trace" },
      ],
      tools,
    };
  },
};
