import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { demoProfile } from '../js/data/demoData.js';
import { actionMappingFor, alertFingerprint, alertGroup, alertKey, confidencePresentation, confidenceText, dedupeActivityRows, escapeHtml, isAlertDismissed, normalizeDecisionAction, readConfidence, recommendationContextLabel, sortAlerts, weatherAgeLabel } from '../js/services/uiHelpers.js';

const appSource = fs.readFileSync(new URL('../js/app.js', import.meta.url), 'utf8');
const swSource = fs.readFileSync(new URL('../sw.js', import.meta.url), 'utf8');

test('mobile navigation uses five primary destinations with Ask Velia featured', () => {
  assert.ok(appSource.includes('{ id: "today", label: "Today" }'));
  assert.ok(appSource.includes('{ id: "fields", label: "Fields" }'));
  assert.ok(appSource.includes('{ id: "assistant", label: "Ask Velia", featured: true }'));
  assert.ok(appSource.includes('{ id: "alerts", label: "Alerts" }'));
  assert.ok(appSource.includes('{ id: "more", label: "More" }'));
  assert.ok(!appSource.includes('const nav = ["today", "fields", "alerts", "assistant", "reports", "settings"]'));
});

test('confidence display never renders undefined for empty values', () => {
  assert.equal(confidenceText(undefined), 'Moderate');
  assert.equal(confidenceText(null), 'Moderate');
  assert.equal(confidenceText(Number.NaN), 'Moderate');
  assert.equal(confidenceText('undefined'), 'Moderate');
  assert.equal(confidenceText(0.8), 'High');
  assert.equal(confidenceText(0.3), 'Low');
  assert.equal(readConfidence({ confidenceScore: 0.8 }), 0.8);
  assert.equal(readConfidence({ confidenceLabel: 'low' }), 'low');
  assert.equal(readConfidence({ confidence: Number.NaN }), null);
  const display = confidencePresentation(undefined, {});
  assert.equal(display.label, 'Moderate');
  assert.ok(display.explanation);
  assert.ok(display.improve);
});

test('dynamic HTML escaping protects farmer and model text', () => {
  const unsafe = '<img src=x onerror=alert(1)>North Block';
  const escaped = escapeHtml(unsafe);
  assert.ok(!escaped.includes('<img'));
  assert.ok(escaped.includes('&lt;img'));
});

test('realistic Napa demo data showcases multiple blocks and activity', () => {
  assert.equal(demoProfile.farm.name, 'Silverado Vineyard');
  assert.deepEqual(demoProfile.fields.map((field) => field.name), [
    'North Cabernet Block',
    'West Chardonnay Block',
    'South Merlot Block',
    'Orchard Test Plot',
  ]);
  assert.ok(demoProfile.fields.some((field) => field.coordinates));
  assert.ok(demoProfile.fields.some((field) => !field.coordinates));
  assert.ok(demoProfile.irrigationLogs.length >= 2);
  assert.ok(demoProfile.alertHistory.length >= 2);
  assert.ok(demoProfile.recommendationHistory.length >= 2);
  assert.equal(demoProfile.fields[0].demoRecommendation.action, 'check field first');
  assert.ok(demoProfile.fields.every((field) => field.demoRecommendation?.confidence));
});

test('decision actions map to safe primary and secondary CTAs', () => {
  assert.deepEqual(actionMappingFor('irrigate'), { primary: 'Log irrigation', secondary: 'Review reasoning', primaryAction: 'log', secondaryAction: 'reasoning' });
  assert.deepEqual(actionMappingFor('check field first'), { primary: 'Record field check', secondary: 'Ask Velia', primaryAction: 'condition', secondaryAction: 'assistant' });
  assert.deepEqual(actionMappingFor('wait'), { primary: 'Set reminder', secondary: 'View weather risk', primaryAction: 'reminder', secondaryAction: 'weather' });
  assert.deepEqual(actionMappingFor('monitor'), { primary: 'Update field condition', secondary: 'Ask Velia', primaryAction: 'condition', secondaryAction: 'assistant' });
  assert.deepEqual(actionMappingFor('update missing data'), { primary: 'Complete field data', secondary: 'Ask Velia', primaryAction: 'field-detail', secondaryAction: 'assistant' });
});

test('decision action normalization prevents incidental irrigate wording', () => {
  assert.equal(normalizeDecisionAction('irrigate'), 'irrigate');
  assert.equal(normalizeDecisionAction('Check field before irrigating'), 'check field first');
  assert.equal(normalizeDecisionAction('Wait before irrigating'), 'wait');
  assert.equal(normalizeDecisionAction('Monitor irrigation risk'), 'monitor');
});

test('recent activity dedupes duplicate refresh noise and keeps newest first', () => {
  const now = Date.now();
  const rows = dedupeActivityRows([
    { at: new Date(now - 1000).toISOString(), title: 'Recommendation refreshed', body: 'North Cabernet Block - monitor', fieldId: 'a' },
    { at: new Date(now - 10_000).toISOString(), title: 'Recommendation refreshed', body: 'North Cabernet Block - monitor', fieldId: 'a' },
    { at: new Date(now - 20_000).toISOString(), title: 'Recommendation changed', body: 'North Cabernet Block - check field first', fieldId: 'a' },
  ], { limit: 5 });
  assert.equal(rows.length, 2);
  assert.equal(rows[0].title, 'Recommendation refreshed');
  assert.equal(rows[1].title, 'Recommendation changed');
});

test('alerts sort by severity urgency and group into action buckets', () => {
  const alerts = sortAlerts([
    { type: 'sensor', severity: 'low', createdAt: '2026-06-02T08:00:00.000Z' },
    { type: 'stale weather', severity: 'medium', createdAt: '2026-06-02T07:00:00.000Z' },
    { type: 'verification', severity: 'high', createdAt: '2026-06-02T06:00:00.000Z' },
  ]);
  assert.equal(alerts[0].type, 'verification');
  assert.equal(alertGroup(alerts[0]), 'Act now');
  assert.equal(alertGroup(alerts[1]), 'Review today');
  assert.equal(alertGroup(alerts[2]), 'Monitoring');
});

test('generated alert keys remain dismissed until the condition changes', () => {
  const alert = { type: 'heat', fieldId: 'block-a', severity: 'medium', conditionToken: 'heat:elevated', explanation: 'Heat pressure', action: 'Check field' };
  const dismissed = { [alertKey(alert)]: { dismissedAt: new Date().toISOString(), fingerprint: alertFingerprint(alert) } };
  assert.equal(isAlertDismissed(alert, dismissed), true);
  assert.equal(isAlertDismissed({ ...alert, conditionToken: 'heat:high' }, dismissed), false);
});

test('recommendation context labels separate mode from risk', () => {
  assert.equal(recommendationContextLabel({ sourceMode: 'demo' }, {}, 'demo'), 'Demo preview');
  assert.equal(recommendationContextLabel({ sourceMode: 'backend' }, {}, 'real'), 'Synced backend intelligence');
  assert.equal(recommendationContextLabel({ sourceMode: 'local' }, { stale: false }, 'real'), 'Local fallback with fresh cached context');
  assert.equal(recommendationContextLabel({ sourceMode: 'offline' }, { stale: true }, 'real'), 'Stale offline fallback');
});

test('experience source includes safe empty states, provenance, alerts, and loading skeleton', () => {
  assert.ok(appSource.includes('data-testid="provenance-disclosure"'));
  assert.ok(appSource.includes('No urgent alerts'));
  assert.ok(appSource.includes('data-testid="decision-loading"'));
  assert.ok(appSource.includes('Using local intelligence until the backend is reachable.'));
  assert.ok(appSource.includes('Add field location to unlock map-based intelligence.'));
  assert.ok(appSource.includes('prepareRecommendationSnapshot'));
  assert.ok(appSource.includes('scheduleDecisionRefreshes'));
  assert.ok(appSource.includes('alertFirstSeen'));
  assert.ok(appSource.includes('previous.fingerprint !== fingerprint'));
  assert.ok(!appSource.includes('state = recordRecommendationHistory(state, field.id, rec);\\n  persist();\\n  return'));
});

test('service worker caches mobile modules for offline reload', () => {
  assert.ok(swSource.includes('velia-v3-module-offline'));
  assert.ok(swSource.includes('./js/services/weatherService.js'));
  assert.ok(swSource.includes('./js/ai/aiOrchestrator.js'));
  assert.ok(swSource.includes('const isModule'));
  assert.ok(swSource.includes('event.request.mode === "navigate") return caches.match("./index.html")'));
  assert.ok(swSource.includes('caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy))'));
});

test('weather age labels are readable', () => {
  assert.equal(weatherAgeLabel({ freshness: { ageMinutes: 12 } }), '12 min old');
  assert.equal(weatherAgeLabel({ freshness: { ageMinutes: 120 } }), '2 hr old');
  assert.equal(weatherAgeLabel({}), 'Weather age unknown');
});

test('weatherAgeLabel uses live timestamp age instead of frozen freshness.ageMinutes', () => {
  const staleTs = new Date(Date.now() - 90 * 60000).toISOString();
  const age = weatherAgeLabel({ weatherTimestamp: staleTs, freshness: { ageMinutes: 5 } });
  assert.ok(age.includes('hr'), `Expected hours-based age from timestamp, got: ${age}`);
  const match = age.match(/^(\d+) hr old$/);
  assert.ok(match && Number(match[1]) >= 1);
});

test('alert fingerprint is stable for same condition and changes when condition token changes', () => {
  const alert = { type: 'frost', fieldId: 'field-2', severity: 'high', conditionToken: 'frost:elevated', explanation: 'Frost risk', action: 'Confirm protocol' };
  assert.equal(alertFingerprint(alert), alertFingerprint({ ...alert }));
  assert.notEqual(alertFingerprint(alert), alertFingerprint({ ...alert, conditionToken: 'frost:high' }));
});

test('alert firstSeenAt is pinned to first occurrence and reset only on condition change', () => {
  const seen = {};
  const pin = (a) => {
    const k = alertKey(a);
    const fp = alertFingerprint(a);
    if (!seen[k] || seen[k].fingerprint !== fp) seen[k] = { firstSeenAt: a.createdAt || new Date().toISOString(), fingerprint: fp };
    return { ...a, createdAt: seen[k].firstSeenAt };
  };

  const base = { type: 'heat', fieldId: 'field-1', severity: 'medium', conditionToken: 'heat:elevated', explanation: 'Heat pressure', action: 'Check field', createdAt: '2026-06-01T08:00:00.000Z' };
  const first = pin(base);
  assert.equal(first.createdAt, '2026-06-01T08:00:00.000Z');

  const second = pin({ ...base, createdAt: '2026-06-02T10:00:00.000Z' });
  assert.equal(second.createdAt, '2026-06-01T08:00:00.000Z', 'same condition should keep original firstSeenAt');

  const changed = pin({ ...base, conditionToken: 'heat:high', createdAt: '2026-06-02T12:00:00.000Z' });
  assert.equal(changed.createdAt, '2026-06-02T12:00:00.000Z', 'changed condition should get new firstSeenAt');
});

test('alert firstSeenAt defaults to current time when alert has no createdAt', () => {
  const alert = { type: 'sensor', fieldId: 'field-3', severity: 'low', conditionToken: 'sensor:none', explanation: 'No sensor', action: 'Use manual observation' };
  const seen = {};
  const k = alertKey(alert);
  const fp = alertFingerprint(alert);
  const before = Date.now();
  if (!seen[k] || seen[k].fingerprint !== fp) seen[k] = { firstSeenAt: alert.createdAt || new Date().toISOString(), fingerprint: fp };
  const after = Date.now();
  const ts = new Date(seen[k].firstSeenAt).getTime();
  assert.ok(ts >= before && ts <= after);
});
