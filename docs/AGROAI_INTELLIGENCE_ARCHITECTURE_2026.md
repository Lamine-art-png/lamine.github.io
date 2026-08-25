# AGRO-AI Intelligence Architecture — 2026

Status: implementation design and rollout contract
Owner: AGRO-AI
Last updated: 2026-08-21

## 1. Product thesis

AGRO-AI should not compete as a generic agriculture chatbot.

The durable product is an evidence-native operating intelligence layer above the systems an agricultural business already uses. It should connect operational data, build a current field state, reason within scientific and policy constraints, propose bounded actions, preserve human control, and verify what happened afterward.

The operating loop is:

`CONNECT → NORMALIZE → OBSERVE → REASON → APPROVE → EXECUTE → VERIFY → PROVE → LEARN`

The moat compounds from the last four steps. A foundation model can summarize data. It cannot recreate a customer's historical evidence, field-specific calibration, connector normalization, decision history, approval policy, and verified outcomes unless those systems have been built and used over time.

## 2. What already exists

The repository already contains substantial production foundations:

- Tenant-scoped workspace and evidence context assembly.
- Field Intelligence capture with voice, media, geolocation, timestamps, extraction provenance, idempotency, and review states.
- Evidence/source records with confidence and quality metadata.
- Hybrid model routing across remote, edge, and local inference lanes.
- Ask AGRO-AI paid-route enforcement and quota reservation/commit/release.
- Task, approval, execution, evidence, reporting, decision-workbench, field-operations, and agent APIs.
- A deterministic agent orchestrator with action allowlists and audit records.
- Customer-facing safety rules that prohibit hidden physical actuation and require human review for consequential operations.

These are more valuable than a model swap because they are the control plane required for trustworthy operational AI.

## 3. Gap between the promise and the current implementation

The public Field Intelligence promise is stronger than a prose assistant. It says AGRO-AI separates facts from hypotheses, records uncertainty, identifies the next step, assigns work, preserves traceability to source media, and verifies outcomes.

Before this work, higher-level Ask AGRO-AI reasoning still behaved primarily as compact evidence + prompt → model prose. The main gaps were:

1. No explicit field/evidence graph passed to the reasoning model.
2. No deterministic conflict detection between recent comparable sources.
3. No source freshness and quality contribution to answer confidence.
4. No versioned scientific calculation layer between raw evidence and model reasoning.
5. No strict output contract separating facts, derived findings, hypotheses, unknowns, conflicts, recommendations, risk, and verification.
6. No post-generation check that numeric recommendations were traceable to evidence.
7. Structured reasoning was not visible or persisted with the Portal conversation.
8. The agent orchestrator's LLM rewrite adapter was effectively a placeholder rather than a meaningful reasoning layer.

## 4. Architecture implemented in Intelligence Graph v1

### 4.1 Evidence graph

`app/services/intelligence_grounding.py`

Each request is converted into a compact graph before the frontier model runs. The graph separates:

- observed/source evidence;
- derived/aggregate context;
- explicit unknowns;
- conflicting measurements;
- source freshness;
- source quality;
- provenance;
- deterministic science results;
- decision constraints.

The graph has explicit schema and science-ruleset versions so future answers can be reproduced against the logic that generated them.

### 4.2 Source-aware confidence

The model does not get to set confidence independently of the evidence.

Grounding confidence is calculated from source type, freshness, quality, and any supplied confidence, with penalties for conflicts and missing data. Post-generation validation caps model confidence at the grounding confidence. Conflicts and material missing data reduce the cap further.

This is intentionally conservative. Confidence should measure the strength of the decision basis, not how persuasive the generated prose sounds.

### 4.3 Deterministic science kernel

Initial rules are intentionally narrow and versioned:

- Crop evapotranspiration: `ETc = Kc × ETo`, only when both ETo and Kc are explicitly supplied by compatible evidence.
- Measured irrigation volume: `volume = measured flow rate × runtime`.
- Gross applied depth: `gallons ÷ (27,154.2857 × acres)`.

The science kernel never guesses crop coefficient, irrigation efficiency, root-zone depth, allowable depletion, pesticide label constraints, or legal/compliance status.

This design follows a core principle: use deterministic or process-based calculations where the physics/agronomy is known, and use frontier AI for synthesis, ambiguity resolution, explanation, planning, and cross-source reasoning.

### 4.4 GPT-5.6 reasoning lane

`app/services/gpt56_intelligence.py`

The canonical paid Ask AGRO-AI route attempts an OpenAI Responses API reasoning lane first. It uses Structured Outputs and an explicit evidence-grounding contract.

Default routing:

| Workload | Default model | Reasoning |
| --- | --- | --- |
| Fast, low-impact summary | GPT-5.6 Luna | low |
| Standard operational reasoning | GPT-5.6 Terra | medium |
| Deep/report/high-impact agricultural decision | GPT-5.6 Sol | high |

High-impact subjects such as irrigation, crop protection, nutrients, disease, equipment control, compliance, and external submissions escalate to Sol even if the UI requested a faster mode.

Optional Pro mode is environment-gated and off by default. It should be reserved for the highest-value deep analyses after cost/latency evaluation.

### 4.5 Structured decision envelope

GPT-5.6 must return a schema containing:

- answer;
- grounded facts + evidence IDs;
- deterministic derived findings + rule IDs;
- hypotheses + confidence + verification method;
- unknowns + why they matter;
- conflicts + resolution path;
- recommendations + priority + rationale + evidence IDs;
- human-approval flag;
- expiration condition;
- verification condition;
- risk flags;
- calibrated confidence block.

The application post-validates the structure. Invalid evidence references are removed. Derived findings must reference an actually executed science rule. Unsupported numeric recommendations are dropped. Material physical/external actions are forced to human approval.

### 4.6 Portal Evidence Intelligence panel

Structured reasoning is persisted with the conversation and rendered under the answer. Customers can inspect:

- confidence;
- evidence count;
- conflict count;
- AGRO-AI correlations/science checks;
- visible facts;
- derived findings;
- uncertainty;
- verification plan.

The answer remains readable by default. The evidence layer is expandable rather than forcing operators to read a diagnostic trace.

### 4.7 Failure behavior

GPT-5.6 is additive, not a new single point of failure.

If the OpenAI lane is not configured, fails transport/API/schema validation, or produces the wrong language, the existing independent edge/OpenRouter/local recovery paths remain available. Existing paywall, tenant, quota, action approval, and audit boundaries stay in place.

## 5. Scientific basis

The design is aligned with the direction of current agricultural decision-support research:

1. **FAO Crop Evapotranspiration, revised edition (2025/2026).** FAO's revised Paper 56 expands crop-coefficient and actual-ET methods and integrates newer data sources including gridded weather data, remote sensing, and IoT. AGRO-AI should therefore normalize these inputs while retaining their quality, scale, and provenance rather than flattening them into prose.
   - FAO: https://www.fao.org/land-water/news/detail/Join-webinar-Main-Innovations-in-the-Revised-FAO-Irrigation-and-Drainage-Paper-56-Guidelines-for-Computing-Crop-Water-Requirements-13-April-2026/en
   - Bibliographic record: https://agris.fao.org/search/en/providers/124943/records/6a32b9d6b9a0a56f302a5e20

2. **Remote Sensing for Irrigation Water Management Under Climate Change (2026).** Review of 83 peer-reviewed studies identifies data integration, model transferability, ground validation, and translation into operational DSS as persistent gaps. The Intelligence Graph is designed directly around these gaps.
   - https://www.mdpi.com/2225-1154/14/6/124

3. **Internet of Things-enabled smart irrigation systems for precision water management (Agricultural Water Management, 2026).** The systematic review highlights sensor calibration, multi-source integration, long-term field validation, scalability, and interoperability as remaining adoption barriers.
   - DOI: https://doi.org/10.1016/j.agwat.2026.110615

4. **Deep learning for intelligent irrigation decision-making (Agricultural Water Management, 2025).** The review finds strong potential for hybrid architectures and edge/cloud collaboration while highlighting data quality and generalization as core limitations.
   - DOI: https://doi.org/10.1016/j.agwat.2025.109836

5. **Explainable Artificial Intelligence in Smart Agriculture (2026).** Recent review work emphasizes transparency, uncertainty, multi-source data, hybrid/physics-informed methods, human-centered AI, and trustworthy agricultural systems.
   - https://www.mdpi.com/2624-7402/8/7/270

6. **Digital twins in agriculture: systematic review on modeling, semantics, and interoperability (2026).** Current literature identifies interoperability, cross-asset integration, standardized architectures, and large-scale field validation as key gaps.
   - DOI: https://doi.org/10.1016/j.atech.2026.102283

These sources support the architecture, but they do not validate AGRO-AI's customer outcomes. Product claims about water savings, yield, cost savings, or prediction accuracy must come from AGRO-AI's own verified deployments or clearly cited external research.

## 6. Competitive boundary

The market is already strong in several areas:

- **CropX:** integrated sensors + agronomic models + irrigation/disease/nutrition insights + machine connections + task/reporting workflows.
- **Taranis:** proprietary leaf-level imagery at scale + agronomy-trained AI + field-specific advisor reports and recommendations.
- **John Deere Operations Center:** machine/work data, near-real-time monitoring, work planning, prescriptions, reporting, and a broad developer API surface.
- **Climate FieldView:** broad farm data capture/analysis, imagery, scripts, field comparisons, and partner connectivity.
- **Leaf:** normalized cross-OEM agriculture APIs plus MCP access so external AI agents can query farm data.

Therefore, AGRO-AI should not claim that data aggregation, chat over farm data, irrigation recommendations, computer vision, or MCP alone are defensible differentiators. Competitors already provide parts of each.

The stronger differentiation is the combined operating contract:

**heterogeneous customer systems → evidence graph → science-constrained reasoning → explicit uncertainty/conflict handling → governed action → verification → durable proof → field-specific learning**

The differentiated asset should become the verified decision/outcome history, not a prompt or foundation model.

## 7. What to build next

### P0 — Production qualification of Intelligence Graph v1

Ship only after:

- CI and static/type checks pass.
- Golden-evaluation cases demonstrate no regression against current Ask AGRO-AI.
- At least 50 adversarial grounding tests cover missing data, stale sensors, conflicting sensors, mixed units, malicious uploaded text, unsupported numbers, wrong-field evidence, and high-impact action requests.
- Latency and cost are measured by Luna/Terra/Sol route.
- OpenAI outage/failure injection proves fallback behavior.
- Portal shows structured reasoning correctly on mobile and both supported UI locales.

### P1 — Decision & Verification Memory

Create first-class durable records for:

- decision state at time of recommendation;
- evidence snapshot/version references;
- recommendation version;
- approver and approval policy;
- executed action / as-applied record;
- post-action observations;
- verification result;
- outcome metrics;
- operator correction/rejection reason.

This becomes a proprietary learning corpus owned by the customer and AGRO-AI's most important compounding technical asset.

### P1 — Field State Engine

Maintain a typed state per field/block instead of rebuilding context solely at question time:

- crop / variety / stage;
- soil/root-zone state;
- weather and forecast state;
- water balance and irrigation state;
- equipment/controller state;
- crop-stress observations;
- pest/disease hypotheses;
- task/decision state;
- compliance evidence state;
- source freshness/health.

State transitions must retain provenance and timestamps. Unknown should be a valid state rather than silently imputed.

### P1 — Scientific tool registry

Expand deterministic/process-based tools behind versioned contracts:

- FAO-56 water balance and dual-Kc where required inputs exist;
- effective rainfall;
- irrigation efficiency and distribution-uniformity calculations only from supplied/tested parameters;
- degree-day / phenology tools;
- basic nutrient/accounting calculators;
- equipment runtime/flow reconciliation;
- unit conversion with dimensional validation;
- weather/ET quality checks;
- source-specific validation rules.

Every scientific tool needs references, input units, valid ranges, assumptions, version, tests, and an explicit statement of what it cannot conclude.

### P1 — Intelligence Evals

Track intelligence as an engineering metric, not as a model impression:

- evidence precision/recall;
- unsupported numeric claim rate;
- citation validity;
- source-conflict detection recall;
- missing-evidence identification recall;
- calibration error / Brier score where labels exist;
- action-policy compliance;
- tool selection accuracy;
- tool argument accuracy;
- verification completeness;
- expert agreement;
- operator acceptance/override rate;
- time from exception to verified resolution;
- model cost and latency per resolved decision.

Use deterministic graders wherever possible. LLM judges can supplement but must not be the sole safety evaluator.

### P2 — Specialist intelligence cells

Introduce side-effect-free specialists behind the same evidence graph:

- Water Intelligence
- Crop Health Intelligence
- Equipment Intelligence
- Assurance/Compliance Intelligence
- Commercial/Customer Reporting Intelligence

A coordinator can request analyses from these specialists, but no specialist may execute physical or external actions directly. They return typed proposals to the approval/action layer.

### P2 — Counterfactual decision simulator

For suitable decisions, compare bounded scenarios such as:

- act now;
- wait for another observation;
- change irrigation timing;
- alternative runtime under the same verified constraints.

Counterfactuals must distinguish modelled outcomes from observed outcomes and expose assumptions. They should never be presented as certainty.

### P2 — Multimodal evidence fusion

Link Field Intelligence observations to the graph at evidence-object level:

- image regions / visual findings;
- transcript spans;
- geolocation;
- operator corrections;
- corresponding sensor and weather window;
- machine/as-applied events;
- follow-up media.

This turns a field photo or voice note into part of an auditable time series rather than a standalone AI result.

### P3 — Reliability calibration by operation

Once enough verified outcomes exist, calibrate confidence and recommendations by customer/field/crop/region/system rather than training a monolithic model on all customer data.

Examples:

- source reliability by sensor/integration;
- field-specific water-response calibration;
- recurring false-positive patterns;
- operator correction patterns;
- seasonal shifts;
- equipment-specific execution variance.

This layer should use privacy-preserving, tenant-isolated defaults and explicit contracts for any cross-customer learning.

## 8. GPT-5.6 and Codex strategy

GPT-5.6 should be the reasoning substrate, not the product identity.

- Sol: high-impact/deep operational reasoning, complex reports, complex tool planning.
- Terra: standard operator reasoning and analysis.
- Luna: fast summaries, classification, low-cost transformations after grounding.
- Pro/ultra capabilities: evaluate selectively for high-value research/analysis; never make them mandatory for normal operation.

Codex belongs primarily in the engineering loop. Use it to understand the codebase, implement/refactor features, generate tests, inspect failures, review diffs, and maintain eval suites. Do not treat a coding agent as an agronomic authority. Scientific truth must remain in cited, versioned tools and validated field evidence.

Do not build product lock-in around a single OpenAI model ID. Keep the reasoning contract provider-independent so AGRO-AI can route or replace models while preserving evidence, science, safety, and audit semantics.

## 9. Privacy and security requirements

- Keep `store=false` for OpenAI inference unless a future customer-approved data policy explicitly changes this.
- Never place connector credentials or secrets in model context.
- Tenant isolation applies before retrieval, not after model generation.
- Uploaded documents are evidence, not instructions. Prompt-injection strings inside evidence must not alter system policy or tool permissions.
- Action tools accept typed parameters and enforce authorization outside the model.
- Consequential actions remain approval-gated.
- Log model/provider/version and graph/ruleset versions internally without exposing provider internals to customers.

## 10. Definition of success

The system is successful when an operator can ask a hard operational question and AGRO-AI can answer:

1. what is known;
2. how it is known;
3. what is calculated;
4. what is still uncertain;
5. which sources disagree;
6. what action is justified now;
7. what requires approval;
8. what new evidence would change the decision;
9. how the action will be verified;
10. what actually happened afterward.

The long-term category is not “AI chat for agriculture.” It is **verified operating intelligence for agriculture**.

## 11. Implemented safety baseline (August 2026)

The `feat/intelligence-graph-gpt56` production upgrade now includes:

- a tenant/workspace/field-aware evidence graph with observed, derived,
  hypothesis, unknown, and conflict separation;
- duplicate and wrong-field evidence exclusion;
- GPT-5.6 Responses API structured-output integration with `store=false`, model
  routing, evidence-as-untrusted-data boundaries, and deterministic postvalidation;
- a versioned, fail-closed scientific-tool registry;
- retirement of legacy operational irrigation heuristics and isolation of the
  preview calibration pack;
- source-specific flow/recent-irrigation validation without hidden freshness,
  variance, or credit thresholds;
- approval, citation, numeric provenance, verification, and no-side-effect
  enforcement;
- deterministic evaluation metrics and 93 named adversarial cases.

The existing `DecisionRun` and `ExecutionVerification` persistence remains the
canonical lifecycle store. A future schema migration should generalize it beyond
irrigation and add immutable snapshots for evidence graph, model/provider,
prompt/policy, tool calls, approval state, and verification state. Do not create
a second parallel decision-memory architecture.

Known follow-up before broad autonomous-assistance claims: field-state snapshots
are still assembled per request rather than persisted as a canonical time-aware
state object; lifecycle verification is irrigation-specific; expert-labelled
calibration and outcome datasets are not yet available. These limitations do
not reopen the removed legacy heuristic path.
