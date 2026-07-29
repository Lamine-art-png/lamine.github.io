import { useEffect, useMemo, useState, type ReactNode } from "react";
import { CheckCircle2, Copy, MessageCircle, RefreshCw, ShieldCheck, Smartphone, Users } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;

type ChannelStatus = {
  enabled?: boolean;
  webhook_url?: string;
  signature_verification_configured?: boolean;
  challenge_verification_configured?: boolean;
  graph_api_version_configured?: boolean;
  connections?: AnyRecord[];
  contacts?: number;
  queued_events?: number;
  queued_outbound?: number;
};

const inputStyle = {
  background: "#FFFDF8",
  border: `1px solid ${BORDER}`,
  color: TEXT,
};

function rows(value: unknown): AnyRecord[] {
  return Array.isArray(value) ? value as AnyRecord[] : [];
}

function messageOf(error: unknown) {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function memberId(member: AnyRecord) {
  return String(member.user_id || member.user?.id || member.id || "");
}

function memberLabel(member: AnyRecord) {
  const user = member.user && typeof member.user === "object" ? member.user : member;
  return String(user.name || user.email || member.email || memberId(member) || "Team member");
}

export function WhatsAppFieldChannel() {
  const { currentWorkspace } = useAuth();
  const [status, setStatus] = useState<ChannelStatus | null>(null);
  const [contacts, setContacts] = useState<AnyRecord[]>([]);
  const [events, setEvents] = useState<AnyRecord[]>([]);
  const [members, setMembers] = useState<AnyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const [connectionForm, setConnectionForm] = useState({
    display_name: "WhatsApp Field Intelligence",
    phone_number_id: "",
    waba_id: "",
    access_token: "",
    confirmation_mode: "receipt",
  });
  const [contactForm, setContactForm] = useState({
    connection_id: "",
    wa_id: "",
    user_id: "",
    role: "operator",
    locale: "en",
    consent_confirmed: false,
    field_name: "",
    block_name: "",
    crop: "",
  });

  const connections = rows(status?.connections);
  const selectedConnectionId = contactForm.connection_id || String(connections[0]?.id || "");
  const readiness = useMemo(() => [
    { label: "Channel enabled", ready: Boolean(status?.enabled) },
    { label: "Webhook signature secret", ready: Boolean(status?.signature_verification_configured) },
    { label: "Webhook verification token", ready: Boolean(status?.challenge_verification_configured) },
    { label: "Pinned Graph API version", ready: Boolean(status?.graph_api_version_configured) },
  ], [status]);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [channel, contactResult, eventResult, teamResult] = await Promise.all([
        apiClient.get("/v1/field-intelligence/whatsapp/status") as Promise<ChannelStatus>,
        apiClient.get("/v1/field-intelligence/whatsapp/contacts?limit=200") as Promise<AnyRecord>,
        apiClient.get("/v1/field-intelligence/whatsapp/events?limit=100") as Promise<AnyRecord>,
        apiClient.team.members() as Promise<AnyRecord>,
      ]);
      setStatus(channel);
      setContacts(rows(contactResult.contacts));
      setEvents(rows(eventResult.events));
      setMembers(rows(teamResult.members || teamResult.team || teamResult));
      const firstConnection = String(rows(channel.connections)[0]?.id || "");
      setContactForm((value) => ({ ...value, connection_id: value.connection_id || firstConnection }));
    } catch (requestError) {
      setError(messageOf(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  async function connectChannel(event: React.FormEvent) {
    event.preventDefault();
    setBusy("connect"); setError(""); setNotice("");
    try {
      const result = await apiClient.post("/v1/field-intelligence/whatsapp/connect", {
        ...connectionForm,
        workspace_id: currentWorkspace?.id || null,
        activate: true,
      }) as AnyRecord;
      setConnectionForm((value) => ({ ...value, access_token: "" }));
      setNotice(result.status === "connected"
        ? "Meta validated the business number. The channel is active."
        : "The channel configuration was saved.");
      await load();
    } catch (requestError) {
      setConnectionForm((value) => ({ ...value, access_token: "" }));
      setError(messageOf(requestError));
      await load();
    } finally {
      setBusy("");
    }
  }

  async function testConnection(connectionId: string) {
    setBusy(`test:${connectionId}`); setError(""); setNotice("");
    try {
      await apiClient.post(`/v1/field-intelligence/whatsapp/connections/${encodeURIComponent(connectionId)}/test`, {});
      setNotice("Meta connection test passed.");
      await load();
    } catch (requestError) { setError(messageOf(requestError)); }
    finally { setBusy(""); }
  }

  async function disconnect(connectionId: string) {
    setBusy(`disconnect:${connectionId}`); setError(""); setNotice("");
    try {
      await apiClient.remove(`/v1/field-intelligence/whatsapp/connections/${encodeURIComponent(connectionId)}`);
      setNotice("The channel is disabled and its stored Meta credential has been revoked.");
      await load();
    } catch (requestError) { setError(messageOf(requestError)); }
    finally { setBusy(""); }
  }

  async function bindContact(event: React.FormEvent) {
    event.preventDefault();
    setBusy("bind"); setError(""); setNotice("");
    try {
      const context = Object.fromEntries(Object.entries({
        field_name: contactForm.field_name,
        block_name: contactForm.block_name,
        crop: contactForm.crop,
      }).filter(([, value]) => value.trim()));
      await apiClient.post("/v1/field-intelligence/whatsapp/contacts", {
        connection_id: selectedConnectionId,
        wa_id: contactForm.wa_id,
        user_id: contactForm.user_id,
        workspace_id: currentWorkspace?.id || null,
        role: contactForm.role,
        locale: contactForm.locale,
        consent_confirmed: contactForm.consent_confirmed,
        context,
      });
      setContactForm((value) => ({ ...value, wa_id: "", field_name: "", block_name: "", crop: "", consent_confirmed: false }));
      setNotice("The WhatsApp number is bound to a verified portal member.");
      await load();
    } catch (requestError) { setError(messageOf(requestError)); }
    finally { setBusy(""); }
  }

  async function revokeContact(bindingId: string) {
    setBusy(`revoke:${bindingId}`); setError(""); setNotice("");
    try {
      await apiClient.remove(`/v1/field-intelligence/whatsapp/contacts/${encodeURIComponent(bindingId)}`);
      setNotice("WhatsApp access and consent are revoked for that number.");
      await load();
    } catch (requestError) { setError(messageOf(requestError)); }
    finally { setBusy(""); }
  }

  async function copyWebhook() {
    if (!status?.webhook_url) return;
    try {
      await navigator.clipboard.writeText(status.webhook_url);
      setNotice("Webhook URL copied.");
    } catch { setError("The browser could not copy the webhook URL."); }
  }

  return <div className="min-h-screen" style={{ background: BG }}>
    <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div>
          <div className="mb-3 flex flex-wrap items-center gap-2"><StatusBadge label="Field Intelligence channel" tone="good" /><StatusBadge label="Official Meta Cloud API" /></div>
          <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>WhatsApp Field Intelligence</h1>
          <p className="mt-2 max-w-3xl text-[14px] leading-7" style={{ color: MUTED }}>Capture voice notes, photographs, documents, locations, and field updates in WhatsApp. AGRO-AI converts them into governed Enterprise Portal records, processing jobs, evidence, and verified follow-through.</p>
        </div>
        <div className="flex gap-2"><PortalButton variant="secondary" onClick={() => window.location.assign("/integrations")}>All connectors</PortalButton><PortalButton variant="secondary" onClick={load} disabled={loading}><RefreshCw className="mr-2 inline h-4 w-4" />Refresh</PortalButton></div>
      </div>
    </header>

    <main className="space-y-6 px-8 py-6" style={{ maxWidth: 1360 }}>
      {error ? <InlineState title={error} /> : null}
      {notice ? <InlineState title={notice} /> : null}
      {loading && !status ? <InlineState title="Loading WhatsApp channel controls…" /> : null}

      <section className="grid gap-4 md:grid-cols-4">
        <Metric icon={<MessageCircle className="h-4 w-4" />} label="Connections" value={String(connections.length)} />
        <Metric icon={<Users className="h-4 w-4" />} label="Authorized numbers" value={String(status?.contacts || 0)} />
        <Metric icon={<Smartphone className="h-4 w-4" />} label="Inbound queue" value={String(status?.queued_events || 0)} />
        <Metric icon={<ShieldCheck className="h-4 w-4" />} label="Outbound queue" value={String(status?.queued_outbound || 0)} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel title="Deployment readiness" subtitle="These values are controlled by the API deployment, not the browser.">
          <div className="space-y-2">{readiness.map((item) => <div key={item.label} className="flex items-center justify-between rounded-xl px-3 py-3" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><span className="text-[12px]" style={{ color: TEXT }}>{item.label}</span><StatusBadge label={item.ready ? "ready" : "required"} tone={item.ready ? "good" : "warn"} /></div>)}</div>
          <div className="mt-4 rounded-xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>Meta callback URL</div><div className="mt-2 flex items-center gap-2"><code className="min-w-0 flex-1 break-all text-[11px]" style={{ color: TEXT }}>{status?.webhook_url || "Not available"}</code><button type="button" onClick={copyWebhook} className="rounded-lg p-2" style={{ border: `1px solid ${BORDER}`, color: TEXT }} aria-label="Copy webhook URL"><Copy className="h-4 w-4" /></button></div></div>
        </Panel>

        <Panel title="Connect a Meta business number" subtitle="The access token is sent once to the API, encrypted in the connector vault, and never returned to the portal.">
          <form onSubmit={connectChannel} className="grid gap-3 md:grid-cols-2">
            <Field label="Connection name"><input required value={connectionForm.display_name} onChange={(event) => setConnectionForm({ ...connectionForm, display_name: event.target.value })} className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle} /></Field>
            <Field label="Confirmation mode"><select value={connectionForm.confirmation_mode} onChange={(event) => setConnectionForm({ ...connectionForm, confirmation_mode: event.target.value })} className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle}><option value="receipt">Send capture receipts</option><option value="silent">Silent capture</option></select></Field>
            <Field label="Phone number ID"><input required inputMode="numeric" value={connectionForm.phone_number_id} onChange={(event) => setConnectionForm({ ...connectionForm, phone_number_id: event.target.value.replace(/\D/g, "") })} placeholder="Meta phone-number ID" className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle} /></Field>
            <Field label="WhatsApp Business Account ID"><input required inputMode="numeric" value={connectionForm.waba_id} onChange={(event) => setConnectionForm({ ...connectionForm, waba_id: event.target.value.replace(/\D/g, "") })} placeholder="WABA ID" className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle} /></Field>
            <div className="md:col-span-2"><Field label="Permanent system-user access token"><input required type="password" autoComplete="new-password" value={connectionForm.access_token} onChange={(event) => setConnectionForm({ ...connectionForm, access_token: event.target.value })} placeholder="Token is cleared from this form after submission" className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle} /></Field></div>
            <div className="md:col-span-2"><PortalButton disabled={busy === "connect"}>{busy === "connect" ? "Validating with Meta…" : "Encrypt, validate, and activate"}</PortalButton></div>
          </form>
        </Panel>
      </section>

      <Panel title="Business-number connections" subtitle="Connection health is tested against Meta; disconnecting revokes AGRO-AI's local credential immediately.">
        {connections.length ? <div className="grid gap-3 lg:grid-cols-2">{connections.map((connection) => <article key={connection.id} className="rounded-2xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="flex items-start justify-between gap-3"><div><h3 className="text-[14px] font-semibold" style={{ color: TEXT }}>{connection.display_name || "WhatsApp Field Intelligence"}</h3><p className="mt-1 text-[11px]" style={{ color: MUTED }}>Phone ID {connection.phone_number_id || "—"} · WABA {connection.waba_id || "—"}</p></div><StatusBadge label={String(connection.status || "configured")} tone={connection.status === "active" ? "good" : connection.status === "error" ? "warn" : "neutral"} /></div>{connection.last_error ? <p className="mt-3 text-[11px] leading-5" style={{ color: "#9A3412" }}>{connection.last_error}</p> : null}<div className="mt-4 flex gap-2"><PortalButton variant="secondary" onClick={() => testConnection(String(connection.id))} disabled={busy === `test:${connection.id}`}>{busy === `test:${connection.id}` ? "Testing…" : "Test"}</PortalButton><PortalButton variant="secondary" onClick={() => disconnect(String(connection.id))} disabled={busy === `disconnect:${connection.id}`}>{busy === `disconnect:${connection.id}` ? "Disconnecting…" : "Disconnect"}</PortalButton></div></article>)}</div> : <Empty>No Meta business number is connected yet.</Empty>}
      </Panel>

      <section className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel title="Authorize a field worker" subtitle="Every number is bound to a verified portal member, organization, workspace, role, consent state, and optional field context.">
          <form onSubmit={bindContact} className="grid gap-3 md:grid-cols-2">
            <Field label="Business-number connection"><select required value={selectedConnectionId} onChange={(event) => setContactForm({ ...contactForm, connection_id: event.target.value })} className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle}><option value="">Choose connection</option>{connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.display_name || connection.phone_number_id}</option>)}</select></Field>
            <Field label="Portal member"><select required value={contactForm.user_id} onChange={(event) => setContactForm({ ...contactForm, user_id: event.target.value })} className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle}><option value="">Choose verified member</option>{members.map((member) => <option key={memberId(member)} value={memberId(member)}>{memberLabel(member)}</option>)}</select></Field>
            <Field label="WhatsApp number"><input required inputMode="tel" value={contactForm.wa_id} onChange={(event) => setContactForm({ ...contactForm, wa_id: event.target.value.replace(/\D/g, "") })} placeholder="Country code + number, digits only" className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle} /></Field>
            <Field label="Role"><select value={contactForm.role} onChange={(event) => setContactForm({ ...contactForm, role: event.target.value })} className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle}><option value="operator">Operator</option><option value="manager">Manager</option><option value="advisor">Advisor</option></select></Field>
            <Field label="Language"><input value={contactForm.locale} onChange={(event) => setContactForm({ ...contactForm, locale: event.target.value })} placeholder="en, es, fr…" className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle} /></Field>
            <Field label="Field context"><input value={contactForm.field_name} onChange={(event) => setContactForm({ ...contactForm, field_name: event.target.value })} placeholder="North Ranch" className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle} /></Field>
            <Field label="Block context"><input value={contactForm.block_name} onChange={(event) => setContactForm({ ...contactForm, block_name: event.target.value })} placeholder="Block A" className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle} /></Field>
            <Field label="Crop context"><input value={contactForm.crop} onChange={(event) => setContactForm({ ...contactForm, crop: event.target.value })} placeholder="Almonds" className="h-11 w-full rounded-xl px-3 text-[13px] outline-none" style={inputStyle} /></Field>
            <label className="md:col-span-2 flex items-start gap-3 rounded-xl p-3 text-[12px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}><input type="checkbox" checked={contactForm.consent_confirmed} onChange={(event) => setContactForm({ ...contactForm, consent_confirmed: event.target.checked })} className="mt-0.5" /><span><strong>Consent already documented.</strong> Leave unchecked to create an invitation; the worker must send START before capture becomes active.</span></label>
            <div className="md:col-span-2"><PortalButton disabled={busy === "bind" || !connections.length}>{busy === "bind" ? "Authorizing…" : "Bind verified worker"}</PortalButton></div>
          </form>
        </Panel>

        <Panel title="Authorized numbers" subtitle="Raw phone numbers are encrypted and never returned after setup.">
          {contacts.length ? <div className="space-y-3">{contacts.map((contact) => <article key={contact.id} className="rounded-xl p-4" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="flex items-start justify-between gap-3"><div><div className="text-[14px] font-semibold" style={{ color: TEXT }}>{contact.masked_wa_id}</div><div className="mt-1 text-[11px]" style={{ color: MUTED }}>{contact.role} · {contact.locale} · {contact.context?.field_name || "No field context"}</div></div><div className="flex gap-2"><StatusBadge label={String(contact.status)} tone={contact.status === "active" ? "good" : "warn"} /><StatusBadge label={String(contact.consent_status)} tone={contact.consent_status === "granted" ? "good" : "warn"} /></div></div><div className="mt-3 flex items-center justify-between"><span className="text-[10px]" style={{ color: MUTED }}>Last inbound {contact.last_inbound_at ? new Date(contact.last_inbound_at).toLocaleString() : "—"}</span><button type="button" onClick={() => revokeContact(String(contact.id))} disabled={busy === `revoke:${contact.id}`} className="text-[11px] font-semibold" style={{ color: "#9A3412" }}>{busy === `revoke:${contact.id}` ? "Revoking…" : "Revoke"}</button></div></article>)}</div> : <Empty>No field-worker numbers have been authorized.</Empty>}
        </Panel>
      </section>

      <Panel title="Recent channel events" subtitle="The portal shows redacted operational metadata only. Original sender identities are not exposed.">
        {events.length ? <div className="overflow-x-auto"><table className="w-full min-w-[760px] border-collapse text-left"><thead><tr>{["Time", "Type", "State", "Message", "Capture", "Attempts"].map((label) => <th key={label} className="border-b px-3 py-3 text-[10px] font-semibold uppercase tracking-widest" style={{ borderColor: BORDER, color: MUTED }}>{label}</th>)}</tr></thead><tbody>{events.map((event) => <tr key={event.id}><td className="border-b px-3 py-3 text-[11px]" style={{ borderColor: BORDER, color: MUTED }}>{event.occurred_at ? new Date(event.occurred_at).toLocaleString() : "—"}</td><td className="border-b px-3 py-3 text-[12px]" style={{ borderColor: BORDER, color: TEXT }}>{event.event_type} / {event.message_type || event.delivery_status || "—"}</td><td className="border-b px-3 py-3" style={{ borderColor: BORDER }}><StatusBadge label={String(event.status)} tone={event.status === "completed" ? "good" : event.status === "failed" || event.status === "quarantined" ? "warn" : "neutral"} /></td><td className="border-b px-3 py-3 text-[11px]" style={{ borderColor: BORDER, color: MUTED }}>{event.masked_message_id || "—"}</td><td className="border-b px-3 py-3 text-[11px]" style={{ borderColor: BORDER, color: MUTED }}>{event.capture_session_id ? "created" : "—"}</td><td className="border-b px-3 py-3 text-[11px]" style={{ borderColor: BORDER, color: MUTED }}>{event.attempt_count || 0}</td></tr>)}</tbody></table></div> : <Empty>No WhatsApp events have been received.</Empty>}
      </Panel>

      <section className="rounded-2xl p-5" style={{ background: "#EFF8F2", border: "1px solid #B8D8C1" }}><div className="flex items-start gap-3"><CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" style={{ color: "#16533C" }} /><div><h3 className="text-[13px] font-semibold" style={{ color: TEXT }}>System-of-record boundary</h3><p className="mt-1 text-[12px] leading-6" style={{ color: MUTED }}>WhatsApp is an authenticated capture and command channel. The Enterprise Portal remains the canonical record for review, assignments, recommendations, evidence, approvals, audit history, and verified closure.</p></div></div></section>
    </main>
  </div>;
}

function Panel({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return <section className="rounded-2xl p-5" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="mb-4"><h2 className="text-[15px] font-semibold" style={{ color: TEXT }}>{title}</h2>{subtitle ? <p className="mt-1 text-[11px] leading-5" style={{ color: MUTED }}>{subtitle}</p> : null}</div>{children}</section>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block"><span className="mb-1.5 block text-[11px] font-semibold" style={{ color: MUTED }}>{label}</span>{children}</label>;
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="mb-3 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: MUTED }}>{icon}{label}</div><div className="text-[28px] font-semibold" style={{ color: TEXT }}>{value}</div></div>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl px-4 py-6 text-center text-[12px]" style={{ background: SURFACE, border: `1px dashed ${BORDER}`, color: MUTED }}>{children}</div>;
}
