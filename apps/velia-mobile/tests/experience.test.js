import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { demoProfile } from '../js/data/demoData.js';
import { confidenceText, escapeHtml, weatherAgeLabel } from '../js/services/uiHelpers.js';

const appSource = fs.readFileSync(new URL('../js/app.js', import.meta.url), 'utf8');

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
  assert.equal(confidenceText(0.8), 'High');
  assert.equal(confidenceText(0.3), 'Low');
});

test('dynamic HTML escaping protects farmer and model text', () => {
  const unsafe = '<img src=x onerror=alert(1)>North Block';
  const escaped = escapeHtml(unsafe);
  assert.ok(!escaped.includes('<img'));
  assert.ok(escaped.includes('&lt;img'));
});

test('realistic Napa demo data showcases multiple blocks and activity', () => {
  assert.equal(demoProfile.farm.name, 'Silverado Vineyard');
  assert.ok(demoProfile.fields.length >= 3);
  assert.ok(demoProfile.fields.some((field) => field.coordinates));
  assert.ok(demoProfile.fields.some((field) => !field.coordinates));
  assert.ok(demoProfile.irrigationLogs.length >= 2);
  assert.ok(demoProfile.alertHistory.length >= 2);
  assert.ok(demoProfile.recommendationHistory.length >= 2);
});

test('experience source includes safe empty states, provenance, alerts, and loading skeleton', () => {
  assert.ok(appSource.includes('data-testid="provenance-disclosure"'));
  assert.ok(appSource.includes('No urgent alerts'));
  assert.ok(appSource.includes('data-testid="decision-loading"'));
  assert.ok(appSource.includes('Using local intelligence until the backend is reachable.'));
  assert.ok(appSource.includes('Add field location to unlock map-based intelligence.'));
});

test('weather age labels are readable', () => {
  assert.equal(weatherAgeLabel({ freshness: { ageMinutes: 12 } }), '12 min old');
  assert.equal(weatherAgeLabel({ freshness: { ageMinutes: 120 } }), '2 hr old');
  assert.equal(weatherAgeLabel({}), 'Weather age unknown');
});
