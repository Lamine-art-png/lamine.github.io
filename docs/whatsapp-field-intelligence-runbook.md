# WhatsApp Field Intelligence — deployment and operations runbook

## Non-negotiable architecture

AGRO-AI uses the official Meta WhatsApp Business Platform Cloud API only. Do not deploy browser automation, WhatsApp Web session impersonation, unofficial SDKs that require QR login, or scraping-based group ingestion.

WhatsApp is an authenticated capture and command channel. The AGRO-AI Enterprise Portal remains the canonical system of record for observations, media, processing state, recommendations, assignments, approvals, evidence, audit history, and verified closure.

## What ships in this release

- Official Meta webhook verification and `X-Hub-Signature-256` validation.
- Fast durable webhook ingestion with event-level idempotency.
- Leased asynchronous processing through the existing Field Intelligence worker.
- Text, audio, image, video, document, sticker, and location ingestion.
- Strict Meta media-host allowlisting, streaming size limits, checksum/length validation, structural media inspection, and bounded duration probing.
- Canonical Field Intelligence capture sessions, assets, observations, processing jobs, provenance, quotas, and retention.
- Encrypted WhatsApp identities and encrypted Meta access-token custody.
- Verified portal-user, organization-membership, workspace, role, consent, and entitlement enforcement.
- START, STOP, HELP, and `/context` commands.
- Durable outbound text/template queue with service-window enforcement and delivery-state reconciliation.
- Enterprise Portal channel administration, masked worker identities, consent state, and redacted event health.

## Required Meta assets

Create or select the following in Meta Business Manager / App Dashboard:

1. A Meta business app with the WhatsApp product enabled.
2. A WhatsApp Business Account dedicated to the intended environment.
3. A business phone number for the intended environment.
4. A system user with the minimum permissions required for WhatsApp business messaging and management.
5. A long-lived or permanent system-user access token appropriate for the business app.
6. The app secret.
7. The phone-number ID and WABA ID.
8. An explicit Meta Graph API version that is currently supported by the app.

Never reuse the production Meta app, number, WABA, token, app secret, or verify token in staging.

## Required AGRO-AI environment

Apply the variables documented in `agroai_api/.env.whatsapp.example` to both the API and Field Intelligence worker.

Required before activation:

- `WHATSAPP_ENABLED=true`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_APP_SECRET`
- `WHATSAPP_GRAPH_API_VERSION`
- `WHATSAPP_GRAPH_API_BASE_URL=https://graph.facebook.com`
- A production-grade connector credential key or versioned keyring.
- Durable Field Intelligence object storage.
- A live Field Intelligence transcription provider.
- A live Field Intelligence worker.

The API and worker must run the same `GIT_SHA` and both must include Alembic revision `028_whatsapp_field_intelligence`.

## Deployment order

1. Back up the production database and verify restore procedure.
2. Deploy the exact candidate SHA to isolated staging API, worker, and portal.
3. Run `alembic upgrade head` in staging.
4. Confirm the persisted Alembic head is `028_whatsapp_field_intelligence`.
5. Keep `WHATSAPP_ENABLED=false` initially.
6. Deploy API and worker at the same SHA.
7. Set all WhatsApp environment values on both services.
8. Restart both services and verify worker heartbeat/queue health.
9. Set `WHATSAPP_ENABLED=true` in staging.
10. In Meta, configure callback URL:

   `https://<staging-api-host>/v1/whatsapp/webhook`

11. Enter the exact staging verify token and complete webhook verification.
12. Subscribe the WhatsApp Business Account to message events.
13. In the Enterprise Portal, open **Connectors → WhatsApp Field Intelligence**.
14. Enter the staging phone-number ID, WABA ID, and system-user token. AGRO-AI encrypts the token and immediately probes the phone-number resource.
15. Bind a staging worker number to a verified staging portal member.
16. Leave consent unchecked and verify that an inbound field message is quarantined.
17. Send `START`; verify consent becomes granted and the number becomes active.
18. Send text, voice, image, location, and document test cases.
19. Verify every accepted message creates one canonical capture and no duplicate record after Meta retry.
20. Verify `STOP` revokes consent and subsequent field content is quarantined.
21. Verify free-form outbound text is refused outside the customer-service window and a template message succeeds.
22. Verify media and records are visible in the Enterprise Portal with provenance surface `whatsapp`.
23. Verify no full worker phone number, Meta token, raw webhook body, or contact display name appears in logs, API responses, or audit payloads.

Only repeat the sequence in production after staging passes.

## Portal operating procedure

### Connect a business number

Only an organization owner or administrator can create, test, update, or disconnect a channel. The portal sends the system-user token once to the backend. The token is stored in the existing encrypted connector vault and is never returned.

### Bind a worker

Every worker number must map to:

- One tenant.
- One WhatsApp connection.
- One verified and active AGRO-AI user.
- One active organization membership.
- An optional workspace.
- A field role.
- A locale.
- A consent state.
- Optional field/block/crop context.

Unknown senders are never automatically enrolled.

### Consent

- `START`, `AGREE`, or `CONSENT`: grants consent only when an administrator has already bound the number to a valid member.
- `STOP`, `UNSUBSCRIBE`, `CANCEL`, `END`, or `QUIT`: revokes consent and disables capture.
- `HELP`: returns bounded channel instructions.
- `/context field=..., block=..., crop=...`: updates bounded operating context only for an active, consented binding.

Documented consent may be recorded by an administrator only when the enterprise has already obtained and retained valid consent through its approved process.

## Security controls

- Verify the webhook signature over the raw body before parsing JSON.
- Reject oversized webhook bodies.
- Do not log request bodies or authorization headers.
- Store a deterministic HMAC of normalized WhatsApp identity for lookup.
- Store the recoverable identity only as AES-GCM ciphertext with tenant/binding authenticated data.
- Return only a masked identity to the portal.
- Keep the Meta token exclusively in the connector vault.
- Do not permit a WhatsApp binding to bypass user suspension, email verification, organization verification, membership status, workspace tenancy, role, plan, quota, or Field Intelligence release gates.
- Quarantine unknown or unauthorized senders.
- Download media only from approved Meta-controlled HTTPS hosts.
- Verify media checksum and declared length where Meta provides them.
- Reuse Field Intelligence media inspection, duration caps, storage quotas, retention, and deletion.
- Require approved message templates outside the customer-service window.

## Observability

Monitor at minimum:

- Live Field Intelligence worker heartbeat and exact SHA.
- WhatsApp inbound queued/processing/failed counts.
- WhatsApp outbound queued/sending/failed counts.
- Quarantined sender volume.
- Duplicate delivery count.
- Capture-to-observation conversion rate.
- Processing failure/retry rate.
- Media rejection reasons.
- Meta delivery failures and phone-number quality state.
- Cost per accepted capture and per active worker.

Alert when:

- Worker heartbeat exceeds TTL.
- Inbound or outbound queue age exceeds the Field Intelligence stale-job threshold.
- Signature failures spike.
- Unknown phone-number IDs appear.
- Media checksum failures occur.
- Meta delivery failures increase materially.
- A channel enters `error` or `disabled` unexpectedly.

## Incident response

### Suspected token exposure

1. Disable the channel in the portal.
2. Revoke the Meta system-user token in Meta Business Manager.
3. Rotate the connector-vault key according to the existing vault rotation procedure if vault custody may be affected.
4. Issue a new least-privilege Meta token.
5. Reconnect and test the business number.
6. Review redacted channel events and security audit logs.

### Suspected app-secret exposure

1. Set `WHATSAPP_ENABLED=false` on API and worker.
2. Rotate the Meta app secret.
3. Update `WHATSAPP_APP_SECRET` on API and worker atomically.
4. Restart both services.
5. Re-enable only after signed staging verification succeeds.

### Queue or provider outage

Do not acknowledge an event as processed unless its durable event row is committed. The public webhook may continue accepting signed events while downstream Field Intelligence processing is unavailable. Leases and bounded retries handle transient failures; terminal failures remain inspectable.

### Emergency rollback

1. Set `WHATSAPP_ENABLED=false` on API and worker.
2. Disconnect affected channels in the portal and revoke Meta credentials when appropriate.
3. Keep migration 028 in place during the emergency. Do not downgrade a live database merely to disable traffic.
4. Roll API, worker, and portal back together to the last known exact SHA.
5. Preserve queued and failed event rows for incident review.

## Production acceptance gates

Production is not accepted until all are true:

- Migration 028 is applied and schema contract passes.
- API and worker run the same exact SHA.
- GitHub migration, backend, WhatsApp, release-contract, and portal jobs are green.
- Official Meta webhook verification succeeds.
- Invalid signatures fail before persistence.
- Duplicate deliveries do not create duplicate captures.
- Unknown senders cannot create evidence.
- Consent grant and revocation work.
- A suspended/deactivated portal identity cannot create new evidence.
- Text, voice, photograph, location, and document captures complete end-to-end.
- Outbound service-window and template rules behave correctly.
- No raw worker phone number or Meta secret is exposed.
- Rollback has been exercised in staging.

## Intentional first-release boundaries

- No unofficial ingestion of existing large WhatsApp groups.
- No general-purpose AI assistant on WhatsApp.
- No consequential operational action without the existing AGRO-AI approval and verification controls.
- No silent enrollment of unknown numbers.
- No storage of WhatsApp as the only operational record.
