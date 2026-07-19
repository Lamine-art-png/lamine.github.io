import { useEffect, useMemo, useState } from "react";
import { Copy, KeyRound, Plus, RefreshCw, ShieldCheck, Webhook } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

type Project = { id: string; name: string; slug: string; environment: string; status: string };
type ApiState = { projects?: Project[]; usage?: { metric: string; events: number; quantity: number }[]; webhooks?: unknown[] };

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, any> : {};
}

export function DevelopersApi() {
  const { platformAdmin } = useAuth();
  const [state, setState] = useState<ApiState>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [plaintextKey, setPlaintextKey] = useState("");
  const [projectName, setProjectName] = useState("Internal test project");
  const [serviceAccountName, setServiceAccountName] = useState("integration-sync");
  const [selectedProjectId, setSelectedProjectId] = useState("");

  const selectedProject = useMemo(() => (state.projects || []).find((project) => project.id === selectedProjectId) || state.projects?.[0], [selectedProjectId, state.projects]);

  async function refresh() {
    if (!platformAdmin) return;
    setLoading(true);
    setError("");
    try {
      const [projectsResult, usageResult, webhooksResult] = await Promise.all([
        apiClient.platformDeveloper.projects(),
        apiClient.platformDeveloper.usage(),
        apiClient.platformDeveloper.webhooks(),
      ]);
      const projects = asRecord(projectsResult).projects || [];
      setState({
        projects,
        usage: asRecord(usageResult).usage || [],
        webhooks: asRecord(webhooksResult).webhooks || [],
      });
      if (!selectedProjectId && projects[0]?.id) setSelectedProjectId(projects[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Platform API control plane is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, [platformAdmin]);

  async function createProject() {
    setError("");
    try {
      const result = await apiClient.platformDeveloper.createProject({ name: projectName, environment: "test" });
      const project = asRecord(result).project;
      setSelectedProjectId(project.id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Project creation failed.");
    }
  }

  async function createServiceAccountAndKey() {
    if (!selectedProject?.id) return;
    setError("");
    setPlaintextKey("");
    try {
      const serviceAccountResult = await apiClient.platformDeveloper.createServiceAccount(selectedProject.id, {
        name: serviceAccountName,
        scopes: ["projects:read", "connectors:read", "connectors:write", "actions:plan", "webhooks:read"],
      });
      const serviceAccount = asRecord(serviceAccountResult).service_account;
      const keyResult = await apiClient.platformDeveloper.createKey(serviceAccount.id, {
        name: `${serviceAccountName} test key`,
        scopes: ["projects:read", "connectors:read", "actions:plan"],
        expires_days: 90,
      });
      setPlaintextKey(String(asRecord(keyResult).plaintext_key || ""));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Service account or key creation failed.");
    }
  }

  if (!platformAdmin) {
    return <div className="min-h-full bg-[#F6F4EE] px-6 py-8 text-[#10231B]"><div className="mx-auto max-w-[760px] border border-[#D6DDD0] bg-white p-6">Not found.</div></div>;
  }

  return (
    <div className="min-h-full bg-[#F6F4EE] px-4 py-5 text-[#10231B] md:px-7 md:py-7">
      <div className="mx-auto flex max-w-[1180px] flex-col gap-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#2D6A4F]">Private Enterprise Partner Beta</div>
            <h1 className="mt-2 text-[26px] font-semibold tracking-tight md:text-[32px]">AGRO-AI Platform API</h1>
          </div>
          <button type="button" onClick={refresh} className="inline-flex h-10 items-center justify-center gap-2 border border-[#D6DDD0] bg-white px-3 text-[13px] font-semibold">
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
        </div>

        {error ? <div className="border border-[#D9A88B] bg-[#FFF4ED] px-4 py-3 text-[13px] text-[#7A2E0E]">{error}</div> : null}

        <section className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="border border-[#D6DDD0] bg-white p-4">
            <div className="flex items-center gap-2 text-[15px] font-semibold"><ShieldCheck className="h-4 w-4" /> API projects</div>
            <div className="mt-4 grid gap-3">
              {(state.projects || []).map((project) => (
                <button key={project.id} type="button" onClick={() => setSelectedProjectId(project.id)} className="flex items-center justify-between border border-[#E2D8C8] bg-[#FFFDF8] px-3 py-3 text-left">
                  <div>
                    <div className="text-[13px] font-semibold">{project.name}</div>
                    <div className="mt-1 text-[12px] text-[#65736A]">{project.environment} · {project.status}</div>
                  </div>
                  <div className="text-[11px] text-[#65736A]">{project.slug}</div>
                </button>
              ))}
              {!state.projects?.length ? <div className="text-[13px] text-[#65736A]">No Platform API projects are enabled for this organization.</div> : null}
            </div>
            <div className="mt-4 flex flex-col gap-2 md:flex-row">
              <input value={projectName} onChange={(event) => setProjectName(event.target.value)} className="h-10 min-w-0 flex-1 border border-[#D6DDD0] bg-white px-3 text-[13px]" />
              <button type="button" onClick={createProject} className="inline-flex h-10 items-center justify-center gap-2 bg-[#10231B] px-4 text-[13px] font-semibold text-white">
                <Plus className="h-4 w-4" /> Create test project
              </button>
            </div>
          </div>

          <div className="border border-[#D6DDD0] bg-white p-4">
            <div className="flex items-center gap-2 text-[15px] font-semibold"><KeyRound className="h-4 w-4" /> Scoped test key</div>
            <div className="mt-3 text-[13px] leading-6 text-[#65736A]">Creates a service account and a test-environment API key. Plaintext is shown only once.</div>
            <div className="mt-4 flex flex-col gap-2">
              <input value={serviceAccountName} onChange={(event) => setServiceAccountName(event.target.value)} className="h-10 border border-[#D6DDD0] bg-white px-3 text-[13px]" />
              <button type="button" disabled={!selectedProject || loading} onClick={createServiceAccountAndKey} className="inline-flex h-10 items-center justify-center gap-2 bg-[#10231B] px-4 text-[13px] font-semibold text-white disabled:opacity-50">
                <KeyRound className="h-4 w-4" /> Create service account and key
              </button>
            </div>
            {plaintextKey ? (
              <div className="mt-4 border border-[#DDEB8F] bg-[#FBFFF0] p-3">
                <div className="text-[12px] font-semibold text-[#2D6A4F]">One-time plaintext key</div>
                <div className="mt-2 break-all font-mono text-[12px]">{plaintextKey}</div>
                <button type="button" onClick={() => navigator.clipboard?.writeText(plaintextKey)} className="mt-3 inline-flex h-9 items-center gap-2 border border-[#D6DDD0] bg-white px-3 text-[12px] font-semibold">
                  <Copy className="h-3.5 w-3.5" /> Copy
                </button>
              </div>
            ) : null}
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <div className="border border-[#D6DDD0] bg-white p-4">
            <div className="text-[15px] font-semibold">Usage summary</div>
            <div className="mt-3 space-y-2">
              {(state.usage || []).map((item) => <div key={item.metric} className="flex justify-between border-b border-[#E2D8C8] py-2 text-[13px]"><span>{item.metric}</span><span>{item.quantity}</span></div>)}
              {!state.usage?.length ? <div className="text-[13px] text-[#65736A]">No Platform API usage recorded.</div> : null}
            </div>
          </div>
          <div className="border border-[#D6DDD0] bg-white p-4">
            <div className="flex items-center gap-2 text-[15px] font-semibold"><Webhook className="h-4 w-4" /> Webhooks</div>
            <div className="mt-3 text-[13px] text-[#65736A]">{state.webhooks?.length || 0} endpoints configured.</div>
          </div>
        </section>
      </div>
    </div>
  );
}
