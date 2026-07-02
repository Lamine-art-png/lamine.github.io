import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { useState } from "react";
import { Link } from "react-router";
import { CheckCircle2, LifeBuoy, Send } from "lucide-react";
import { apiClient, SupportTicketPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { useLocale } from "../hooks/useLocale";
import { BG, BORDER, GREEN, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block text-[12px] font-medium" style={{ color: MUTED }}>{label}<div className="mt-1">{children}</div></label>;
}

function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className="h-10 w-full rounded-lg px-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />;
}

function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className="h-10 w-full rounded-lg px-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />;
}

export function SupportPage() {
  const { currentWorkspace, currentOrganization, user } = useAuth();
  const { t } = useLocale();
  const [form, setForm] = useState<SupportTicketPayload>({ category: "support", subject: "", message: "", source_page: "support", workspace_id: currentWorkspace?.id, name: user?.name || "", email: user?.email || "", company: currentOrganization?.name || "" });
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const canSubmit = form.subject.trim().length >= 2 && form.message.trim().length >= 2 && status !== "sending";

  async function submit() {
    if (!canSubmit) return;
    setStatus("sending");
    setError("");
    try {
      const response = await apiClient.support.ticket({ ...form, workspace_id: currentWorkspace?.id, source_page: "support" }) as Record<string, unknown>;
      setResult(response);
      setStatus("sent");
      setForm((current) => ({ ...current, subject: "", message: "" }));
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Support request could not be sent.");
    }
  }

  return <div className="min-h-screen" style={{ background: BG }}><header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}><div className="flex flex-wrap items-start justify-between gap-5"><div><div className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest" style={{ color: GREEN }}><LifeBuoy className="h-4 w-4" /> AGRO-AI support desk</div><h1 className="mt-2 text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>{t("supportTitle")}</h1><p className="mt-2 max-w-3xl text-[14px] leading-7" style={{ color: MUTED }}>{t("supportSubtitle")}</p></div><Link to="/admin/requests"><PortalButton variant="secondary">Open request inbox</PortalButton></Link></div></header><main className="grid gap-5 px-8 py-6 lg:grid-cols-[1fr_340px]" style={{ maxWidth: 1240 }}><section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="mb-5 flex items-start justify-between gap-4"><div><h2 className="text-[20px] font-semibold" style={{ color: TEXT }}>{t("contactSupport")}</h2><p className="mt-1 text-[13px]" style={{ color: MUTED }}>This creates a tracked request for the AGRO-AI team.</p></div><PortalButton disabled={!canSubmit} onClick={submit}>{status === "sending" ? t("sending") : t("sendRequest")}</PortalButton></div>{status === "sent" ? <div className="mb-4 rounded-xl px-4 py-3 text-[13px]" style={{ background: "#F0FDF4", color: "#15803D", border: "1px solid #BBF7D0" }}><CheckCircle2 className="mr-2 inline h-4 w-4" />{t("requestReceived")}. ID: {String(result?.request_id || "tracked")}</div> : null}{error ? <div className="mb-4 rounded-xl px-4 py-3 text-[13px]" style={{ background: "#FFFBEB", color: "#92400E", border: "1px solid #FCD34D" }}>{error}</div> : null}<div className="grid gap-4 md:grid-cols-3"><Field label={t("requestType")}><Select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value as SupportTicketPayload["category"] })}><option value="support">Support</option><option value="integration">Integration</option><option value="issue">Issue</option><option value="onboarding">Onboarding</option><option value="sales">Sales</option></Select></Field><Field label="Name"><Input value={form.name || ""} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field><Field label="Email"><Input value={form.email || ""} onChange={(event) => setForm({ ...form, email: event.target.value })} /></Field></div><div className="mt-4"><Field label={t("subject")}><Input value={form.subject} onChange={(event) => setForm({ ...form, subject: event.target.value })} /></Field></div><div className="mt-4"><Field label={t("message")}><textarea value={form.message} onChange={(event) => setForm({ ...form, message: event.target.value })} rows={7} className="w-full rounded-lg px-3 py-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /></Field></div><div className="mt-5 flex justify-end"><button type="button" disabled={!canSubmit} onClick={submit} className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-semibold disabled:opacity-50" style={{ background: GREEN, color: "white" }}><Send className="h-4 w-4" />{status === "sending" ? t("sending") : t("sendRequest")}</button></div></section><aside className="space-y-4"><section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><h3 className="text-[14px] font-semibold" style={{ color: TEXT }}>What happens next</h3><ol className="mt-3 space-y-2 text-[12px] leading-5" style={{ color: MUTED }}><li>1. The request is saved.</li><li>2. The team receives it when delivery is configured.</li><li>3. The status can be tracked in Requests.</li></ol></section><section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><h3 className="text-[14px] font-semibold" style={{ color: TEXT }}>Workspace context</h3><div className="mt-3 space-y-2 text-[12px]" style={{ color: MUTED }}><div>{currentWorkspace?.name || "Evaluation workspace"}</div><div>{currentOrganization?.name || "Organization"}</div><div>{currentOrganization?.plan || "free"}</div></div></section></aside></main></div>;
}
