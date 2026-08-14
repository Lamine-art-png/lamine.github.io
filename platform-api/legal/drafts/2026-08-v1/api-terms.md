# DRAFT — AGRO-AI Platform API Terms

**Version:** 2026-08-v1  
**Status:** LEGAL REVIEW REQUIRED — NOT EFFECTIVE  
**Company:** AGRO-AI Inc.  

These draft terms are prepared for counsel review. They must not be published as `approved_effective` or used to activate public self-service until approved.

## 1. Agreement and authority

These Platform API Terms (the “API Terms”) govern an organization’s access to and use of the AGRO-AI Platform API, developer console, command-line interface, software development kits, documentation, sandbox, and related developer services (collectively, the “Developer Services”). The individual accepting these API Terms represents that they are authorized to bind the organization associated with the AGRO-AI account (“Customer”).

If Customer and AGRO-AI Inc. (“AGRO-AI”) have a separate signed agreement that expressly governs the same Developer Services, that signed agreement controls to the extent of a conflict.

## 2. TEST service and LIVE service are separate

AGRO-AI may provide a self-service TEST environment that uses deterministic or synthetic agricultural data and bounded developer entitlements. TEST access does not grant LIVE access, production provider credentials, access to another customer’s data, production webhook delivery, billing activation, or permission to execute physical agricultural actions.

LIVE projects, provider-backed production access, physical execution, and other higher-risk capabilities may require separate technical, commercial, security, and approval gates. AGRO-AI may refuse or suspend LIVE activation even when TEST access is available.

Customer must not use TEST outputs as instructions to control irrigation, machinery, chemical application, planting, harvesting, food safety, worker safety, or any other physical operation. TEST is for software evaluation and integration development.

## 3. Accounts and credentials

Customer must provide accurate registration information, maintain control of its account, and promptly update material changes. Customer is responsible for users and service accounts operating under its organization.

API keys, human CLI sessions, webhook secrets, OAuth credentials, and other credentials are confidential. Customer must use reasonable safeguards, limit scopes and permissions, rotate credentials when appropriate, and promptly revoke credentials that may have been exposed.

Customer must not sell, transfer, publish, or knowingly share credentials outside its authorized organization or approved contractors. Customer remains responsible for activity performed with credentials issued to its organization except to the extent caused by AGRO-AI’s breach of its own security obligations.

## 4. Authorized use

Subject to these API Terms and the Acceptable Use Policy, AGRO-AI grants Customer a limited, revocable, non-exclusive, non-transferable right to use the Developer Services to develop, test, and operate authorized integrations with AGRO-AI.

Customer may not:

- bypass technical restrictions, quotas, rate limits, organization boundaries, environment boundaries, or access-control checks;
- access or attempt to access another customer’s resources;
- reverse engineer security controls or exploit vulnerabilities except through an AGRO-AI-authorized security testing program;
- use the Developer Services to violate law, third-party rights, sanctions, export controls, or contractual restrictions;
- represent TEST functionality as approved for production or physical execution;
- use credentials or data obtained through unauthorized means;
- interfere with service availability or integrity.

Additional prohibited conduct is described in the Acceptable Use Policy.

## 5. Customer data and permitted processing

“Customer Data” means information Customer or its authorized users submit to the Developer Services or authorize AGRO-AI to retrieve from third-party systems, excluding AGRO-AI technology and aggregated or de-identified service telemetry that cannot reasonably identify Customer or an individual.

As between the parties, Customer retains its rights in Customer Data. Customer grants AGRO-AI the rights necessary to host, transmit, transform, analyze, secure, and otherwise process Customer Data to provide, maintain, protect, support, and improve the Developer Services, subject to applicable law, the Privacy Notice, and any applicable signed data-processing agreement.

Customer represents that it has the rights, permissions, notices, and lawful basis necessary to provide Customer Data and authorize the requested processing.

Customer must not place regulated data, sensitive personal information, production credentials, or real farm/customer data into a TEST environment unless AGRO-AI expressly documents that category as supported for that environment.

## 6. Agricultural and AI outputs

Developer Services may generate recommendations, forecasts, summaries, classifications, anomaly flags, or other machine-generated outputs. Outputs may be incomplete, uncertain, delayed, or incorrect. Agricultural outcomes depend on local conditions, equipment, weather, crop state, human judgment, and data quality.

Unless expressly agreed in writing for a specific LIVE workflow, outputs are decision-support information and are not a substitute for qualified agronomic, engineering, legal, safety, regulatory, or other professional judgment. Customer is responsible for reviewing outputs and for decisions or actions it takes based on them.

No TEST output authorizes a physical action.

## 7. Third-party systems and providers

Developer Services may interoperate with third-party platforms, equipment systems, data providers, or cloud services. Customer’s use of those systems remains subject to the third party’s terms and permissions. AGRO-AI is not responsible for changes, outages, data quality, or restrictions imposed by third parties outside AGRO-AI’s reasonable control.

Customer must not use the Developer Services to exceed or evade the scope of Customer’s authorization from a third-party provider.

## 8. Usage limits and changes

AGRO-AI may enforce documented technical limits, quotas, rate limits, concurrency limits, retention limits, and environment restrictions. AGRO-AI may modify TEST limits or sandbox behavior to protect the service, prevent abuse, or improve the platform.

Material changes to paid or LIVE commercial terms will be handled under the applicable commercial agreement or pricing terms. TEST access does not guarantee future availability, pricing, feature parity, or LIVE approval.

## 9. Software and intellectual property

AGRO-AI and its licensors retain all rights in the Developer Services, SDKs, documentation, models, software, interfaces, trademarks, and related technology, except for Customer Data and third-party materials.

To the extent an SDK is distributed under a separate open-source or source-available license, that license governs the licensed code. Otherwise, Customer may use AGRO-AI SDKs only with the Developer Services as permitted by these API Terms.

If Customer voluntarily provides feedback, Customer grants AGRO-AI a worldwide, perpetual, irrevocable, royalty-free right to use that feedback without restriction or obligation.

## 10. Security and responsible disclosure

Customer must use reasonable security practices appropriate to its use of the Developer Services. Customer must promptly notify AGRO-AI if it discovers credential compromise, unauthorized access, or a suspected security vulnerability affecting AGRO-AI.

Customer must not publicly disclose a vulnerability before giving AGRO-AI a reasonable opportunity to investigate and remediate it, unless applicable law protects or requires the disclosure.

## 11. Suspension and termination

AGRO-AI may suspend or restrict access where reasonably necessary to address security risk, suspected abuse, unlawful activity, material breach, nonpayment for paid services, provider restrictions, or risk to other customers or infrastructure. Where practicable and lawful, AGRO-AI will provide notice and an opportunity to cure.

Customer may stop using the Developer Services at any time. Upon termination, Customer must stop using revoked credentials and any access that is no longer authorized.

Sections that by their nature should survive termination survive, including intellectual-property, confidentiality-related obligations, disclaimers, limitations of liability, and dispute terms.

## 12. Confidentiality

Each party may receive non-public information from the other that is identified as confidential or reasonably should be understood to be confidential. The receiving party will protect such information using reasonable care and use it only for the relationship contemplated by these API Terms, except where disclosure is authorized or legally required.

Customer Data is Customer confidential information except to the extent Customer makes it public or the parties agree otherwise.

## 13. Disclaimers

THE DEVELOPER SERVICES, ESPECIALLY TEST AND BETA CAPABILITIES, ARE PROVIDED ON AN “AS IS” AND “AS AVAILABLE” BASIS TO THE MAXIMUM EXTENT PERMITTED BY LAW. AGRO-AI DISCLAIMS IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, AND ANY WARRANTY THAT TEST OUTPUTS OR THIRD-PARTY DATA WILL BE COMPLETE, ERROR-FREE, OR SUITABLE FOR PHYSICAL AGRICULTURAL DECISIONS.

Nothing in this section excludes a warranty that cannot lawfully be excluded.

## 14. Limitation of liability — counsel to confirm

**COUNSEL REVIEW REQUIRED.** The final agreement should specify an appropriate liability framework and cap, including treatment of confidentiality, data security, IP claims, gross negligence, willful misconduct, statutory rights, and any paid-service fees. No liability cap is approved in this draft.

## 15. Indemnity — counsel to confirm

**COUNSEL REVIEW REQUIRED.** The final agreement should define any Customer and AGRO-AI indemnification obligations, including third-party claims arising from Customer Data, unlawful use, infringement, or unauthorized physical actions. No indemnity allocation is approved in this draft.

## 16. Export controls and sanctions

Customer must comply with applicable export-control and sanctions laws and must not use the Developer Services where such use is prohibited. Customer represents that it is not using the Developer Services on behalf of a prohibited or sanctioned person or entity.

## 17. Changes to these API Terms

AGRO-AI may update these API Terms. If a change materially affects Customer’s rights or obligations, AGRO-AI will provide notice as required by applicable law or the applicable commercial agreement. The Platform may require reacceptance of a new effective version before continued developer access.

## 18. Governing law and disputes — counsel to confirm

**COUNSEL REVIEW REQUIRED.** The final agreement must identify governing law, venue, dispute procedure, and any arbitration/class-action provisions. Those terms are intentionally not approved in this draft.

## 19. Notices and contact

Operational and security notices may be delivered through the AGRO-AI account, Developer Console, email associated with the organization, or another agreed method.

Customer questions about these API Terms may be sent to `support@agroai-pilot.com` until counsel designates a legal-notice address.

---

**Not effective. Counsel approval and an exact approved content digest are required before production activation.**
