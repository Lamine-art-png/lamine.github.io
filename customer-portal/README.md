# AGRO-AI Water Command Center

AGRO-AI Water Command Center is the operator-facing command surface for farm water decisions.
It is designed around the operational chain:
**Observe → Recommend → Execute → Verify**.

## What this foundation includes

- Production-style app shell with mobile-first navigation and route-based sections.
- Primary screens:
  - Command Center
  - Intelligence
  - Verification
  - Reports
  - Integrations
- Reusable UI patterns (cards, badges, action buttons, chips, voice controls).
- Strong mock data layer for daily irrigation decisions and operational context.
- Offline-first foundation with local queue and sync status model.
- Multilingual-ready i18n structure (English active, additional languages predeclared).
- Recommendation engine placeholder service with replaceable business logic.
- Modular integration adapter system for WiseConn, Talgil, Hortau, Manual, Weather, Satellite, and FutureProvider.
- Voice Agent module foundation for field-first voice workflows.

## Architecture overview

```text
customer-portal/
  index.html
  styles.css
  js/
    app.js                      # Shell, routes, rendering, UI event flow
    data/
      models.js                 # Typed JSDoc model contracts
      mockData.js               # Seed mock farm/field/weather/alerts data
    i18n/
      translations.js           # Dictionary structure
      index.js                  # t(), setLanguage(), language()
    services/
      storageService.js         # localStorage abstraction
      syncService.js            # queue model + mock sync
      recommendationEngine.js   # recommendationEngine placeholder
      voiceAgent.js             # voice service placeholder methods
      integrations/
        baseAdapter.js          # integration interface
        adapters.js             # provider registry + adapters
```

## Run locally

```bash
cd customer-portal
python -m http.server 4173
```

Open `http://localhost:4173`.

## What is real today
- WiseConn runtime context is connected when tenant/runtime credentials are valid.
- Talgil runtime context is connected when tenant/runtime credentials are valid.
- Intelligence engine endpoints are active for manual and live recommendation flows.
- Live recommendation shortcuts support override-only request bodies.

## What is pending
- Full report generation rollout by deployment environment.
- Execution and observation state automation across all controller integrations.

## Hosting note
- Portal URL target in code/config is: `https://app.agroai-pilot.com`.
- **Important:** this domain currently has a hosting conflict with Velia and must be corrected in deployment ownership/routing later.

## Data model foundation

The model layer defines contracts for:

- `User`, `Farm`, `Field`, `Crop`
- `IrrigationRecommendation`, `IrrigationLog`, `Alert`, `WeatherSummary`
- `DataSource`, `Integration`, `FieldNote`, `ReportSummary`, `SyncStatus`
- Voice models: `VoiceSession`, `VoiceTranscript`, `VoiceCommand`, `VoiceIntent`, `VoiceAction`, `VoiceAgentResponse`

## Offline-first foundation

- Local persistence abstraction (`storageService`).
- Queue model for field actions and voice actions.
- Sync status object (`isOnline`, pending count, last sync, state).
- Mock sync worker to flush queue when connectivity returns.
- Graceful offline language for voice requests requiring live data:
  - “I saved your request. I will update it when connection returns.”

## Recommendation engine placeholder

`recommendationEngine.generateRecommendation()` currently evaluates mock features:

- Crop and stage
- Weather summary
- Last irrigation timing
- Water stress level
- Field status / data source context

Returns:

- Recommendation type
- Action
- Timing
- Confidence
- Reasoning list
- Risk flags

This module is intentionally isolated so AGRO-AI production logic can replace it without UI rewrites.

## Integrations adapter system

All integrations conform to a consistent adapter interface:

- `connect()`
- `fetchFields()`
- `fetchIrrigationLogs()`
- `sync()`

Current adapters are placeholders for:

- WiseConn
- Talgil
- Hortau
- Manual
- Weather
- Satellite
- FutureProvider

## Voice agent foundation

### Architecture

- UI entry points in Today, Assistant, and Field Detail (plus note/log workflows).
- Service methods:
  - `startListening`
  - `stopListening`
  - `transcribe`
  - `detectIntent`
  - `executeVoiceAction`
  - `speakResponse`
  - `saveOfflineVoiceAction`
  - `syncQueuedVoiceActions`

### Current mock behavior

1. User taps microphone.
2. App enters listening state.
3. Mock transcript appears.
4. Mock intent is detected.
5. Mock response appears.
6. Action is executed or queued based on connectivity.

### Offline voice handling

- Voice notes and actions are saved when offline.
- User sees clear queue/sync language.
- No blocking capture flow.

### Future production integration points

- Replace mock `transcribe()` with cloud/on-device STT.
- Replace mock `speakResponse()` with TTS provider.
- Add contextual intent model and entity extraction.
- Add secure voice audit and consent controls.

### Future multilingual roadmap

- English active now.
- Predeclared expansion path: French, Spanish, Wolof, Arabic, Hindi, Portuguese.
- Voice models already include `language` fields.

## Next features to build

1. Real authentication and tenant-aware farm switching.
2. API-backed field data and recommendation history.
3. Rich reminder scheduling and alert acknowledgement flow.
4. Production-grade sync conflict resolution.
5. Real speech-to-text and text-to-speech provider adapters.
6. Language pack expansion and localized voice prompts.
7. Report export pipeline and enterprise audit trail.
