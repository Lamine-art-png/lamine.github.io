# AGRO-AI AI & Model Data Use Policy

**Status:** DRAFT — ENGINEERING, SECURITY, AND COUNSEL VERIFICATION REQUIRED  
**Purpose:** Define how customer data may and may not interact with AI and machine-learning systems.

## Principle

Using AGRO-AI intelligence should not silently turn a customer's operational records into training data for other customers.

AGRO-AI should separate four activities that are often incorrectly collapsed into one term, "AI use":

1. **Inference** — sending authorized context to a model to answer a request or perform an approved workflow.
2. **Customer-specific retrieval or configuration** — using that customer's authorized data to improve responses within that customer's scope.
3. **Service evaluation and safety** — limited, controlled use of records or derived test cases to measure quality, reliability, abuse, and security.
4. **Model training or fine-tuning** — changing model parameters or shared learned behavior using datasets.

Customers should be able to understand which of these occurs and under what authority.

## 1. Default training rule

**Proposed binding rule — do not publish until every provider and pipeline is verified:** Raw Customer Data is not used by default to train a shared AGRO-AI model, foundation model, or third-party model for the benefit of unrelated customers.

Any future shared-training program using identifiable or customer-linked Customer Data must have a documented purpose, approved data-governance review, contractual authority, and any consent/opt-in required by the customer agreement or applicable law.

## 2. Inference is not blanket reuse

Customer authorization to use a feature that requires model inference authorizes the processing necessary to provide that feature; it does not by itself authorize unrestricted secondary use, sale, advertising, or shared-model training.

## 3. Model-provider controls

For every external model provider, AGRO-AI must register and verify:

- exact product/API used;
- categories of data sent;
- provider retention behavior and configurable retention setting;
- provider training/use terms for submitted data;
- processing locations where relevant;
- subprocessor/contract terms;
- security controls;
- approved purposes;
- whether zero-data-retention or equivalent controls are available and enabled;
- deletion/export implications;
- owner and last review date.

A provider must not be described as "zero retention" unless the exact account, endpoint, and configuration qualify.

## 4. Tenant isolation before retrieval

Authorization, organization scope, and workspace/tenant filtering must be applied before retrieval and context assembly. Cross-tenant data must not be fetched and then left for a model prompt to separate.

## 5. Secrets never enter model context

Passwords, private keys, API keys, OAuth refresh tokens, connector secrets, and equivalent credentials must not be placed in model prompts or retrieval context except where a narrowly designed security workflow explicitly requires secret handling and has been separately approved.

## 6. Data minimization for context

Model context should contain only the information reasonably necessary for the authorized task. Systems should prefer scoped retrieval and structured context over bulk transmission of an entire customer's records.

## 7. Provenance and derived data

Where decision quality or auditability matters, AGRO-AI should preserve links between outputs and meaningful source evidence. Systems should distinguish source records, normalized records, derived features, model-generated conclusions, human edits, and final approved actions.

Derived data does not automatically become unrestricted AGRO-AI property merely because it was computed. Contract language must define rights in Customer Data, service telemetry, aggregated/de-identified data, feedback, and model outputs with precision.

## 8. De-identification is not a shortcut

Removing a customer name is not sufficient if field geometry, precise location, rare crop combinations, equipment identifiers, imagery, or other attributes can reasonably reveal the operation. Data used as de-identified or aggregated information must follow an approved de-identification method and re-identification risk review appropriate to the use.

## 9. Human control for consequential workflows

For workflows capable of materially affecting crop treatment, water application, compliance submissions, financial decisions, equipment operation, or comparable consequential activity, the system should implement risk-appropriate approval gates, confidence/uncertainty handling, evidence visibility, and authorization controls.

No model should obtain physical actuation authority merely because it can generate a recommendation.

## 10. Evaluation datasets

Customer-linked data used for evaluation, debugging, red-teaming, or quality analysis must have documented authority, access restrictions, retention, and purpose. Where practical, synthetic or appropriately de-identified test data should be preferred for repeatable testing.

## 11. Customer-specific learning

If AGRO-AI introduces customer-specific memory, retrieval indexes, fine-tunes, adapters, or other learning artifacts, the product and contract should explain:

- whether the artifact is isolated to that customer;
- what source data created it;
- who can access it;
- how long it persists;
- whether it can be exported or deleted;
- what happens when the customer terminates service.

## 12. New model or provider launch gate

No new model provider, training workflow, cross-customer dataset, or material AI data-use change should enter production until:

1. data categories and purposes are registered;
2. privacy/security/vendor review is complete;
3. contract and provider terms are reviewed;
4. retention and training settings are verified;
5. tenant and authorization controls are tested;
6. the Trust Claims Register is updated;
7. customer notice/authorization is handled where required.

## 13. Public transparency

The Trust Center should publish a concise AI Data Use summary that answers, in plain language:

- Is my raw data used for inference?
- Is it used to train models?
- Can other customers' requests retrieve it?
- Which external model providers can process it?
- How is model context minimized?
- Can I request deletion/export?
- How are high-consequence actions controlled?

## Current architecture evidence to validate

Existing AGRO-AI architecture documentation states an intent to keep `store=false` for OpenAI inference unless a future customer-approved policy changes it, to exclude connector credentials from model context, and to enforce tenant isolation before retrieval. Before those statements become public commitments, engineering must verify that every production path follows them and document the evidence in the Trust Claims Register.
