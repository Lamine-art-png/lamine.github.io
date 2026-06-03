import test from 'node:test';
import assert from 'node:assert/strict';
import { createAiOrchestrator } from '../js/ai/aiOrchestrator.js';
import { memoryStore } from '../js/ai/memoryStore.js';

function context(preview = false) {
  const field = { id: 'preview-field', name: 'Preview Field', crop: 'Grapes', waterStressLevel: 'moderate', soilType: 'Loam', lastIrrigationAt: new Date().toISOString(), dataSource: 'neither' };
  return {
    getFarmProfile: () => ({ name: 'Farm' }),
    getFieldProfile: () => field,
    getWeather: () => ({ rainChance: 10, heatRisk: 'low', frostRisk: 'low', forecastSummary: 'Clear' }),
    getIrrigationLogs: () => [],
    getFieldObservations: () => [],
    getRecommendationHistory: () => [],
    saveIrrigationLog: () => ({ ok: true }),
    saveFieldObservation: () => ({ ok: true }),
    saveVoiceNote: () => ({ ok: true }),
    calculateWaterBalance: () => ({ waterBalanceScore: 0.5 }),
    estimateIrrigationNeed: () => ({ needScore: 0.4 }),
    calculateConfidence: () => 0.8,
    generateExplanation: () => 'Explanation',
    isPreviewRender: () => preview,
  };
}

test('preview recommendations do not write local memory decisions', () => {
  const before = memoryStore.getFieldMemory('preview-field').recommendationHistory.length;
  createAiOrchestrator(context(true)).runGoal({ goal: 'daily irrigation decision', fieldId: 'preview-field' });
  createAiOrchestrator(context(true)).runGoal({ goal: 'daily irrigation decision', fieldId: 'preview-field' });
  const after = memoryStore.getFieldMemory('preview-field').recommendationHistory.length;
  assert.equal(after, before);
});

test('intentional non-preview decisions are capped and deduped', () => {
  for (let i = 0; i < 55; i += 1) {
    createAiOrchestrator(context(false)).runGoal({ goal: 'daily irrigation decision', fieldId: 'intentional-field' });
  }
  const memory = memoryStore.getFieldMemory('intentional-field');
  assert.equal(memory.recommendationHistory.length, 1);
  assert.ok(memory.events.length <= 100);
});
