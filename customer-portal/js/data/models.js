/**
 * Core data model foundation for Velia.
 * JSDoc typedefs are used as typed contracts for the current static-app foundation.
 */

/** @typedef {{ id: string; name: string; role: string; language: string; farmIds: string[]; }} User */
/** @typedef {{ id: string; name: string; location: string; timezone: string; acreage: number; operationType: 'smallholder'|'commercial'|'enterprise'; }} Farm */
/** @typedef {{ id: string; farmId: string; name: string; cropId: string; acreage: number; soilType: string; irrigationMethod: string; status: 'stable'|'attention'|'critical'; waterStressLevel: 'low'|'moderate'|'high'; lastIrrigationAt: string; dataSourceStatus: 'manual'|'weather_only'|'sensor_connected'|'controller_connected'; }} Field */
/** @typedef {{ id: string; name: string; stage: string; idealMoistureRange: [number, number]; }} Crop */
/** @typedef {{ id: string; fieldId: string; type: 'irrigate_now'|'delay_irrigation'|'inspect_field'|'monitor'; action: string; timing: string; confidence: 'low'|'moderate'|'high'; reasoning: string[]; riskFlags: string[]; createdAt: string; }} IrrigationRecommendation */
/** @typedef {{ id: string; fieldId: string; amountMm: number; durationMin: number; method: string; performedAt: string; source: 'manual'|'controller'|'voice'; }} IrrigationLog */
/** @typedef {{ id: string; type: string; severity: 'low'|'medium'|'high'; fieldId: string|null; action: string; timeSensitivity: string; message: string; createdAt: string; }} Alert */
/** @typedef {{ condition: string; temperatureC: number; humidityPct: number; rainProbabilityPct: number; windKph: number; summary: string; date: string; }} WeatherSummary */
/** @typedef {{ id: string; kind: 'manual'|'weather'|'sensor'|'controller'|'satellite'; status: 'connected'|'configured'|'integration_ready'; provider: string; lastSyncAt: string|null; }} DataSource */
/** @typedef {{ id: string; provider: 'wiseconn'|'talgil'|'hortau'|'manual'|'weather'|'satellite'|'future_provider'; status: 'connected'|'configured'|'integration_ready'; metadata: Record<string, string>; }} Integration */
/** @typedef {{ id: string; fieldId: string; text: string; createdAt: string; source: 'manual'|'voice'; synced: boolean; }} FieldNote */
/** @typedef {{ id: string; periodLabel: string; recommendedMm: number; loggedMm: number; estimatedWaterSavedPct: number|null; fieldPerformanceSummary: string; }} ReportSummary */
/** @typedef {{ isOnline: boolean; lastSyncAt: string|null; pendingActions: number; status: 'synced'|'pending'|'offline'; }} SyncStatus */

/** @typedef {{ id: string; language: string; startedAt: string; endedAt?: string; status: 'idle'|'listening'|'processing'|'responding'; fieldId?: string; }} VoiceSession */
/** @typedef {{ id: string; sessionId: string; language: string; text: string; confidence: number; createdAt: string; source: 'mock_stt'; }} VoiceTranscript */
/** @typedef {'ASK_RECOMMENDATION'|'EXPLAIN_RECOMMENDATION'|'LOG_IRRIGATION'|'ADD_FIELD_NOTE'|'READ_ALERTS'|'CREATE_REMINDER'|'SWITCH_LANGUAGE'|'OPEN_FIELD'|'UNKNOWN'} VoiceIntent */
/** @typedef {{ id: string; sessionId: string; transcriptId: string; intent: VoiceIntent; entities: Record<string, string|number>; confidence: number; }} VoiceCommand */
/** @typedef {{ id: string; type: 'save_note'|'log_irrigation'|'navigate'|'reminder'|'noop'; payload: Record<string, unknown>; requiresLiveData?: boolean; queued?: boolean; }} VoiceAction */
/** @typedef {{ id: string; sessionId: string; text: string; confidence: 'low'|'moderate'|'high'; uncertainty?: string; spoken: boolean; createdAt: string; }} VoiceAgentResponse */

export const modelVersion = "velia-foundation-v1";
