import test from 'node:test';
import assert from 'node:assert/strict';
import { createAiOrchestrator } from '../js/ai/aiOrchestrator.js';
import { traverseKnowledgeGraph } from '../js/ai/knowledgeBase.js';
import { runEvaluationHarness } from '../js/ai/evaluationHarness.js';

const context = {
  getFarmProfile: () => ({ name: 'Farm A' }),
  getFieldProfile: () => ({ id: 'f1', name: 'Field 1', crop: 'Maize', dataSource: 'neither', waterStressLevel: 'high', soilType: '', lastObservation: 'Looks dry' }),
  getWeather: () => ({ forecastSummary: 'Hot and dry', heatRisk: 'elevated', frostRisk: 'low', rainChance: 8, stale: false }),
  getIrrigationLogs: () => [],
  getFieldObservations: () => [{ condition: 'Looks dry' }],
  getRecommendationHistory: () => [],
  saveIrrigationLog: () => ({ ok: true }),
  saveFieldObservation: () => ({ ok: true }),
  saveVoiceNote: () => ({ ok: true }),
  calculateWaterBalance: () => ({ waterBalanceScore: 0.8 }),
  estimateIrrigationNeed: () => ({ needScore: 0.82 }),
  calculateConfidence: ({ missingData }) => 0.72 - (missingData.length * 0.05),
  generateExplanation: () => 'Explanation',
};

test('ai orchestrator returns structured decision', () => {
  const ai = createAiOrchestrator(context);
  const out = ai.runGoal({ goal: 'daily irrigation decision', fieldId: 'f1', language: 'en' });
  assert.equal(out.type, 'decision');
  assert.equal(out.decision.fieldId, 'f1');
  assert.ok(out.decision.action);
  assert.ok(Array.isArray(out.decision.decisionTrace.toolsUsed));
  assert.ok(out.decision.disclaimer);
});

test('knowledge graph traversal returns relationships', () => {
  const edges = traverseKnowledgeGraph('weather_risk');
  assert.ok(edges.length > 0);
});

test('evaluation harness validates baseline checks', () => {
  const rows = runEvaluationHarness(() => ({ action: 'monitor', confidenceScore: 0.6, missingData: [], reasons: ['ok'], disclaimer: 'x' }));
  assert.ok(rows.every((r) => r.passed));
});
