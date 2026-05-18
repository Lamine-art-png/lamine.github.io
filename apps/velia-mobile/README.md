# Velia Mobile + Agentic AI Brain v0.1 (AGRO-AI)

Velia helps farms make better water decisions, act faster, and understand what happened across their fields.

This app now includes a frontend-local **Agentic AI Brain architecture** with clean interfaces and mock providers, designed for future backend/serverless migration.

## AI Brain architecture (`js/ai/`)

- `aiOrchestrator.js` — central coordinator for goals and agent/tool execution.
- `modelRouter.js` — model routing profiles:
  - `fastModel` (translation/classification/extraction)
  - `reasoningModel` (irrigation planning)
  - `visionModel` (future image analysis)
  - `embeddingModel` (RAG embeddings)
- `agentPlanner.js` — ReAct-style planner (Reason → Act → Observe → Decide) with concise decision trace.
- `toolRegistry.js` — normalized callable tools with schemas and mock/future distinction.
- `ragEngine.js`, `embeddingService.js`, `vectorStore.js`, `knowledgeBase.js` — local RAG foundation + GraphRAG-ready schema.
- `memoryStore.js` — field-level long-term memory events and retrieval.
- `multimodalProcessor.js` — text/voice processing plus image-analysis placeholder.
- `fieldReasoningAgent.js`, `weatherRiskAgent.js`, `irrigationDecisionAgent.js` — core decision reasoning flow.
- `verificationAgent.js` — post-action recommendation outcome verification.
- `translationAgent.js` — language-neutral decision with presentation translation layer.
- `safetyGuardrails.js` — uncertainty/limitation enforcement.
- `evaluationHarness.js` — scenario-based decision quality checks.

## Model routing and provider-readiness

Model Router supports future provider integration points for:
- Gemini
- OpenAI
- Anthropic
- local/open-source models

Provider interface readiness exists for:
- LLM provider
- embedding provider
- vector database provider
- weather provider
- satellite provider
- integration provider
- translation provider

## Tool registry

Current tool registry includes:
- `getFarmProfile`
- `getFieldProfile`
- `getWeather`
- `getForecast`
- `getIrrigationLogs`
- `getFieldObservations`
- `getRecommendationHistory`
- `saveIrrigationLog`
- `saveFieldObservation`
- `saveVoiceNote`
- `retrieveKnowledge`
- `calculateWaterBalance`
- `estimateIrrigationNeed`
- `calculateConfidence`
- `generateExplanation`
- `verifyRecommendationOutcome`
- `translateText`

Each tool has name/description/input schema/output schema/execute/mode.

## RAG + GraphRAG-ready foundation

Seed knowledge covers:
- irrigation decision principles
- soil water holding concepts
- crop water demand basics
- weather risk interpretation
- confidence + missing data interpretation
- observation guidance
- safe wording + limitations

RAG pipeline includes:
- chunking
- embedding placeholder
- vector store placeholder
- semantic retrieval + ranking
- citation metadata

Graph schema includes entities and relationships such as:
- weather risk increases recommendation risk
- unknown soil type reduces confidence
- field observations require checks

## Memory architecture

Field-level memory stores:
- profile context
- recommendation history
- irrigation logs
- observations
- voice notes
- user overrides
- recurring issues
- confidence changes
- missing data patterns
- verification outcomes

Functions:
- `getFieldMemory(fieldId)`
- `updateFieldMemory(fieldId, event)`
- `summarizeFieldMemory(fieldId)`
- `retrieveRelevantMemory(fieldId, query)`

## Decision + verification loop

Today decisions now come from `irrigationDecisionAgent` via `aiOrchestrator` and return structured output:

```json
{
  "decisionId": "...",
  "fieldId": "...",
  "action": "irrigate | check field first | wait | monitor | update missing data | escalate to advisor",
  "timing": "...",
  "urgency": "high|medium|low",
  "estimatedDurationRange": "...",
  "confidenceScore": 0.0,
  "confidenceLabel": "high|moderate|low",
  "reasons": [],
  "uncertainties": [],
  "missingData": [],
  "fieldChecks": [],
  "risks": [],
  "nextBestAction": "...",
  "decisionTrace": {
    "dataChecked": [],
    "toolsUsed": [],
    "confidenceDrivers": [],
    "uncertainty": []
  },
  "knowledgeSources": [],
  "verificationPlan": {}
}
```

Verification statuses include:
- followed
- partially followed
- not followed
- no confirmation
- contradictory observation
- needs follow-up

## Safety guardrails

- No exact soil moisture claims without sensors.
- No guaranteed yield or guaranteed savings language.
- Recommendation (not command) framing.
- Explicit uncertainty + missing data.
- Field-check guidance when confidence is low.
- Stale weather warnings.
- Insufficient-data warnings.

## Multilingual architecture

Decision object stays language-neutral; translation is applied only to final user-facing explanation.

Language routing prepared for:
- English, French, Spanish, Portuguese, Arabic, Wolof, Hindi.

## Evaluation harness

Scenario coverage:
- sparse data farm
- manual irrigation farm
- high heat and dry field
- rain expected soon
- unknown soil type
- stale weather
- connected controller scenario
- user override
- voice log irrigation
- ask why confidence is low
- ask in another language

Assertions focus on:
- action reasonableness
- confidence behavior
- missing data exposure
- explanation clarity
- guardrail presence

## Run locally

```bash
cd apps/velia-mobile
python -m http.server 4174
```

## Tests

```bash
cd apps/velia-mobile
npm test
```

## Future production deployment path

1. Move AI orchestrator and tool execution to backend/serverless APIs.
2. Swap mock modelRouter/provider calls for real LLM/embedding providers.
3. Replace local vector placeholder with production vector database.
4. Connect real weather/satellite/integration adapters.
5. Persist memory and verification events in tenant-safe backend storage.


## Backend API fallback wiring

`js/services/apiClient.js` uses `http://localhost:4310` by default and can be overridden with:

```js
localStorage.setItem("veliaApiBaseUrl", "https://your-api-host");
```

Runtime behavior is backend-first with local fallback for:
- weather context
- assistant query
- voice intent interpretation
