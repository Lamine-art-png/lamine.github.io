import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const voice = fs.readFileSync(path.join(root, "src/app/components/voice/VoiceAssistantDock.tsx"), "utf8");
const intelligence = fs.readFileSync(path.join(root, "src/app/components/Intelligence.tsx"), "utf8");
const intelligenceView = fs.readFileSync(path.join(root, "src/app/components/intelligence/IntelligenceView.tsx"), "utf8");
const dictation = fs.readFileSync(path.join(root, "src/app/components/voice/VoiceDictationButton.tsx"), "utf8");
const uploadToast = fs.readFileSync(path.join(root, "src/app/components/UploadStatusToast.tsx"), "utf8");
const controller = fs.readFileSync(path.join(root, "src/app/components/intelligence/useIntelligenceController.ts"), "utf8");
const field = fs.readFileSync(path.join(root, "src/app/components/FieldIntelligenceV2.tsx"), "utf8");
const apiClient = fs.readFileSync(path.join(root, "src/app/api/client.ts"), "utf8");

assert.match(voice, /new RTCPeerConnection\(\)/);
assert.match(voice, /createDataChannel\("oai-events"\)/);
assert.match(voice, /\/v1\/voice\/realtime-call/);
assert.match(voice, /conversation\.item\.input_audio_transcription\.completed/);
assert.match(voice, /response\.function_call_arguments\.done/);
assert.match(voice, /execute_aep_action/);
assert.match(voice, /Confirm AEP action/);
assert.match(voice, /cancelled_by_user/);
assert.match(voice, /echoCancellation: true/);
assert.match(voice, /noiseSuppression: true/);
assert.match(voice, /autoGainControl: true/);
assert.match(voice, /option value="wo">Wolof/);
assert.match(voice, /option value="deep">Deep/);
assert.match(voice, /\/v1\/voice\/health/);
assert.match(voice, /transport.*fallback/);
assert.match(voice, /\/v1\/voice\/transcribe/);
assert.match(voice, /speechSynthesis/);
assert.match(voice, /agroai:voice-open/);
assert.match(voice, /resolvedVoiceLanguage/);
assert.match(voice, /response_language/);
assert.match(apiClient, /\/v1\\\/runtime\\\/intelligence-run/);
assert.match(intelligence, /preferred_language: responseLanguage/);
assert.match(intelligence, /requested && requested !== "en"/);

assert.match(dictation, /MediaRecorder/);
assert.match(dictation, /\/v1\/voice\/transcribe/);
assert.match(dictation, /onTranscript/);
assert.match(intelligenceView, /<VoiceDictationButton/);
assert.match(intelligenceView, /Start live voice conversation/);
assert.match(intelligenceView, /openAgroAiVoice\("ask"\)/);

assert.match(intelligence, /<VoiceAssistantDock/);
assert.match(intelligence, /surface="ask"/);
assert.match(intelligence, /await controller\.ingestVoiceExchange\(userText, assistantText\)/);

assert.match(uploadToast, /location\.pathname === "\/field-intelligence"/);
assert.match(uploadToast, /<VoiceAssistantDock surface="field"/);

assert.match(voice, /get_field_context/);
assert.match(voice, /update_field_draft/);
assert.match(voice, /capture_field_location/);
assert.match(voice, /save_field_observation/);
assert.match(voice, /create_field_task/);
assert.match(voice, /agroai:field-agent-action/);
assert.match(voice, /agroai:field-context/);
assert.match(field, /agroai:field-context/);
assert.match(field, /agroai:field-context-request/);
assert.match(field, /agroai:field-agent-action/);
assert.match(field, /detail\.type === "update_draft"/);
assert.match(field, /detail\.type === "capture_location"/);
assert.match(field, /detail\.type === "save_observation"/);
assert.match(field, /await queueCapture\(\)/);
assert.match(field, /selected_observation/);

console.log("AEP realtime voice contract OK");

assert.match(controller, /action\?\.auto_execute/);
assert.match(controller, /approval_confirmed: false/);
assert.match(controller, /agroai:workspace-agent-change/);
assert.match(intelligenceView, /generatedArtifact\?\.download_url/);
assert.match(intelligenceView, /downloadGeneratedArtifact/);
assert.match(voice, /tool\.arguments\.approval_required === true/);
assert.match(voice, /approval_confirmed: true/);

assert.match(voice, /generatedArtifacts/);
assert.match(voice, /downloadVoiceArtifact/);
assert.match(voice, /voiceDrafts/);
assert.match(voice, /name: "plan_aep_action"/);
assert.match(voice, /action\?\.auto_execute/);
assert.match(voice, /captureActionOutput/);
