import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { storage } from "../js/services/storage.js";
import { syncService } from "../js/services/sync.js";
import { applyVoiceAction, parseVoiceCommand } from "../js/services/voiceAgent.js";
import { createTerrisFieldEvent, appendLedgerEvent, appendRecommendationEventIfNew, fieldObservationEvent, recommendationFingerprint, safeRandomUuid, waterAppliedEvent, waterRecommendationEvent } from "../js/domain/fieldLedger.js";
import { terrisModuleRegistryForMode, TERRIS_FEATURE_FLAGS } from "../js/domain/moduleRegistry.js";
import { createNutrientRecord, nutrientLedgerEvent, plannedAppliedVariance } from "../js/domain/nutrients.js";
import { compareEligibleWindows, pumpingRuntimeEvent } from "../js/domain/energy.js";
import { completeFieldTask, createFieldTask, taskEvent } from "../js/domain/ops.js";
import { createEvidencePacket, evidencePacketEvent, evidenceReviewSignature, filterEvidenceEvents, TERRIS_PROOF_DISCLAIMER } from "../js/domain/proof.js";
import { createInitialState, hydrateState } from "../js/state/store.js";
import { createAttachmentMetadata, createIrrigationLog, createObservation, createVoiceTimelineEntry } from "../js/state/actions.js";

global.localStorage = {
  _m: new Map(),
  getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
  setItem(k, v) { this._m.set(k, v); },
  removeItem(k) { this._m.delete(k); },
};

test("storage reads Terris key first and migrates legacy Velia key", () => {
  localStorage._m.clear();
  localStorage.setItem("velia-mobile:state", JSON.stringify({ onboarded: true }));
  assert.deepEqual(storage.get("state", {}), { onboarded: true });
  assert.equal(localStorage.getItem("terris-mobile:state"), JSON.stringify({ onboarded: true }));
  storage.set("state", { onboarded: false });
  assert.deepEqual(storage.get("state", {}), { onboarded: false });
});

test("hydrateState gives older persisted users every Terris array without deleting main keys", () => {
  const hydrated = hydrateState({
    onboarded: true,
    dismissedAlerts: { a: true },
    alertFirstSeen: { b: { firstSeenAt: "2026-06-01T00:00:00.000Z" } },
    recommendationHistory: [{ fieldId: "f1" }],
    alertHistory: [{ id: "alert-1" }],
    voiceTimeline: [{ id: "voice-1" }],
    remoteDecisions: { f1: { decision: {} } },
    weatherCache: { forecastSummary: "Cached" },
    fields: [{ id: "f1", waterSource: "Well", dataSourceMode: "neither", verificationStatus: "due today" }],
  });
  for (const key of ["nutrientRecords", "pumpRuntimeEvents", "fieldTasks", "evidenceArtifacts", "evidencePackets", "fieldLedgerEvents"]) {
    assert.deepEqual(hydrated[key], []);
  }
  assert.equal(hydrated.fields[0].waterSource, "Well");
  assert.equal(hydrated.fields[0].dataSourceMode, "neither");
  assert.equal(hydrated.fields[0].verificationStatus, "due today");
  assert.equal(hydrated.ledgerMetadata.persistenceMode, "local_mobile_buffer");
  assert.equal(hydrated.ledgerMetadata.durableBackendPersistence, false);
});

test("field ledger validates truth labels, modules, event types, source modes, and data quality", () => {
  assert.equal(createTerrisFieldEvent({ eventType: "irrigation_applied", module: "water", fieldId: "f1", truthLabel: "measured", sourceMode: "controller", dataQuality: "high" }).truthLabel, "measured");
  assert.throws(() => createTerrisFieldEvent({ eventType: "irrigation_applied", module: "bad", fieldId: "f1" }), /Unsupported Terris module/);
  assert.throws(() => createTerrisFieldEvent({ eventType: "bad", module: "water", fieldId: "f1" }), /Unsupported Terris event type/);
  assert.throws(() => createTerrisFieldEvent({ eventType: "irrigation_applied", module: "water", fieldId: "f1", truthLabel: "verified" }), /Unsupported Terris truth label/);
  assert.throws(() => createTerrisFieldEvent({ eventType: "irrigation_applied", module: "water", fieldId: "f1", sourceMode: "magic" }), /Unsupported Terris source mode/);
  assert.throws(() => createTerrisFieldEvent({ eventType: "irrigation_applied", module: "water", fieldId: "f1", dataQuality: "perfect" }), /Unsupported Terris data quality/);
});

test("safeRandomUuid has a fallback when crypto.randomUUID is unavailable", () => {
  const original = globalThis.crypto;
  Object.defineProperty(globalThis, "crypto", { value: {}, configurable: true });
  assert.match(safeRandomUuid(), /^local-/);
  Object.defineProperty(globalThis, "crypto", { value: original, configurable: true });
});

test("water recommendation fingerprint is stable and prevents duplicate ledger append", () => {
  const field = { id: "f1" };
  const recommendation = { action: "irrigate", urgency: "high", timing: "today", sourceMode: "backend", decisionVersion: "v1" };
  const fp1 = recommendationFingerprint({ fieldId: "f1", recommendation, sourceMode: "backend", decisionVersion: "v1" });
  const fp2 = recommendationFingerprint({ fieldId: "f1", recommendation, sourceMode: "backend", decisionVersion: "v1" });
  assert.equal(fp1, fp2);
  const event = waterRecommendationEvent({ field, recommendation, weather: {}, fingerprint: fp1 });
  const first = appendRecommendationEventIfNew(createInitialState(), event);
  const second = appendRecommendationEventIfNew(first.state, waterRecommendationEvent({ field, recommendation, weather: {}, fingerprint: fp2 }));
  assert.equal(first.appended, true);
  assert.equal(second.appended, false);
  assert.equal(second.state.fieldLedgerEvents.length, 1);
});

test("render and recommendation helpers do not append ledger events or persist state", () => {
  const appSource = fs.readFileSync(new URL("../js/app.js", import.meta.url), "utf8");
  const renderBody = appSource.match(/function render\(\) \{[\s\S]*?\n\}/)?.[0] || "";
  const recommendationBody = appSource.match(/function recommendationFor\(field\) \{[\s\S]*?\n\}/)?.[0] || "";
  const computeBody = appSource.match(/function computeRecommendation\(field\) \{[\s\S]*?\n\}/)?.[0] || "";
  for (const body of [renderBody, recommendationBody, computeBody]) {
    assert.ok(!body.includes("appendLedgerEvent"));
    assert.ok(!body.includes("persist()"));
  }
  assert.ok(appSource.includes("recordLocalRecommendationTransitions"));
  assert.ok(appSource.includes("recordRecommendationLedgerEvent(field, recommendation"));
});

test("beta UI renders locked cards instead of disabled forms and handlers are guarded", () => {
  const appSource = fs.readFileSync(new URL("../js/app.js", import.meta.url), "utf8");
  assert.ok(appSource.includes("function isTerrisModuleEnabled"));
  assert.ok(appSource.includes("betaLockedCard"));
  assert.ok(appSource.includes('data-module-locked="${h(key)}"'));
  assert.ok(appSource.includes('if (!isTerrisModuleEnabled("nutrients"))'));
  assert.ok(appSource.includes('if (!isTerrisModuleEnabled("ops"))'));
  assert.ok(appSource.includes('if (!isTerrisModuleEnabled("proof"))'));
  assert.ok(!appSource.includes("Complete sample evidence task"));
});

test("module registry gates beta modules in real mode and exposes representative demo surfaces", () => {
  assert.equal(TERRIS_FEATURE_FLAGS.TERRIS_NUTRIENTS_ENABLED, false);
  const real = terrisModuleRegistryForMode("real");
  assert.equal(real.find((module) => module.key === "water").enabled, true);
  assert.equal(real.find((module) => module.key === "nutrients").enabled, false);
  assert.equal(real.find((module) => module.key === "protect").enabled, false);
  assert.equal(real.find((module) => module.key === "risk_api").enabled, false);
  const demo = terrisModuleRegistryForMode("demo");
  assert.equal(demo.find((module) => module.key === "nutrients").enabled, true);
  assert.equal(demo.find((module) => module.key === "nutrients").representativeDemo, true);
  assert.equal(demo.find((module) => module.key === "protect").enabled, false);
});

test("water applied and observation create separate ledger events", () => {
  const applied = waterAppliedEvent(createIrrigationLog({ fieldId: "f1", durationMin: 60, amountMm: 12, source: "manual" }));
  const observed = fieldObservationEvent(createObservation({ fieldId: "f1", condition: "Looks dry" }));
  assert.equal(applied.eventType, "irrigation_applied");
  assert.equal(observed.eventType, "field_observation");
  assert.notEqual(applied.eventType, "irrigation_verified");
});

test("offline water records preserve queued ledger metadata", () => {
  const applied = waterAppliedEvent(createIrrigationLog({ fieldId: "f1", durationMin: 60, amountMm: 12, source: "manual", offline: true }));
  const observed = fieldObservationEvent(createObservation({ fieldId: "f1", condition: "Looks dry", offline: true }));
  assert.equal(applied.payload.syncStatus, "queued");
  assert.equal(applied.ledgerMetadata.queuedForSync, true);
  assert.equal(observed.payload.syncStatus, "queued");
  assert.equal(observed.ledgerMetadata.queuedForSync, true);
  const state = appendLedgerEvent(createInitialState(), applied);
  assert.equal(state.ledgerMetadata.queuedForSync, true);
});

test("nutrient drafts require metadata and quantity evidence", () => {
  const missingMetadata = createNutrientRecord({ fieldId: "f1", nutrientType: "N", appliedQuantity: 10, unit: "kg", applicationMethod: "fertigation" });
  assert.equal(missingMetadata.recordStatus, "draft_missing_inputs");
  assert.equal(missingMetadata.truthLabel, "reported");
  assert.ok(missingMetadata.missingData.includes("source type"));
  assert.equal(nutrientLedgerEvent(missingMetadata).eventType, "fertigation_applied");
  assert.equal(nutrientLedgerEvent(missingMetadata).dataQuality, "blocked");

  const noQuantity = createNutrientRecord({ fieldId: "f1", nutrientType: "N", sourceType: "fertilizer", unit: "kg", applicationMethod: "broadcast" });
  assert.equal(noQuantity.recordStatus, "draft_missing_inputs");
  assert.equal(noQuantity.truthLabel, "unknown");
  assert.ok(noQuantity.missingData.includes("quantity evidence"));
  assert.equal(nutrientLedgerEvent(noQuantity).dataQuality, "blocked");
});

test("nutrient status distinguishes planned, calculated, and manual applied records", () => {
  const planned = createNutrientRecord({ fieldId: "f1", nutrientType: "N", sourceType: "fertilizer", plannedQuantity: 20, unit: "kg", applicationMethod: "fertigation" });
  const event = nutrientLedgerEvent(planned);
  assert.equal(planned.appliedQuantity, null);
  assert.equal(planned.truthLabel, "unknown");
  assert.equal(planned.recordStatus, "planned");
  assert.equal(event.truthLabel, "unknown");
  assert.equal(event.eventType, "fertigation_plan");

  const calculated = createNutrientRecord({ fieldId: "f1", nutrientType: "N", sourceType: "fertilizer", waterVolume: 10, concentration: 2, plannedQuantity: 25, unit: "kg", applicationMethod: "fertigation" });
  assert.equal(calculated.appliedQuantity, 20);
  assert.equal(calculated.truthLabel, "calculated");
  assert.equal(calculated.recordStatus, "applied");
  assert.equal(plannedAppliedVariance(calculated), -5);
  assert.equal(nutrientLedgerEvent(calculated).eventType, "fertigation_applied");

  const manualApplied = createNutrientRecord({ fieldId: "f1", nutrientType: "K", sourceType: "fertilizer", appliedQuantity: 8, unit: "kg", applicationMethod: "broadcast" });
  assert.equal(manualApplied.recordStatus, "applied");
  assert.equal(manualApplied.truthLabel, "reported");
  assert.equal(nutrientLedgerEvent(manualApplied).eventType, "nutrient_application");
  assert.equal(nutrientLedgerEvent(manualApplied).dataQuality, "medium");
});

test("offline nutrient records use nutrient_log queue semantics and queued ledger metadata", () => {
  const record = createNutrientRecord({ fieldId: "f1", nutrientType: "N", sourceType: "fertilizer", appliedQuantity: 10, unit: "kg", applicationMethod: "broadcast", offline: true, representativeDemo: true });
  const event = nutrientLedgerEvent(record);
  const appSource = fs.readFileSync(new URL("../js/app.js", import.meta.url), "utf8");
  assert.equal(record.syncStatus, "queued");
  assert.equal(event.payload.syncStatus, "queued");
  assert.equal(event.ledgerMetadata.queuedForSync, true);
  assert.equal(event.sourceMode, "demo");
  assert.ok(appSource.includes('queueSyncAction({ kind: "nutrient_log", payload: record })'));
});

test("energy beta withholds real-mode comparison without pump and tariff evidence", () => {
  const withheld = compareEligibleWindows({ mode: "real", recommendation: {}, windows: [], tariff: null, pumpEvidence: null });
  assert.equal(withheld.status, "missing_pump_evidence");
  const result = compareEligibleWindows({
    mode: "real",
    recommendation: { timing: "today" },
    pumpEvidence: { id: "pump-1" },
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

test("ops task completion requires notes and preserves attachments", () => {
  const task = createFieldTask({ title: "Verify application", module: "water", taskType: "verify_application", fieldId: "f1" });
  assert.throws(() => completeFieldTask(task, {}), /operator note/);
  const completed = completeFieldTask(task, { notes: "Checked row end", attachments: ["photo-1"], offline: true });
  const event = taskEvent(completed, true);
  assert.equal(completed.offlineSyncState, "queued");
  assert.deepEqual(completed.attachments, ["photo-1"]);
  assert.equal(event.eventType, "task_completed");
  assert.ok(event.limitations[0].includes("not agronomic verification"));
});

test("proof packet is draft when required evidence is missing", () => {
  const packet = createEvidencePacket({ moduleScope: "water", farmScope: "farm-1", fieldScope: "f1", dateWindow: { start: "2026-06-01", end: "2026-06-02" }, events: [], missingInputs: ["controller confirmation"] });
  assert.equal(packet.status, "draft_missing_evidence");
  assert.ok(packet.missingInputs.includes("filtered ledger evidence"));
  assert.ok(packet.missingInputs.includes("matching reviewed event scope"));
  assert.equal(packet.disclaimer, TERRIS_PROOF_DISCLAIMER);
  assert.ok(!/official regulatory filing support/i.test(packet.disclaimer));
});

test("proof packet filters events by scope, date window, and requires explicit review for ready status", () => {
  const events = [
    createTerrisFieldEvent({ id: "e1", eventType: "irrigation_applied", module: "water", farmId: "farm-1", fieldId: "f1", blockId: "b1", occurredAt: "2026-06-02T12:00:00.000Z", truthLabel: "reported", dataQuality: "medium" }),
    createTerrisFieldEvent({ id: "e2", eventType: "nutrient_application", module: "nutrients", farmId: "farm-1", fieldId: "f1", occurredAt: "2026-06-02T12:00:00.000Z", truthLabel: "reported", dataQuality: "medium" }),
    createTerrisFieldEvent({ id: "e3", eventType: "irrigation_applied", module: "water", farmId: "farm-2", fieldId: "f1", occurredAt: "2026-06-02T12:00:00.000Z", truthLabel: "reported", dataQuality: "medium" }),
    createTerrisFieldEvent({ id: "e4", eventType: "irrigation_applied", module: "water", farmId: "farm-1", fieldId: "f1", occurredAt: "2026-05-30T12:00:00.000Z", truthLabel: "reported", dataQuality: "medium" }),
    createTerrisFieldEvent({ id: "e5", eventType: "irrigation_applied", module: "water", fieldId: "f1", blockId: "b1", occurredAt: "2026-06-02T12:00:00.000Z", truthLabel: "reported", dataQuality: "medium" }),
  ];
  const scope = { moduleScope: "water", farmScope: "farm-1", fieldScope: "f1", blockScope: "b1", dateWindow: { start: "2026-06-01", end: "2026-06-03" } };
  const filtered = filterEvidenceEvents(events, scope);
  assert.deepEqual(filtered.map((event) => event.id), ["e1"]);
  const reviewSnapshot = { scope, includedEventIds: filtered.map((event) => event.id), reviewSignature: evidenceReviewSignature(scope, filtered), reviewedAt: "2026-06-03T00:00:00.000Z" };
  const unreviewed = createEvidencePacket({ ...scope, events, reviewConfirmed: false, reviewSnapshot });
  assert.equal(unreviewed.status, "draft_missing_evidence");
  const reviewed = createEvidencePacket({ ...scope, events, reviewConfirmed: true, reviewSnapshot });
  assert.equal(reviewed.status, "ready_operational_record");
  assert.deepEqual(reviewed.includedEventIds, ["e1"]);
  assert.equal(reviewed.reviewRows[0].eventType, "irrigation_applied");
  assert.equal(reviewed.reviewSignature, reviewSnapshot.reviewSignature);

  const editedScope = { ...scope, fieldScope: null };
  const editedEvents = filterEvidenceEvents(events, editedScope);
  const staleReview = createEvidencePacket({ ...editedScope, events: editedEvents, preFiltered: true, reviewConfirmed: true, reviewSnapshot });
  assert.equal(staleReview.status, "draft_missing_evidence");
  assert.ok(staleReview.missingInputs.includes("matching reviewed event scope"));

  const event = evidencePacketEvent(reviewed);
  assert.equal(event.farmId, "farm-1");
  assert.equal(event.fieldId, "f1");
  assert.equal(event.blockId, "b1");
});

test("representative demo metadata reaches beta records and ledger events", () => {
  const nutrient = createNutrientRecord({ fieldId: "f1", nutrientType: "N", sourceType: "fertilizer", plannedQuantity: 10, unit: "kg", applicationMethod: "fertigation", representativeDemo: true });
  assert.equal(nutrient.representativeDemo, true);
  assert.equal(nutrientLedgerEvent(nutrient).sourceMode, "demo");
  const task = createFieldTask({ title: "Demo task", module: "ops", taskType: "inspect_field", fieldId: "f1", representativeDemo: true });
  assert.equal(taskEvent(task).sourceMode, "demo");
  const packetEvent = createTerrisFieldEvent({ id: "demo-e", eventType: "irrigation_applied", module: "water", farmId: "farm-1", fieldId: "f1", occurredAt: "2026-06-02T12:00:00.000Z" });
  const packetScope = { moduleScope: "water", farmScope: "farm-1", dateWindow: { start: "2026-06-01", end: "2026-06-03" } };
  const packetReview = { scope: packetScope, includedEventIds: [packetEvent.id], reviewSignature: evidenceReviewSignature(packetScope, [packetEvent]), reviewedAt: "2026-06-03T00:00:00.000Z" };
  const packet = createEvidencePacket({ ...packetScope, events: [packetEvent], reviewConfirmed: true, reviewSnapshot: packetReview, representativeDemo: true });
  assert.equal(packet.representativeDemo, true);
  assert.equal(evidencePacketEvent(packet).sourceMode, "demo");
});

test("app reconciles global ledger sync metadata from the current queue", async () => {
  const originalNavigator = global.navigator;
  Object.defineProperty(global, "navigator", { value: { onLine: true }, configurable: true, writable: true });
  storage.set("queue", []);
  syncService.configure({ backendSyncEnabled: false });
  try {
    syncService.queueAction({ kind: "irrigation_log", payload: { id: "log-1" } });
    assert.equal(syncService.status().pending, 1);
    const flushed = await syncService.flushQueue();
    assert.equal(flushed.reason, "backend_sync_not_enabled");
    assert.equal(syncService.status().pending, 1);
    const appSource = fs.readFileSync(new URL("../js/app.js", import.meta.url), "utf8");
    assert.ok(appSource.includes("function reconcileLedgerSyncMetadata"));
    assert.ok(appSource.includes("syncService.status().pending > 0"));
    assert.ok(appSource.includes("queueSyncAction"));
    assert.ok(appSource.includes("await syncService.flushQueue(); reconcileLedgerSyncMetadata();"));
  } finally {
    storage.set("queue", []);
    syncService.configure({ backendSyncEnabled: false });
    Object.defineProperty(global, "navigator", { value: originalNavigator, configurable: true, writable: true });
  }
});

test("offline ops and proof actions preserve local queue semantics", () => {
  const task = createFieldTask({ title: "Inspect pump", module: "ops", taskType: "inspect_pump", fieldId: "f1", offlineSyncState: "queued", representativeDemo: true });
  const completed = completeFieldTask(task, { notes: "Pump inspected.", attachments: ["photo-1"], offline: true });
  const proofEvent = createTerrisFieldEvent({ id: "proof-e", eventType: "irrigation_applied", module: "water", farmId: "farm-1", fieldId: "f1", occurredAt: "2026-06-02T12:00:00.000Z" });
  const proofScope = { moduleScope: "water", farmScope: "farm-1", dateWindow: { start: "2026-06-01", end: "2026-06-03" } };
  const reviewSnapshot = { scope: proofScope, includedEventIds: [proofEvent.id], reviewSignature: evidenceReviewSignature(proofScope, [proofEvent]), reviewedAt: "2026-06-03T00:00:00.000Z" };
  const packet = createEvidencePacket({ ...proofScope, events: [proofEvent], reviewConfirmed: true, reviewSnapshot, syncStatus: "queued", representativeDemo: true });
  const appSource = fs.readFileSync(new URL("../js/app.js", import.meta.url), "utf8");
  assert.equal(taskEvent(task).ledgerMetadata.queuedForSync, true);
  assert.equal(taskEvent(completed, true).ledgerMetadata.queuedForSync, true);
  assert.equal(packet.syncStatus, "queued");
  assert.equal(packet.reviewSignature, reviewSnapshot.reviewSignature);
  assert.equal(evidencePacketEvent(packet).ledgerMetadata.queuedForSync, true);
  assert.ok(appSource.includes('queueSyncAction({ kind: "task_create", payload: task })'));
  assert.ok(appSource.includes('queueSyncAction({ kind: "task_complete", payload: completed })'));
  assert.ok(appSource.includes('queueSyncAction({ kind: "proof_packet", payload: packet })'));
});

test("offline actionable voice command queues exactly one operational action", () => {
  storage.set("queue", []);
  const command = parseVoiceCommand("Field north block looks dry", { fieldId: "f1" });
  applyVoiceAction(command, {
    onIrrigation: (payload) => syncService.queueAction({ kind: "irrigation_log", payload }),
    onCondition: (payload) => syncService.queueAction({ kind: "observation", payload }),
    onNote: (payload) => syncService.queueAction({ kind: "field_note", payload }),
    onNoop: () => {},
  });
  const queue = syncService.getQueue();
  const voiceSource = fs.readFileSync(new URL("../js/services/voiceAgent.js", import.meta.url), "utf8");
  assert.equal(queue.length, 1);
  assert.equal(queue[0].kind, "observation");
  assert.ok(!voiceSource.includes('kind: "voice"'));
  storage.set("queue", []);
});

test("materially changed recommendation creates one new event and local/backend are distinguishable", () => {
  const field = { id: "f1" };
  const local = { action: "monitor", urgency: "low", timing: "today", sourceMode: "local" };
  const changed = { action: "irrigate", urgency: "high", timing: "today", sourceMode: "local" };
  const localEvent = waterRecommendationEvent({ field, recommendation: local, weather: {}, fingerprint: recommendationFingerprint({ fieldId: "f1", recommendation: local, sourceMode: "local", decisionVersion: "d1" }) });
  const first = appendRecommendationEventIfNew(createInitialState(), localEvent);
  const duplicate = appendRecommendationEventIfNew(first.state, localEvent);
  const changedEvent = waterRecommendationEvent({ field, recommendation: changed, weather: {}, fingerprint: recommendationFingerprint({ fieldId: "f1", recommendation: changed, sourceMode: "local", decisionVersion: "d1" }) });
  const second = appendRecommendationEventIfNew(duplicate.state, changedEvent);
  const backendEvent = waterRecommendationEvent({ field, recommendation: { ...changed, sourceMode: "backend" }, weather: {}, fingerprint: recommendationFingerprint({ fieldId: "f1", recommendation: changed, sourceMode: "backend", decisionVersion: "d1" }) });
  const third = appendRecommendationEventIfNew(second.state, backendEvent);
  assert.equal(duplicate.appended, false);
  assert.equal(second.appended, true);
  assert.equal(third.appended, true);
  assert.deepEqual(third.state.fieldLedgerEvents.map((event) => event.sourceMode).sort(), ["backend", "local", "local"]);
});

test("offline voice, photo metadata, translation, and field association remain explicit", () => {
  const photo = createAttachmentMetadata({ fieldId: "f1", type: "photo", uri: "local://photo.jpg", geotag: { lat: 1, lon: 2 } });
  const voice = createVoiceTimelineEntry({ fieldId: "f1", transcript: "Looks dry", intent: "UPDATE_CONDITION", outcome: "queued", attachmentRefs: [photo.id], translation: { display: "Se ve seco", locale: "es" }, offline: true });
  assert.equal(photo.syncStatus, "queued");
  assert.equal(voice.fieldId, "f1");
  assert.equal(voice.translation.display, "Se ve seco");
  assert.equal(voice.syncStatus, "queued");
});
