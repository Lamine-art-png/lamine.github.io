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

test('manual onboarding persists farm and field values across app state', () => {
  const state = applyOnboarding(createInitialState(), {
    role: 'farmer',
    farmName: 'Silverado Vineyard',
    farmLocation: 'Napa',
    coordinates: { lat: 38.5, lon: -122.4 },
    fieldName: 'North Block',
    fieldLocation: 'North bench',
    crop: 'Grapes',
    acreage: '10',
    irrigationMethod: 'Drip',
    soilType: 'Loam',
    units: 'imperial',
    language: 'en',
    hardware: 'manual',
    dataSource: 'neither',
    lastIrrigationAt: '2026-06-01',
    waterSource: 'Well',
    usualDurationMin: '55',
  });
  const field = state.fields[0];
  assert.equal(state.profile.farm.name, 'Silverado Vineyard');
  assert.equal(state.profile.farm.location, 'Napa');
  assert.deepEqual(state.profile.farm.coordinates, { lat: 38.5, lon: -122.4 });
  assert.equal(field.name, 'North Block');
  assert.equal(field.location, 'North bench');
  assert.equal(field.crop, 'Grapes');
  assert.equal(field.acreage, 10);
  assert.equal(state.units, 'imperial');
  assert.equal(field.units, 'imperial');
  assert.equal(field.irrigationMethod, 'Drip');
  assert.equal(field.soilType, 'Loam');
  assert.equal(field.lastIrrigationAt, '2026-06-01');
  assert.equal(field.waterSource, 'Well');
  assert.equal(field.dataSource, 'neither');
  assert.equal(field.dataSourceMode, 'neither');
});

test('recommendation history storage deduplicates recent same urgency', () => {
  const init = { ...createInitialState(), recommendationHistory: [] };
  const s1 = recordRecommendationHistory(init, 'f1', { urgency: 'medium' });
  const s2 = recordRecommendationHistory(s1, 'f1', { urgency: 'medium' });
  assert.equal(s1.recommendationHistory.length, 1);
  assert.equal(s2.recommendationHistory.length, 1);
});

test('recommendation history distinguishes changed recommendations', () => {
  const init = { ...createInitialState(), recommendationHistory: [] };
  const s1 = recordRecommendationHistory(init, 'f1', { urgency: 'medium', action: 'monitor' });
  const s2 = recordRecommendationHistory(s1, 'f1', { urgency: 'medium', action: 'check field first' });
  assert.equal(s2.recommendationHistory.length, 2);
  assert.equal(s2.recommendationHistory[0].eventType, 'recommendation changed');
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
