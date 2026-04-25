import test from 'node:test';
import assert from 'node:assert/strict';
import { applyOnboarding, createInitialState } from '../js/state/store.js';

test('onboarding data creation includes first field', () => {
  const state = applyOnboarding(createInitialState(), {
    role:'farmer', farmName:'My Farm', farmLocation:'Dakar', fieldName:'Field A', crop:'Maize', acreage:'10', irrigationMethod:'Drip', soilType:'Loam', units:'metric', language:'en', hardware:'manual'
  });
  assert.equal(state.onboarded, true);
  assert.equal(state.fields.length, 1);
  assert.equal(state.fields[0].crop, 'Maize');
});
