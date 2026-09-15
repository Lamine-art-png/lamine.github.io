# AGRO-AI Trust & Data Governance Program

**Program version:** 2026-09  
**Public Trust Center:** `https://agroai-pilot.com/trust/`  
**Publication architecture:** isolated Cloudflare route `agroai-pilot.com/trust*`

## Purpose

AGRO-AI handles agricultural operational data that can be commercially sensitive even when it is not legally classified as personal information. The Trust & Data Governance Program therefore treats privacy, farm-data governance, model data use, security, customer control, subprocessors, retention, portability, deletion, provenance, and enterprise procurement as one coordinated trust system.

The program applies across the AGRO-AI Enterprise Portal, Field Intelligence, Platform API, customer-authorized connectors, support workflows, and material infrastructure or model-provider paths.

## Public Trust Center surfaces

The public website provides the following versioned pages:

- `/trust/` — Trust Center overview
- `/trust/privacy/` — company Privacy Notice
- `/trust/data-governance/` — public Data Governance Standard
- `/trust/ai-data-use/` — AI & Model Data Use Policy
- `/trust/security/` — Security Program overview
- `/trust/subprocessors/` — Subprocessors & Integrations transparency
- `/trust/farm-data-covenant/` — Farm Data Trust Covenant

The pages are served through a dedicated Worker whose only route is `agroai-pilot.com/trust*`. The Worker does not own or intercept careers, demo booking, newsroom, Platform API, Enterprise Portal, machine API, integrations, or other marketing routes.

## Core design principles

1. **Customer control.** Customer Data is governed by customer authorization and the applicable agreement rather than treated as unrestricted AGRO-AI property.
2. **Operational data is protected even when it is not personal data.** Precise field geometry, machine telemetry, irrigation/controller records, yield, financial records, non-public imagery, and equivalent data are classified as Restricted Operational Data.
3. **Purpose limitation.** A connection or upload authorizes the requested service, not unlimited secondary use.
4. **Tenant boundaries before intelligence.** Organization/workspace authorization is enforced before retrieval and context assembly.
5. **No hidden shared-model training.** Customer Data is not used to train shared AGRO-AI or third-party foundation models for unrelated customers unless expressly authorized through an appropriate agreement or control.
6. **Secrets stay outside model context.** Connector credentials, private keys, API keys, and equivalent secrets are not ordinary model inputs.
7. **Human control for consequential workflows.** Recommendations do not automatically become permission for physical action, compliance submission, financial action, or other high-consequence execution.
8. **Portability and deletion are lifecycle controls.** Export/return and deletion behavior must account for active stores, derived indexes, logs, media, backups, processors, and lawful retention.
9. **Providers are governed.** Infrastructure vendors, subprocessors, and customer-authorized integrations are distinguished and reviewed according to role and risk.
10. **Trust claims require evidence.** AGRO-AI does not use certifications, zero-retention claims, residency claims, or deletion guarantees as marketing language without supporting evidence and scope.

## Internal governance artifacts

This directory contains the operational source material behind the public pages:

- `data-governance-standard.md`
- `ai-model-data-use-policy.md`
- `farm-data-trust-covenant.md`
- `privacy-notice-v2-draft.md`
- `trust-center-web-copy.md`
- `implementation-plan.md`

The internal documents are intentionally more conservative than marketing copy and identify areas requiring ongoing engineering, security, legal, or operational verification.

## Living registers required by the program

AGRO-AI should maintain:

- a Data Processing Register;
- a Data Flow Map;
- a Subprocessor & Vendor Register;
- a Retention Schedule;
- a Privileged Access Register;
- an AI / Model Register;
- a Trust Claims Register;
- an Incident Register; and
- a Rights / Customer Request Register.

## Trust Claims Register

The Trust Claims Register is the control that prevents website copy, sales responses, legal documents, procurement questionnaires, and engineering reality from drifting apart.

A material claim should record:

- exact public or contractual language;
- product and data scope;
- known exceptions;
- implemented control;
- evidence location;
- responsible owner;
- last test/review;
- next review; and
- approval status.

If a claim can no longer be supported, AGRO-AI should correct the claim rather than quietly leaving it in place.

## Assurance posture

Frameworks such as NIST, SOC 2 criteria, ISO/IEC 27001, and privacy-management standards may guide control design and readiness. AGRO-AI must not represent that it is certified, audited, or fully compliant merely because controls are mapped to a framework.

The recommended maturity sequence remains:

1. operational evidence baseline;
2. risk-driven independent security testing;
3. SOC 2 readiness where customer demand justifies it;
4. formal SOC 2 audit when the control environment is ready;
5. additional ISO/privacy assurance when business requirements justify it.

## Change control

Material trust-policy changes should update the public version/date and the internal registers that support the claim. New model providers, sensitive data categories, countries, high-risk automated decisioning, physical write-back, or material secondary uses should receive a documented data/privacy/security impact review before production activation.
