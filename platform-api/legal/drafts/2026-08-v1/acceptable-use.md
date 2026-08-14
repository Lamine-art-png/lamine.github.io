# DRAFT — AGRO-AI Platform API Acceptable Use Policy

**Version:** 2026-08-v1  
**Status:** LEGAL REVIEW REQUIRED — NOT EFFECTIVE

This draft is for counsel review. It is designed to protect the TEST developer environment without expanding any LIVE or physical-action capability.

## 1. General rule

You may use the AGRO-AI Developer Services only for lawful, authorized purposes consistent with the Platform API Terms, documentation, technical restrictions, and the permissions associated with your organization, project, service account, and API keys.

## 2. Security and access abuse

You must not:

- obtain or attempt to obtain unauthorized access to an account, organization, project, field, source, job, report, webhook, provider connection, billing record, credential, or other resource;
- guess, enumerate, replay, steal, share, scrape, or misuse credentials, identifiers, tokens, device codes, session data, or secrets;
- bypass authentication, authorization, organization isolation, project isolation, scopes, CIDR restrictions, quotas, rate limits, concurrency limits, feature flags, provider restrictions, or environment boundaries;
- interfere with security controls, logging, auditability, metering, provenance, or safety gates;
- intentionally submit malicious code, malware, destructive payloads, exploit traffic, denial-of-service traffic, or traffic designed to degrade the service;
- use automated security testing against production without AGRO-AI’s written authorization or an applicable published safe-harbor program.

Good-faith reporting of suspected vulnerabilities is encouraged through AGRO-AI’s designated security/support channel.

## 3. TEST environment restrictions

The public self-service TEST environment is for development and evaluation. You must not:

- treat TEST outputs as instructions for real irrigation, machinery, pesticide or chemical application, crop treatment, worker activity, food-safety action, or any other physical operation;
- attempt to enable LIVE projects, production provider credentials, physical execution, or production webhook delivery by manipulating requests or client code;
- upload real customer secrets, production credentials, highly sensitive personal information, or regulated datasets unless AGRO-AI expressly documents the category as supported for that TEST environment;
- present TEST data or synthetic sandbox results as observations from a real farm or production system.

## 4. Harmful, unlawful, or deceptive use

You must not use the Developer Services to:

- violate applicable law or regulation;
- facilitate fraud, phishing, impersonation, credential theft, extortion, or deceptive conduct;
- infringe intellectual-property, privacy, confidentiality, publicity, or other rights;
- harass, threaten, stalk, discriminate unlawfully, or facilitate violence;
- develop or operate malware, ransomware, botnets, unauthorized surveillance, or credential-harvesting systems;
- knowingly submit content or data you do not have the right to process;
- misrepresent an integration as endorsed, certified, or approved by AGRO-AI when it is not;
- misrepresent a TEST integration as a production or safety-certified system.

## 5. Data and privacy

You must respect applicable privacy and data-protection obligations. Do not use the Developer Services to collect, infer, or process personal information in a manner that is unlawful or outside the scope of your authorization.

You must not attempt to identify another customer, infer another customer’s data through timing or error behavior, or combine TEST resources with unauthorized external data to defeat tenant isolation.

## 6. Providers and third-party systems

You must not use AGRO-AI to evade a third-party provider’s contract, authentication, rate limit, license, or customer-authorization requirement. You may connect only systems and data that you are authorized to access.

Provider readiness shown in TEST does not represent permission to make production provider calls.

## 7. Excessive or abusive traffic

You must respect published technical limits and reasonable requests from AGRO-AI to reduce harmful traffic. You must not deliberately create unnecessary load, evade rate limits by rotating identities or projects, or create large numbers of accounts, projects, keys, webhooks, or requests to circumvent quotas.

## 8. Credential handling

Keep API keys, webhook secrets, CLI sessions, OAuth credentials, and provider credentials confidential. Use the smallest practical scopes. Revoke or rotate a credential promptly if you suspect exposure.

Do not embed secret credentials in public repositories, client-side browser bundles, mobile application packages, public logs, support tickets, screenshots, or shared documents.

## 9. Enforcement

AGRO-AI may investigate suspected violations and may restrict, suspend, or terminate access where reasonably necessary to protect customers, infrastructure, providers, or legal compliance. Where appropriate, AGRO-AI may preserve relevant audit records and cooperate with lawful requests.

Enforcement should be proportionate to risk, severity, recurrence, and available evidence. The final policy should be reviewed by counsel for notice, appeals, statutory obligations, and regional requirements.

## 10. Changes

AGRO-AI may update this policy. Material changes may require reacceptance when the Platform API legal catalog marks a new version as effective.

---

**Not effective. Counsel approval and an exact approved content digest are required before production activation.**
