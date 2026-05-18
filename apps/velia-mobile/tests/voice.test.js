import test from 'node:test';
import assert from 'node:assert/strict';
import { detectIntent, parseVoiceCommand } from '../js/services/voiceAgent.js';

test('voice command logging irrigation', () => {
  const cmd = parseVoiceCommand('Log irrigation for Field 1 for 2 hours', { fieldId:'f1' });
  assert.equal(detectIntent('Log irrigation for Field 1 for 2 hours'), 'LOG_IRRIGATION');
  assert.equal(cmd.action.type, 'log_irrigation');
  assert.equal(cmd.action.payload.durationMin, 120);
});

test('voice command adding field condition', () => {
  const cmd = parseVoiceCommand('Field 1 looks dry', { fieldId:'f1' });
  assert.equal(cmd.intent, 'UPDATE_CONDITION');
  assert.equal(cmd.action.payload.condition, 'Looks dry');
});
