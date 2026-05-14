import test from 'node:test';
import assert from 'node:assert/strict';
import { weatherService } from '../js/services/weatherService.js';

global.localStorage = {
  _m:new Map(),
  getItem(k){return this._m.has(k)?this._m.get(k):null;},
  setItem(k,v){this._m.set(k,v);},
};
Object.defineProperty(global, 'navigator', { value: { onLine: true }, configurable: true });

test('weather service mock output shape', async () => {
  const weather = await weatherService.getWeather({ location:'Dakar', forceRefresh:true });
  assert.ok(typeof weather.temperature === 'number');
  assert.ok('rainChance' in weather);
  assert.ok('evapotranspiration' in weather);
  assert.ok(weather.lastUpdated);
});

test('weather provider adapter structure is exposed', () => {
  const providers = weatherService.listProviders();
  assert.ok(providers.includes('mock'));
});

test('offline cached weather behavior', async () => {
  await weatherService.getWeather({ location:'Dakar', forceRefresh:true });
  Object.defineProperty(global, 'navigator', { value: { onLine: false }, configurable: true });
  const weather = await weatherService.getWeather({ location:'Dakar', forceRefresh:false });
  assert.equal(weather.stale, true);
  assert.equal(weather.cached, true);
});
