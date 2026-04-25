import test from 'node:test';
import assert from 'node:assert/strict';
import { createField, createIrrigationLog, createObservation } from '../js/state/actions.js';

test('field creation', () => {
  const field = createField({ fieldName:'North Block', crop:'Rice', acreage:'20', irrigationMethod:'Flood', soilType:'Clay', dataSource:'sensors' });
  assert.equal(field.name, 'North Block');
  assert.equal(field.acreage, 20);
});

test('irrigation log creation', () => {
  const log = createIrrigationLog({ fieldId:'f1', durationMin:60, amountMm:15, source:'manual' });
  assert.equal(log.fieldId, 'f1');
  assert.equal(log.durationMin, 60);
});

test('field condition observation', () => {
  const obs = createObservation({ fieldId:'f1', condition:'Looks dry' });
  assert.equal(obs.condition, 'Looks dry');
});
