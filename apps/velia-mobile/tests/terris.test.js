import test from "node:test";
import assert from "node:assert/strict";
import { storage } from "../js/services/storage.js";
import { createTerrisFieldEvent, fieldObservationEvent, waterAppliedEvent, waterRecommendationEvent } from "../js/domain/fieldLedger.js";
import { terrisModuleRegistry, TERRIS_FEATURE_FLAGS } from "../js/domain/moduleRegistry.js";
import { createNutrientRecord, nutrientLedgerEvent, plannedAppliedVariance } from "../js/domain/nutrients.js";
import { compareEligibleWindows, pumpingRuntimeEvent } from "../js/domain/energy.js";
import { completeFieldTask, createFieldTask, taskEvent } from "../js/domain/ops.js";
import { createEvidencePacket, TERRIS_PROOF_DISCLAIMER } from "../js/domain/proof.js";
import { createAttachmentMetadata, createIrrigationLog, createObservation, createVoiceTimelineEntry } from "../js/state/actions.js";

global.localStorage = {
  _m: new Map(),
  getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
  setItem(k, v) { this._m.set(k, v); },
};

test("storage reads Terris key first and migrates legacy Velia key", () => {
  localStorage._m.clear();
  localStorage.setItem("velia-mobile:state", JSON.stringify({ onboarded: true }));
  assert.deepEqual(storage.get("state", {}), { onboarded: true });
  assert.equal(localStorage.getItem("terris-mobile:state"), JSON.stringify({ onboarded: true }));
  storage.set("state", { onboarded: false });
  assert.deepEqual(storage.get("state", {}), { onboarded: false });
});

test("module registry exposes canonical statuses and feature flags", () => {
  const water = terrisModuleRegistry.find((module) => module.key === "water");
  const protect = terrisModuleRegistry.find((module) => module.key === "protect");
  const risk = terrisModuleRegistry.find((module) => module.key === "risk_api");
  assert.equal(water.status, "active");
  assert.equal(water.enabled, true);
  assert.equal(protect.status, "preview");
  assert.equal(TERRIS_FEATURE_FLAGS.TERRIS_PROTECT_ENABLED, false);
  assert.equal(risk.status, "reserved");
});

test("water recommendation, applied water, and observation create separate ledger states", () => {
  const field = { id: "f1" };
  const recommendation = waterRecommendationEvent({ field, recommendation: { action: "check field", urgency: "medium", timing: "today", reasons: ["dry"], missingData: [] }, weather: { source: "mock" } });
  const applied = waterAppliedEvent(createIrrigationLog({ fieldId: "f1", durationMin: 60, amountMm: 12, source: "manual" }));
  const observed = fieldObservationEvent(createObservation({ fieldId: "f1", condition: "Looks dry" }));
  assert.equal(recommendation.eventType, "irrigation_recommendation");
  assert.equal(applied.eventType, "irrigation_applied");
  assert.equal(observed.eventType, "field_observation");
  assert.notEqual(applied.eventType, "irrigation_verified");
});

test("nutrients beta withholds calculated amount when water volume or concentration is missing", () => {
  const missingVolume = createNutrientRecord({ fieldId: "f1", nutrientType: "N", concentration: 2, unit: "kg", applicationMethod: "fertigation" });
  assert.equal(missingVolume.appliedQuantity, null);
  assert.deepEqual(missingVolume.missingData, ["water volume"]);
  const complete = createNutrientRecord({ fieldId: "f1", nutrientType: "N", waterVolume: 10, concentration: 2, plannedQuantity: 25, unit: "kg", applicationMethod: "fertigation" });
  assert.equal(complete.appliedQuantity, 20);
  assert.equal(complete.truthLabel, "calculated");
  assert.equal(plannedAppliedVariance(complete), -5);
  assert.equal(nutrientLedgerEvent(complete).eventType, "fertigation_applied");
});

test("energy beta filters unsafe cheaper execution windows and labels estimates", () => {
  const result = compareEligibleWindows({
    recommendation: { timing: "today" },
    tariff: { energyRate: 1 },
    windows: [
      { label: "safe", estimatedKwh: 10, energyRate: 1, allowedByWaterDecision: true },
      { label: "unsafe cheap", estimatedKwh: 10, energyRate: 0.1, allowedByWaterDecision: false },
    ],
  });
  assert.equal(result.bestWindow.label, "safe");
  assert.equal(result.windows.length, 1);
  assert.equal(pumpingRuntimeEvent({ fieldId: "f1", estimatedCost: 12 }).truthLabel, "estimated");
});

test("ops task completion does not equal agronomic verification", () => {
  const task = createFieldTask({ title: "Verify application", module: "water", taskType: "verify_application", fieldId: "f1" });
  const completed = completeFieldTask(task, { notes: "Checked row end", offline: true });
  const event = taskEvent(completed, true);
  assert.equal(completed.offlineSyncState, "queued");
  assert.equal(event.eventType, "task_completed");
  assert.ok(event.limitations[0].includes("not agronomic verification"));
});

test("proof packet preserves truth labels and disclaimer", () => {
  const packet = createEvidencePacket({
    title: "Water packet",
    events: [createTerrisFieldEvent({ eventType: "irrigation_applied", module: "water", fieldId: "f1", truthLabel: "reported" })],
    artifacts: [],
    assumptions: ["manual report"],
    missingInputs: ["controller confirmation"],
  });
  assert.deepEqual(packet.truthLabelSummary, ["reported"]);
  assert.equal(packet.disclaimer, TERRIS_PROOF_DISCLAIMER);
  assert.ok(!/official regulatory filing support/i.test(packet.disclaimer));
});

test("offline voice, photo metadata, translation, and field association remain explicit", () => {
  const photo = createAttachmentMetadata({ fieldId: "f1", type: "photo", uri: "local://photo.jpg", geotag: { lat: 1, lon: 2 } });
  const voice = createVoiceTimelineEntry({ fieldId: "f1", transcript: "Looks dry", intent: "UPDATE_CONDITION", outcome: "queued", attachmentRefs: [photo.id], translation: { display: "Se ve seco", locale: "es" } });
  assert.equal(photo.syncStatus, "queued");
  assert.equal(voice.fieldId, "f1");
  assert.equal(voice.translation.display, "Se ve seco");
  assert.equal(voice.transcript, "Looks dry");
});
