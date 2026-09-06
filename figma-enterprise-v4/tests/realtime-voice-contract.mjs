import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const repoRoot = path.resolve(root, "..");

function read(relative) {
  return fs.readFileSync(path.join(root, relative), "utf8");
}

const client = read("src/app/voice/realtimeVoiceClient.ts");
const panel = read("src/app/voice/VoiceCallPanel.tsx");
const intelligence = read("src/app/components/intelligence/IntelligenceView.tsx");
const controller = read("src/app/components/intelligence/useIntelligenceController.ts");
const field = read("src/app/components/FieldIntelligenceV2.tsx");
const backend = fs.readFileSync(path.join(repoRoot, "agroai_api/app/api/v1/voice.py"), "utf8");
const main = fs.readFileSync(path.join(repoRoot, "agroai_api/app/main.py"), "utf8");

assert.match(client, /RTCPeerConnection/);
assert.match(client, /mediaDevices\.getUserMedia/);
assert.match(client, /\/v1\/voice\/realtime\/call/);
assert.match(client, /conversation\.item\.input_audio_transcription\.completed/);
assert.match(client, /response\.output_audio_transcript\.delta/);
assert.match(client, /response\.output_item\.done/);
assert.match(client, /function_call_output/);
assert.match(client, /plan_aep_action/);
assert.match(client, /execute_aep_action/);
assert.doesNotMatch(client, /OPENAI_API_KEY/);
assert.doesNotMatch(panel, /OPENAI_API_KEY/);

assert.match(intelligence, /VoiceCallPanel/);
assert.match(intelligence, /surface="ask_agro_ai"/);
assert.match(controller, /commitVoiceExchange/);
assert.match(controller, /source: "realtime_voice"/);

assert.match(field, /VoiceCallPanel/);
assert.match(field, /surface="field_intelligence"/);
assert.match(field, /SmartComposer/);
assert.match(field, /offlineQueue/);

assert.match(backend, /semantic_vad/);
assert.match(backend, /interrupt_response/);
assert.match(backend, /gpt-realtime-2\.1/);
assert.match(backend, /gpt-live-transcribe/);
assert.match(backend, /approval_confirmed": False/);
assert.match(backend, /approval_bypass_disabled/);
assert.match(backend, /workspace_id/);
assert.match(main, /voice_router/);

console.log("Realtime voice contract: OK");
