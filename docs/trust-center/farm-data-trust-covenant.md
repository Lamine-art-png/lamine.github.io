# AGRO-AI Farm Data Trust Covenant

**Status:** PUBLIC-FACING DRAFT — VERIFY EVERY COMMITMENT BEFORE PUBLICATION  
**Purpose:** A plain-language commitment for agricultural enterprises, growers, operators, advisors, agencies, OEMs, and data partners. This Covenant supplements, and does not replace, applicable contracts, privacy notices, or DPAs.

## Your operation should not have to trade control for intelligence.

Agricultural data can reveal where an operation works, what it grows, how equipment performs, how water is used, what happened in a field, what a team plans next, and how a business is managed. AGRO-AI therefore treats customer operational data as a protected business asset, whether or not a privacy law classifies it as personal data.

Subject to the applicable agreement and the verified production controls behind these commitments, AGRO-AI adopts the following principles.

## 1. Customer control comes first

Customers retain all right, title, and interest they have in data they provide to AGRO-AI or authorize AGRO-AI to retrieve ("Customer Data"). AGRO-AI receives only the rights needed to provide, secure, support, and operate the authorized services, plus any other use the customer has separately and explicitly authorized.

AGRO-AI does not acquire ownership of a customer's farm merely because data passes through AGRO-AI systems, and connecting a data source does not by itself grant unrestricted reuse rights.

## 2. Purpose must be clear

AGRO-AI should collect and use Customer Data only for disclosed, authorized purposes. New materially different uses require an appropriate legal basis and, where the applicable agreement or law requires it, customer notice or authorization.

## 3. No sale of Customer Operational Data

**Proposed commitment — publication requires operational and counsel verification:** AGRO-AI will not sell or rent Customer Operational Data, and will not use it for third-party targeted advertising.

## 4. No hidden shared-model training

**Proposed commitment — publication requires model/provider verification:** Customer Data will not be used to train a shared or foundation model for other customers by default. Any future customer-data contribution to a shared training program must be separately described and based on explicit, granular customer authorization where required.

A customer should be able to receive AGRO-AI intelligence without silently contributing its raw farm records to a cross-customer training pool.

## 5. Tenant boundaries before intelligence

Customer authorization and tenant/workspace boundaries should be enforced before data is retrieved for an intelligence request, not after a model has generated an answer. Credentials, API keys, and connector secrets must not be placed into model context.

## 6. Restricted Operational Data gets heightened protection

AGRO-AI treats the following as Restricted Operational Data unless a customer intentionally makes it public: precise field boundaries and geolocation; farm financial and commercial records; yield and production records; irrigation and controller data; equipment telemetry; non-public imagery; sensitive agronomic records; credentials and integration secrets; and comparable data that can reveal sensitive operating conditions.

Restricted Operational Data should receive least-privilege access, tenant scoping, heightened logging, controlled vendor access, and purpose-limited handling.

## 7. Connections remain customer-authorized

Third-party data connections should be initiated or authorized by the customer or an authorized administrator. Scopes should be limited to what the integration needs. Revoking a connection should stop future collection through that authorization, subject to provider behavior and lawful retention of data already received.

## 8. Customers can take their data with them

AGRO-AI should provide a practical way for customers to retrieve eligible Customer Data in a usable, commonly machine-readable form, subject to security, third-party rights, system constraints, and the applicable agreement.

## 9. Deletion must be real and explained

Customers should have a defined process to request deletion or return of eligible Customer Data. AGRO-AI must explain material exceptions, including legal holds, security records, financial records, and backup-retention windows. Public deletion claims must match production behavior.

## 10. Partners and subprocessors are visible

AGRO-AI should maintain a current registry of material subprocessors that handle covered customer or personal data, explaining their role and, where reasonably available and relevant, processing region. Material changes should follow the notice process in the applicable contract or DPA.

## 11. Aggregation and de-identification require safeguards

If AGRO-AI creates aggregated or de-identified datasets, the method should be designed to prevent reasonable re-identification of a single customer or operation. AGRO-AI should disclose material uses of such datasets and any customer choices that apply.

AGRO-AI should not attempt to re-identify data that it has committed to maintain as de-identified, except for legitimate security testing or as required by law and subject to appropriate controls.

## 12. Provenance matters

AGRO-AI should preserve meaningful distinctions among source data, reported observations, measured data, estimates, derived data, and model-generated outputs where those distinctions matter to the workflow. Intelligence should not erase where evidence came from.

## 13. People remain in control of consequential action

High-consequence agronomic, compliance, financial, or physical-execution workflows should include appropriate authorization, confidence, evidence, and human-review controls. AGRO-AI should not represent uncertain model output as verified fact.

## 14. Security is an operating discipline

AGRO-AI should maintain risk-appropriate technical and organizational safeguards, including access control, credential protection, logging, incident response, vulnerability management, change control, backups/recovery, and workforce/vendor confidentiality measures appropriate to the services in use.

Security claims must be evidence-backed. AGRO-AI will not claim a certification or independent audit that it has not earned.

## 15. Government and legal requests are handled narrowly

Where legally permitted, AGRO-AI should require valid legal process, review requests for scope and authority, disclose only what is legally required, and notify the affected customer when permitted by law and contract.

## 16. Changes should not be hidden

Material changes to customer-data commitments should be versioned, dated, summarized, and communicated through the process required by the applicable agreement or law.

## 17. Trust should be auditable

AGRO-AI should maintain an internal Trust Claims Register mapping public statements to controls, evidence, owners, and review dates. A public claim that can no longer be supported should be corrected rather than quietly left in place.

---

## Plain-language summary proposed for the Trust Center

**Your data. Your operation. Your control.**

AGRO-AI is being designed around a simple rule: agricultural intelligence should not require surrendering control of the data behind your operation. We limit use to authorized purposes, separate tenants before intelligence is generated, make material data partners visible, support portability and deletion, and do not hide how customer data interacts with AI.

**Before publication:** Legal, security, infrastructure, and engineering owners must approve every statement above against current production behavior and contracts.
