import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity, BookOpen, Boxes, Copy, CreditCard, FileClock, Gauge, KeyRound,
  LifeBuoy, Plus, RefreshCw, RotateCw, ServerCog, ShieldCheck, Webhook,
} from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalCopy } from "../hooks/usePortalCopy";

type Project = { id: string; name: string; slug: string; environment: string; status: string };
type ServiceAccount = { id: string; api_project_id: string; name: string; status: string; scopes: string[]; last_used_at?: string };
type ApiKey = { id: string; service_account_id: string; name: string; status: string; environment: string; fingerprint: string; key_prefix: string; expires_at?: string; last_used_at?: string };
type Overview = {
  program?: string;
  enrollment_status?: string;
  allowed_environments?: string[];
  sections?: Record<string, boolean>;
  limits?: Record<string, number>;
};
type UnknownRecord = Record<string, unknown>;
type ConsoleState = {
  overview?: Overview;
  projects: Project[];
  serviceAccounts: ServiceAccount[];
  keys: ApiKey[];
  usage: { metric: string; events: number; quantity: number }[];
  requestLogs: UnknownRecord[];
  webhooks: UnknownRecord[];
  billing?: UnknownRecord;
  liveAccess: UnknownRecord[];
  support: UnknownRecord[];
};

const COPY = [
  "AGRO-AI Platform API", "Developer console", "Refresh", "Overview", "Projects",
  "Service Accounts", "API Keys", "Usage", "Request Logs", "Webhooks", "Billing",
  "Documentation", "Live Access", "Support", "Create test project", "Create service account",
  "Create key", "No records yet.", "One-time plaintext secret", "Copy", "Revoke",
  "Rotate", "Reset synthetic sandbox", "Test and live environments stay structurally separate.",
  "API billing is separate from your Enterprise Portal subscription.", "Open developer documentation",
  "Not found.", "The developer console is unavailable.", "Program", "Enrollment", "Allowed environments",
  "Resource limits", "Project name", "Service account name", "Key name", "Selected project",
  "Synthetic sandbox", "No live provider credentials or physical actions.", "Loading…",
  "Webhook URL", "Create webhook", "Rotate secret", "Disable",
] as const;

const TABS = [
  ["overview", "Overview", Gauge],
  ["projects", "Projects", Boxes],
  ["service_accounts", "Service Accounts", ServerCog],
  ["api_keys", "API Keys", KeyRound],
  ["usage", "Usage", Activity],
  ["request_logs", "Request Logs", FileClock],
  ["webhooks", "Webhooks", Webhook],
  ["billing", "Billing", CreditCard],
  ["documentation", "Documentation", BookOpen],
  ["live_access", "Live Access", ShieldCheck],
  ["support", "Support", LifeBuoy],
] as const;

function record(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, any> : {};
}

function rows(value: unknown, key: string): any[] {
  const source = record(value)[key];
  return Array.isArray(source) ? source : [];
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border border-[#D6DDD0] bg-white p-4 md:p-5">
      <h2 className="text-[15px] font-semibold">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function DevelopersApi() {
  const { platformDeveloper } = useAuth();
  const { tx } = usePortalCopy(["developers-api"], COPY);
  const [activeTab, setActiveTab] = useState("overview");
  const [state, setState] = useState<ConsoleState>({
    projects: [], serviceAccounts: [], keys: [], usage: [], requestLogs: [],
    webhooks: [], liveAccess: [], support: [],
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [plaintext, setPlaintext] = useState("");
  const [projectName, setProjectName] = useState("");
  const [serviceAccountName, setServiceAccountName] = useState("");
  const [keyName, setKeyName] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedServiceAccountId, setSelectedServiceAccountId] = useState("");

  const selectedProject = useMemo(
    () => state.projects.find((item) => item.id === selectedProjectId) || state.projects[0],
    [selectedProjectId, state.projects],
  );
  const projectServiceAccounts = state.serviceAccounts.filter((item) => !selectedProject || item.api_project_id === selectedProject.id);

  async function refresh() {
    if (!platformDeveloper) return;
    setLoading(true);
    setError("");
    try {
      const overview = record(await apiClient.platformDeveloper.overview());
      const optional = async (enabled: boolean, work: () => Promise<unknown>) => enabled ? work().catch(() => null) : null;
      const [projectsResult, serviceAccountsResult, keysResult, usageResult, logsResult, webhooksResult, billingResult, liveResult, supportResult] = await Promise.all([
        apiClient.platformDeveloper.projects(),
        apiClient.platformDeveloper.serviceAccounts(),
        apiClient.platformDeveloper.keys(),
        apiClient.platformDeveloper.usage(),
        apiClient.platformDeveloper.requestLogs(),
        apiClient.platformDeveloper.webhooks(),
        optional(Boolean(overview.sections?.billing), apiClient.platformDeveloper.billing),
        optional(Boolean(overview.sections?.live_access), apiClient.platformDeveloper.liveAccess),
        optional(Boolean(overview.sections?.support), apiClient.platformDeveloper.support),
      ]);
      const projects = rows(projectsResult, "projects");
      const serviceAccounts = rows(serviceAccountsResult, "service_accounts");
      setState({
        overview,
        projects,
        serviceAccounts,
        keys: rows(keysResult, "keys"),
        usage: rows(usageResult, "usage"),
        requestLogs: rows(logsResult, "items"),
        webhooks: rows(webhooksResult, "webhooks"),
        billing: billingResult ? record(billingResult) : undefined,
        liveAccess: rows(liveResult, "requests"),
        support: rows(supportResult, "support_requests"),
      });
      const nextProjectId = selectedProjectId || projects[0]?.id || "";
      setSelectedProjectId(nextProjectId);
      setSelectedServiceAccountId((current) => current || serviceAccounts.find((item) => item.api_project_id === nextProjectId)?.id || "");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tx("The developer console is unavailable."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, [platformDeveloper]);

  async function createProject() {
    if (!projectName.trim()) return;
    try {
      const result = record(await apiClient.platformDeveloper.createProject({ name: projectName.trim(), environment: "test" }));
      setProjectName("");
      setSelectedProjectId(String(result.project?.id || ""));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tx("The developer console is unavailable."));
    }
  }

  async function createServiceAccount() {
    if (!selectedProject?.id || !serviceAccountName.trim()) return;
    try {
      const result = record(await apiClient.platformDeveloper.createServiceAccount(selectedProject.id, {
        name: serviceAccountName.trim(),
        scopes: ["projects:read", "fields:read", "sources:read", "observations:read", "recommendations:read", "reports:read", "jobs:read", "usage:read", "request_logs:read", "webhooks:read"],
      }));
      setServiceAccountName("");
      setSelectedServiceAccountId(String(result.service_account?.id || ""));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tx("The developer console is unavailable."));
    }
  }

  async function createKey() {
    if (!selectedServiceAccountId || !keyName.trim()) return;
    try {
      const result = record(await apiClient.platformDeveloper.createKey(selectedServiceAccountId, {
        name: keyName.trim(),
        scopes: ["projects:read", "fields:read", "sources:read", "observations:read", "recommendations:read", "reports:read", "jobs:read", "usage:read", "request_logs:read", "webhooks:read"],
        expires_days: 90,
      }));
      setPlaintext(String(result.plaintext_key || ""));
      setKeyName("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tx("The developer console is unavailable."));
    }
  }

  async function revokeKey(keyId: string) {
    await apiClient.platformDeveloper.revokeKey(keyId);
    await refresh();
  }

  async function rotateKey(keyId: string) {
    const result = record(await apiClient.platformDeveloper.rotateKey(keyId));
    setPlaintext(String(result.plaintext_key || ""));
    await refresh();
  }

  async function createWebhook() {
    if (!selectedProject?.id || !webhookUrl.trim()) return;
    try {
      const result = record(await apiClient.platformDeveloper.createWebhook({
        api_project_id: selectedProject.id,
        url: webhookUrl.trim(),
        description: "Developer console endpoint",
        subscribed_event_types: ["recommendation.created", "source.created", "sync.completed"],
      }));
      setPlaintext(String(result.signing_secret || ""));
      setWebhookUrl("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tx("The developer console is unavailable."));
    }
  }

  async function rotateWebhookSecret(endpointId: string) {
    try {
      const result = record(await apiClient.platformDeveloper.rotateWebhookSecret(endpointId));
      setPlaintext(String(result.signing_secret || ""));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tx("The developer console is unavailable."));
    }
  }

  async function disableWebhook(endpointId: string) {
    try {
      await apiClient.platformDeveloper.disableWebhook(endpointId);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : tx("The developer console is unavailable."));
    }
  }

  if (!platformDeveloper) {
    return <div className="min-h-full bg-[#F6F4EE] px-6 py-8"><div className="mx-auto max-w-[760px] border border-[#D6DDD0] bg-white p-6">{tx("Not found.")}</div></div>;
  }

  const visibleTabs = TABS.filter(([key]) => key === "overview" || state.overview?.sections?.[key] !== false);
  const empty = <div className="text-[13px] text-[#65736A]">{tx("No records yet.")}</div>;

  return (
    <div className="min-h-full bg-[#F6F4EE] px-4 py-5 text-[#10231B] md:px-7 md:py-7">
      <div className="mx-auto max-w-[1220px]">
        <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#2D6A4F]">{tx("Developer console")}</div>
            <h1 className="mt-2 text-[28px] font-semibold tracking-tight md:text-[34px]">{tx("AGRO-AI Platform API")}</h1>
            <p className="mt-2 text-[13px] text-[#65736A]">{tx("Test and live environments stay structurally separate.")}</p>
          </div>
          <button type="button" onClick={() => void refresh()} className="inline-flex h-10 items-center justify-center gap-2 border border-[#D6DDD0] bg-white px-3 text-[13px] font-semibold">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> {loading ? tx("Loading…") : tx("Refresh")}
          </button>
        </header>

        {error ? <div role="alert" className="mt-4 border border-[#D9A88B] bg-[#FFF4ED] px-4 py-3 text-[13px] text-[#7A2E0E]">{error}</div> : null}
        {plaintext ? (
          <div className="mt-4 border border-[#A9C970] bg-[#FBFFF0] p-4">
            <div className="text-[12px] font-semibold text-[#2D6A4F]">{tx("One-time plaintext secret")}</div>
            <code className="mt-2 block break-all text-[12px]">{plaintext}</code>
            <button type="button" onClick={() => navigator.clipboard?.writeText(plaintext)} className="mt-3 inline-flex h-9 items-center gap-2 border border-[#D6DDD0] bg-white px-3 text-[12px] font-semibold"><Copy className="h-3.5 w-3.5" /> {tx("Copy")}</button>
          </div>
        ) : null}

        <div className="mt-5 overflow-x-auto border-b border-[#CDD6C8]" role="tablist" aria-label={tx("Developer console")}>
          <div className="flex min-w-max gap-1">
            {visibleTabs.map(([key, label, Icon]) => (
              <button key={key} type="button" role="tab" aria-selected={activeTab === key} onClick={() => setActiveTab(key)} className={`inline-flex h-11 items-center gap-2 px-3 text-[12px] font-semibold ${activeTab === key ? "border-b-2 border-[#2D6A4F] bg-white text-[#10231B]" : "text-[#65736A]"}`}>
                <Icon className="h-3.5 w-3.5" /> {tx(label)}
              </button>
            ))}
          </div>
        </div>

        <main className="mt-5 grid gap-4">
          {activeTab === "overview" ? (
            <div className="grid gap-4 md:grid-cols-2">
              <Card title={tx("Program")}><div className="text-[20px] font-semibold">{state.overview?.program || "—"}</div><div className="mt-2 text-[13px] text-[#65736A]">{tx("Enrollment")}: {state.overview?.enrollment_status || "—"}</div></Card>
              <Card title={tx("Allowed environments")}><div className="flex gap-2">{(state.overview?.allowed_environments || []).map((item) => <span key={item} className="bg-[#EDF5E9] px-3 py-1 text-[12px] font-semibold">{item}</span>)}</div></Card>
              <Card title={tx("Resource limits")}><div className="grid grid-cols-2 gap-3">{Object.entries(state.overview?.limits || {}).map(([key, value]) => <div key={key} className="border border-[#E2D8C8] p-3"><div className="text-[11px] uppercase text-[#65736A]">{key.replaceAll("_", " ")}</div><div className="mt-1 text-[20px] font-semibold">{value}</div></div>)}</div></Card>
              <Card title={tx("Synthetic sandbox")}><p className="text-[13px] leading-6 text-[#65736A]">{tx("No live provider credentials or physical actions.")}</p>{state.overview?.sections?.sandbox && selectedProject ? <button type="button" onClick={() => apiClient.platformDeveloper.resetSandbox(selectedProject.id)} className="mt-3 inline-flex h-9 items-center gap-2 border border-[#D6DDD0] px-3 text-[12px] font-semibold"><RotateCw className="h-3.5 w-3.5" /> {tx("Reset synthetic sandbox")}</button> : null}</Card>
            </div>
          ) : null}

          {activeTab === "projects" ? <Card title={tx("Projects")}><div className="grid gap-3 md:grid-cols-2">{state.projects.map((item) => <button key={item.id} type="button" onClick={() => setSelectedProjectId(item.id)} className={`p-4 text-left ${selectedProject?.id === item.id ? "border-2 border-[#2D6A4F]" : "border border-[#D6DDD0]"}`}><div className="font-semibold">{item.name}</div><div className="mt-1 text-[12px] text-[#65736A]">{item.environment} · {item.status} · {item.slug}</div></button>)}</div>{!state.projects.length ? empty : null}<div className="mt-4 flex gap-2"><input aria-label={tx("Project name")} value={projectName} onChange={(event) => setProjectName(event.target.value)} className="h-10 min-w-0 flex-1 border border-[#D6DDD0] px-3 text-[13px]" /><button type="button" onClick={() => void createProject()} className="inline-flex h-10 items-center gap-2 bg-[#10231B] px-4 text-[12px] font-semibold text-white"><Plus className="h-4 w-4" /> {tx("Create test project")}</button></div></Card> : null}

          {activeTab === "service_accounts" ? <Card title={tx("Service Accounts")}><div className="mb-3 text-[12px] text-[#65736A]">{tx("Selected project")}: {selectedProject?.name || "—"}</div><div className="space-y-2">{projectServiceAccounts.map((item) => <button key={item.id} type="button" onClick={() => setSelectedServiceAccountId(item.id)} className={`flex w-full items-center justify-between p-3 text-left ${selectedServiceAccountId === item.id ? "border-2 border-[#2D6A4F]" : "border border-[#D6DDD0]"}`}><span><strong className="text-[13px]">{item.name}</strong><span className="ml-2 text-[11px] text-[#65736A]">{item.status}</span></span><span className="text-[11px] text-[#65736A]">{item.scopes?.length || 0} scopes</span></button>)}</div>{!projectServiceAccounts.length ? empty : null}<div className="mt-4 flex gap-2"><input aria-label={tx("Service account name")} value={serviceAccountName} onChange={(event) => setServiceAccountName(event.target.value)} className="h-10 min-w-0 flex-1 border border-[#D6DDD0] px-3 text-[13px]" /><button type="button" onClick={() => void createServiceAccount()} className="inline-flex h-10 items-center gap-2 bg-[#10231B] px-4 text-[12px] font-semibold text-white"><Plus className="h-4 w-4" /> {tx("Create service account")}</button></div></Card> : null}

          {activeTab === "api_keys" ? <Card title={tx("API Keys")}><div className="space-y-2">{state.keys.map((item) => <div key={item.id} className="flex flex-col gap-3 border border-[#D6DDD0] p-3 md:flex-row md:items-center md:justify-between"><div><div className="text-[13px] font-semibold">{item.name}</div><div className="mt-1 font-mono text-[11px] text-[#65736A]">{item.key_prefix}… · {item.fingerprint} · {item.environment} · {item.status}</div></div><div className="flex gap-2"><button type="button" onClick={() => void rotateKey(item.id)} className="h-8 border border-[#D6DDD0] px-3 text-[11px] font-semibold">{tx("Rotate")}</button><button type="button" onClick={() => void revokeKey(item.id)} className="h-8 border border-[#D9A88B] px-3 text-[11px] font-semibold text-[#7A2E0E]">{tx("Revoke")}</button></div></div>)}</div>{!state.keys.length ? empty : null}<div className="mt-4 flex gap-2"><input aria-label={tx("Key name")} value={keyName} onChange={(event) => setKeyName(event.target.value)} className="h-10 min-w-0 flex-1 border border-[#D6DDD0] px-3 text-[13px]" /><button type="button" onClick={() => void createKey()} className="inline-flex h-10 items-center gap-2 bg-[#10231B] px-4 text-[12px] font-semibold text-white"><Plus className="h-4 w-4" /> {tx("Create key")}</button></div></Card> : null}

          {activeTab === "usage" ? <Card title={tx("Usage")}><div className="space-y-2">{state.usage.map((item) => <div key={item.metric} className="grid grid-cols-3 border-b border-[#E2D8C8] py-2 text-[13px]"><span>{item.metric}</span><span>{item.events} events</span><strong className="text-right">{item.quantity}</strong></div>)}</div>{!state.usage.length ? empty : null}</Card> : null}
          {activeTab === "request_logs" ? <Card title={tx("Request Logs")}><div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-[12px]"><thead><tr className="border-b border-[#D6DDD0] text-[#65736A]"><th className="py-2">Request ID</th><th>Status</th><th>Operation</th><th>Latency</th><th>Cost</th></tr></thead><tbody>{state.requestLogs.map((item) => <tr key={String(item.request_id)} className="border-b border-[#EEE8DE]"><td className="py-2 font-mono">{String(item.request_id)}</td><td>{String(item.status_code || "—")}</td><td>{String(item.operation_id || "—")}</td><td>{String(item.latency_ms || "—")} ms</td><td>{String(item.usage_cost || 0)}</td></tr>)}</tbody></table></div>{!state.requestLogs.length ? empty : null}</Card> : null}
          {activeTab === "webhooks" ? <Card title={tx("Webhooks")}><div className="space-y-2">{state.webhooks.map((item) => <div key={String(item.id)} className="flex flex-col gap-3 border border-[#D6DDD0] p-3 text-[13px] md:flex-row md:items-center md:justify-between"><div><strong>{String(item.url)}</strong><div className="mt-1 text-[11px] text-[#65736A]">{String(item.status)} · {String(item.signing_secret_prefix)}…</div></div>{String(item.status) === "active" ? <div className="flex gap-2"><button type="button" onClick={() => void rotateWebhookSecret(String(item.id))} className="h-8 border border-[#D6DDD0] px-3 text-[11px] font-semibold">{tx("Rotate secret")}</button><button type="button" onClick={() => void disableWebhook(String(item.id))} className="h-8 border border-[#D9A88B] px-3 text-[11px] font-semibold text-[#7A2E0E]">{tx("Disable")}</button></div> : null}</div>)}</div>{!state.webhooks.length ? empty : null}<div className="mt-4 flex gap-2"><input type="url" aria-label={tx("Webhook URL")} value={webhookUrl} onChange={(event) => setWebhookUrl(event.target.value)} placeholder="https://hooks.example.com/agroai" className="h-10 min-w-0 flex-1 border border-[#D6DDD0] px-3 text-[13px]" /><button type="button" onClick={() => void createWebhook()} className="inline-flex h-10 items-center gap-2 bg-[#10231B] px-4 text-[12px] font-semibold text-white"><Plus className="h-4 w-4" /> {tx("Create webhook")}</button></div></Card> : null}
          {activeTab === "billing" ? <Card title={tx("Billing")}><p className="text-[13px] text-[#65736A]">{tx("API billing is separate from your Enterprise Portal subscription.")}</p><pre className="mt-3 overflow-auto bg-[#F6F4EE] p-3 text-[11px]">{JSON.stringify(state.billing?.subscription || {}, null, 2)}</pre></Card> : null}
          {activeTab === "documentation" ? <Card title={tx("Documentation")}><a href="/developers" target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 bg-[#10231B] px-4 text-[12px] font-semibold text-white"><BookOpen className="h-4 w-4" /> {tx("Open developer documentation")}</a></Card> : null}
          {activeTab === "live_access" ? <Card title={tx("Live Access")}>{state.liveAccess.map((item) => <pre key={String(item.id)} className="mb-2 overflow-auto border border-[#D6DDD0] p-3 text-[11px]">{JSON.stringify(item, null, 2)}</pre>)}{!state.liveAccess.length ? empty : null}</Card> : null}
          {activeTab === "support" ? <Card title={tx("Support")}>{state.support.map((item) => <div key={String(item.id)} className="mb-2 border border-[#D6DDD0] p-3 text-[13px]"><strong>{String(item.subject)}</strong><div className="mt-1 text-[11px] text-[#65736A]">{String(item.category)} · {String(item.status)}</div></div>)}{!state.support.length ? empty : null}</Card> : null}
        </main>
      </div>
    </div>
  );
}
