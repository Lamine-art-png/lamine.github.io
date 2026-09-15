# AGRO-AI Trust Center — Website Copy & Information Architecture

**Status:** DRAFT FOR WEBSITE IMPLEMENTATION  
**Rule:** Public claims marked `VERIFY` must not ship until the Trust Claims Register has evidence and an owner.

## Recommended route

`/trust`

Footer and enterprise-navigation links:

**Trust Center · Privacy · Farm Data Covenant · AI Data Use · Security · Subprocessors · DPA**

## Hero

**Eyebrow:** Trust & Data Governance

# Agricultural intelligence without surrendering control of your operation.

AGRO-AI connects sensitive agricultural systems, field evidence, machine records, water data, files, and enterprise workflows. We treat trust as part of the product architecture: clear authorization, tenant boundaries, data-use transparency, provenance, human control, and evidence-backed security claims.

**Primary CTA:** Review the Farm Data Trust Covenant  
**Secondary CTA:** Enterprise security review

Suggested trust strip:

**Customer-authorized connections · Tenant-scoped access · Provenance & audit trails · Human review gates · Transparent data-use policies**

These statements may ship only to the extent they are already evidenced across the relevant product scope.

## Section: The operating principle

### Your operation should not have to trade control for intelligence.

Farm data can reveal far more than an email address. Field boundaries, precise location, yield, irrigation behavior, equipment telemetry, imagery, agronomic records, and commercial information can expose how an agricultural business operates.

That is why AGRO-AI's governance model is designed to protect both personal data and sensitive operational data.

## Section: The Farm Data Trust Covenant

### A plain-language commitment built for agriculture.

The Covenant explains how AGRO-AI approaches customer control, authorized use, AI/model data use, tenant boundaries, portability, deletion, data partners, de-identification, provenance, consequential actions, and changes to our practices.

Cards:

**Customer control**  
Connecting data does not give AGRO-AI unrestricted rights to reuse it.

**Purpose limitation**  
Data use should remain tied to disclosed and authorized purposes.

**AI transparency**  
We explain how customer data interacts with inference, evaluation, and model training.

**Portability & deletion**  
Customer data should not become a trap. Export and deletion behavior should be practical and clearly documented.

**Visible data partners**  
Material subprocessors that handle covered customer data should be identifiable and governed.

**Evidence-backed trust**  
We do not claim certifications, residency, retention, or security controls that we cannot substantiate.

## Section: AI & customer data

# AI use should be explicit, scoped, and accountable.

AGRO-AI distinguishes between model inference, customer-specific retrieval/configuration, service evaluation, and model training. Those are different activities and should not be hidden behind a generic statement that "AI uses data."

**VERIFY before publication:**

> Customer Data is not used by default to train a shared AGRO-AI or third-party foundation model for unrelated customers.

Only publish the sentence above after every production model/provider path and contract has been verified.

Current architecture principles that can be surfaced after scope verification:

- authorization and tenant scope before retrieval;
- credentials and connector secrets excluded from normal model context;
- consequential actions remain approval-gated;
- source evidence, uncertainty, and provenance are preserved where the workflow requires them.

Link: **Read the AI & Model Data Use Policy**

## Section: Customer data controls

Recommended matrix:

| Control | What it means | Status surface |
| --- | --- | --- |
| Authorized connectors | Connections are initiated or authorized by permitted users | Document supported connector authorization patterns |
| Scoped access | Data access follows organization/workspace permissions | Publish product scope after control test |
| Export | Eligible data can be retrieved in usable formats | Publish supported formats and request path |
| Deletion | Defined deletion/return workflow with disclosed exceptions | Publish actual backup/legal-hold behavior |
| Access revocation | Connector/user access can be revoked | Publish effect and timing by integration |
| Auditability | Important actions and evidence can be traced | Publish exact log coverage/retention |

## Section: Security

# Security claims should come with evidence.

AGRO-AI's security program should cover access control, authentication and credentials, tenant isolation, encryption, logging, vulnerability management, change management, backups and recovery, incident response, vendor risk, and workforce confidentiality.

Do not use generic badge walls. Show an accurate status table instead:

| Area | Public status approach |
| --- | --- |
| Encryption in transit | `VERIFY exact protocols/scope` |
| Encryption at rest | `VERIFY systems and exceptions` |
| Tenant isolation | `VERIFY by product/data path` |
| Audit logging | `VERIFY events and retention` |
| Backup/recovery | `VERIFY RPO/RTO and tested scope` |
| Vulnerability management | `VERIFY scanning/patch process` |
| Penetration testing | Publish only after independent test, with date/scope |
| SOC 2 | Say "Not certified" until report is issued; later state exact type/period |
| ISO 27001/27701 | Say "Not certified" until certification is issued |

## Section: Data lifecycle

### Know where data goes—and what happens next.

Present the lifecycle visually:

**Authorize → collect → classify → store → retrieve → analyze → derive → share/subprocess → retain → export/return → delete**

For each stage, the Trust Center should link to the relevant customer control or policy.

## Section: Subprocessors

# Know who helps us operate the service.

Publish a searchable/table registry with:

- provider;
- service/purpose;
- categories of covered data;
- processing/storage region where relevant and verified;
- product scope;
- date added/updated;
- link to vendor privacy/security information where useful.

Add a subprocessor change-notification mechanism only after the operational process exists.

## Section: Global data responsibility

AGRO-AI operates across agricultural markets with different legal frameworks. The Trust Center should explain that legal obligations depend on context while the underlying governance standard applies broadly to sensitive operational data.

Suggested references after counsel review:

- applicable U.S. state privacy requirements;
- GDPR where applicable;
- Brazil's LGPD and ANPD rules where applicable;
- EU Data Act obligations where AGRO-AI's role or connected-product data flows bring them into scope.

Avoid the blanket badge: **"GDPR/LGPD compliant."** Explain concrete controls and contractual mechanisms instead.

## Section: Documents

Recommended document cards:

1. Privacy Notice
2. Farm Data Trust Covenant
3. AI & Model Data Use Policy
4. Data Processing Addendum
5. Security Overview / Technical & Organizational Measures
6. Subprocessor Registry
7. Acceptable Use Policy
8. Platform/API Terms
9. Data Request / Privacy Request instructions
10. Vulnerability reporting instructions

## Section: Trust status

Publish a simple version/status panel rather than decorative compliance seals:

- Trust Center version
- Last material review date
- Privacy Notice version/effective date
- Farm Data Covenant version/effective date
- Subprocessor registry last reconciled
- Security assurance status
- Contact for privacy
- Contact for security

## Enterprise CTA

# Need to run a security or data-governance review?

Enterprise customers can request the current trust package, DPA, security architecture responses, subprocessor information, and data-flow discussion for their deployment.

**CTA:** Request enterprise trust review

Use `contact@agroai-pilot.com` until dedicated `privacy@` and `security@` aliases are operational.

## Footer microcopy

**Trust is part of the operating layer.** AGRO-AI publishes what it does with data, how AI interacts with it, which material partners process it, and what customers can control. Claims are versioned and reviewed against implementation.
