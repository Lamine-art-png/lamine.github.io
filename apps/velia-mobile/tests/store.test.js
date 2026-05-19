import test from 'node:test';
import assert from 'node:assert/strict';
import { applyDemoScenario, applyOnboarding, createInitialState, recordRecommendationHistory } from '../js/state/store.js';

test('onboarding data creation includes first field', () => {
  const state = applyOnboarding(createInitialState(), {
    role:'farmer', farmName:'My Farm', farmLocation:'Dakar', fieldName:'Field A', fieldLocation:'North block', crop:'Maize', acreage:'10', irrigationMethod:'Drip', soilType:'Loam', units:'metric', language:'en', hardware:'manual'
  });
  assert.equal(state.onboarded, true);
  assert.equal(state.fields.length, 1);
  assert.equal(state.fields[0].crop, 'Maize');
  assert.equal(state.fields[0].location, 'North block');
});

test('recommendation history storage deduplicates recent same urgency', () => {
  const init = { ...createInitialState(), recommendationHistory: [] };
  const s1 = recordRecommendationHistory(init, 'f1', { urgency: 'medium' });
  const s2 = recordRecommendationHistory(s1, 'f1', { urgency: 'medium' });
  assert.equal(s1.recommendationHistory.length, 1);
  assert.equal(s2.recommendationHistory.length, 1);
});

test('demo scenario switching updates field stress', () => {
  const base = {
    ...createInitialState(),
    mode: 'demo',
    fields: [{ id: 'f1', name: 'Field 1', waterStressLevel: 'moderate', lastObservation: 'Looks normal' }],
    weatherCache: { heatRisk: 'low', forecastSummary: 'Stable' },
  };
  const next = applyDemoScenario(base, 'hotDry');
  assert.equal(next.fields[0].waterStressLevel, 'high');
  assert.equal(next.demoScenario, 'hotDry');
});
