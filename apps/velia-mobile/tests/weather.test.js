import test from 'node:test';
import assert from 'node:assert/strict';
import { apiClient } from '../js/services/apiClient.js';
import { weatherService, WEATHER_CACHE_TTL_MS } from '../js/services/weatherService.js';

global.localStorage = {
  _m:new Map(),
  getItem(k){return this._m.has(k)?this._m.get(k):null;},
  setItem(k,v){this._m.set(k,v);},
};
Object.defineProperty(global, 'navigator', { value: { onLine: true }, configurable: true });

function resetWeather() {
  global.localStorage._m.clear();
  Object.defineProperty(global, 'navigator', { value: { onLine: true }, configurable: true });
  apiClient.getWeatherContext = async () => ({
    temperature: 72,
    rainChance: 12,
    heatRisk: 'low',
    forecastSummary: 'Backend weather',
    weatherTimestamp: new Date().toISOString(),
    freshness: { ageMinutes: 0 },
    stale: false,
    fallbackStatus: 'live',
  });
}

test('weather service mock output shape', async () => {
  resetWeather();
  Object.defineProperty(global, 'navigator', { value: { onLine: false }, configurable: true });
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
  resetWeather();
  await weatherService.getWeather({ location:'Dakar', forceRefresh:true });
  Object.defineProperty(global, 'navigator', { value: { onLine: false }, configurable: true });
  const weather = await weatherService.getWeather({ location:'Dakar', forceRefresh:false });
  assert.equal(weather.stale, true);
  assert.equal(weather.cached, true);
});

test('weather service returns fresh cache within TTL', async () => {
  resetWeather();
  let calls = 0;
  apiClient.getWeatherContext = async () => {
    calls += 1;
    return { temperature: 70, rainChance: 5, forecastSummary: 'Fresh', weatherTimestamp: new Date().toISOString(), stale: false, freshness: { ageMinutes: 0 } };
  };
  await weatherService.getWeather({ location:'Napa', forceRefresh:true });
  const cached = await weatherService.getWeather({ location:'Napa' });
  assert.equal(calls, 1);
  assert.equal(cached.cached, true);
  assert.equal(cached.stale, false);
});

test('weather service refreshes expired cache', async () => {
  resetWeather();
  let calls = 0;
  const old = new Date(Date.now() - WEATHER_CACHE_TTL_MS - 60000).toISOString();
  global.localStorage.setItem('velia-mobile:weather_cache', JSON.stringify({ temperature: 60, rainChance: 50, forecastSummary: 'Old', weatherTimestamp: old, cachedAt: old, stale: false }));
  apiClient.getWeatherContext = async () => {
    calls += 1;
    return { temperature: 75, rainChance: 8, forecastSummary: 'Refreshed', weatherTimestamp: new Date().toISOString(), stale: false, freshness: { ageMinutes: 0 } };
  };
  const weather = await weatherService.getWeather({ location:'Napa' });
  assert.equal(calls, 1);
  assert.equal(weather.cached, false);
  assert.equal(weather.temperature, 75);
});

test('weather service preserves stale backend metadata', async () => {
  resetWeather();
  apiClient.getWeatherContext = async () => ({
    temperature: 65,
    rainChance: 30,
    forecastSummary: 'Backend stale',
    weatherTimestamp: '2026-06-02T10:00:00.000Z',
    freshness: { ageMinutes: 180, source: 'backend' },
    stale: true,
    fallbackStatus: 'stale provider cache',
  });
  const weather = await weatherService.getWeather({ location:'Napa', forceRefresh:true });
  assert.equal(weather.stale, true);
  assert.equal(weather.fallbackStatus, 'stale provider cache');
  assert.ok(weather.freshness.ageMinutes > 180);
  assert.equal(weather.freshness.source, 'backend');
  assert.equal(weather.weatherTimestamp, '2026-06-02T10:00:00.000Z');
});

test('offline cached response is honest about staleness and age', async () => {
  resetWeather();
  const old = new Date(Date.now() - 90 * 60000).toISOString();
  global.localStorage.setItem('velia-mobile:weather_cache', JSON.stringify({ temperature: 64, rainChance: 20, forecastSummary: 'Cached', weatherTimestamp: old, cachedAt: old, stale: false }));
  Object.defineProperty(global, 'navigator', { value: { onLine: false }, configurable: true });
  const weather = await weatherService.getWeather({ location:'Napa' });
  assert.equal(weather.cached, true);
  assert.equal(weather.stale, true);
  assert.equal(weather.fallbackStatus, 'offline cached weather');
  assert.ok(weather.freshness.ageMinutes >= 89);
});

test('cached weather age is recomputed instead of frozen', async () => {
  resetWeather();
  const old = new Date(Date.now() - 65 * 60000).toISOString();
  global.localStorage.setItem('velia-mobile:weather_cache', JSON.stringify({
    temperature: 64,
    forecastSummary: 'Cached',
    weatherTimestamp: old,
    cachedAt: old,
    freshness: { ageMinutes: 1, source: 'backend' },
    stale: false,
  }));
  Object.defineProperty(global, 'navigator', { value: { onLine: false }, configurable: true });
  const weather = await weatherService.getWeather({ location:'Napa' });
  assert.ok(weather.freshness.ageMinutes >= 64);
  assert.equal(weather.freshness.source, 'backend');
});

test('force refresh prefers stale real cache over mock after backend failure', async () => {
  resetWeather();
  const old = new Date(Date.now() - 45 * 60000).toISOString();
  global.localStorage.setItem('velia-mobile:weather_cache', JSON.stringify({
    temperature: 62,
    rainChance: 40,
    forecastSummary: 'Real cached provider weather',
    weatherTimestamp: old,
    cachedAt: old,
    fallbackStatus: 'live',
    stale: false,
  }));
  apiClient.getWeatherContext = async () => { throw new Error('backend unavailable'); };
  const weather = await weatherService.getWeather({ location:'Napa', forceRefresh:true });
  assert.equal(weather.temperature, 62);
  assert.equal(weather.cached, true);
  assert.equal(weather.stale, true);
  assert.equal(weather.weatherTimestamp, old);
  assert.ok(weather.freshness.ageMinutes >= 44);
  assert.match(weather.fallbackStatus, /stale cached weather: backend unavailable/);
});
