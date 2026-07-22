#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "src" / "app" / "components" / "PlatformConsole.tsx"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source match, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    source = TARGET.read_text(encoding="utf-8")

    source = replace_once(
        source,
        '''  secret: string;\n  secretTitle: string;\n  revealSecret: (title: string, value: string) => void;\n  clearSecret: () => void;''',
        '''  secret: string;\n  secretTitle: string;\n  secretError: string;\n  revealSecret: (title: string, value: string) => boolean;\n  clearSecret: () => void;\n  clearSecretError: () => void;''',
        "context secret contract",
    )

    source = replace_once(
        source,
        '''function rows(value: unknown, key: string): UnknownRecord[] {\n  const source = record(value)[key];\n  return Array.isArray(source) ? source : [];\n}\n''',
        '''function rows(value: unknown, key: string): UnknownRecord[] {\n  const source = record(value)[key];\n  return Array.isArray(source) ? source : [];\n}\n\nfunction actionMessage(cause: unknown, fallback: string) {\n  return cause instanceof Error && cause.message.trim() ? cause.message : fallback;\n}\n''',
        "action error helper",
    )

    source = replace_once(
        source,
        '''function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {\n  return <label className="block"><span className="mb-2 block text-[11px] font-bold uppercase tracking-[0.12em] text-[#53665A]">{label}</span>{children}{hint ? <span className="mt-2 block text-[11px] leading-5 text-[#7A867E]">{hint}</span> : null}</label>;\n}\n''',
        '''function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {\n  return <label className="block"><span className="mb-2 block text-[11px] font-bold uppercase tracking-[0.12em] text-[#53665A]">{label}</span>{children}{hint ? <span className="mt-2 block text-[11px] leading-5 text-[#7A867E]">{hint}</span> : null}</label>;\n}\n\nfunction ActionError({ message }: { message: string }) {\n  if (!message) return null;\n  return <div role="alert" aria-live="polite" className="rounded-xl border border-[#E4B9AE] bg-[#FFF2EE] px-4 py-3 text-[12px] leading-6 text-[#823628]">{message}</div>;\n}\n''',
        "inline action error component",
    )

    source = replace_once(
        source,
        '''  const [secret, setSecret] = useState("");\n  const [secretTitle, setSecretTitle] = useState("");''',
        '''  const [secret, setSecret] = useState("");\n  const [secretTitle, setSecretTitle] = useState("");\n  const [secretError, setSecretError] = useState("");''',
        "secret error state",
    )

    source = replace_once(
        source,
        '''  const selectedProject = state.projects.find((item) => item.id === selectedProjectId) || state.projects[0];\n  const revealSecret = (title: string, value: string) => { setSecretTitle(title); setSecret(value); };\n  const clearSecret = () => { setSecret(""); setSecretTitle(""); };\n\n  return (\n    <PlatformContext.Provider value={{ state, loading, error, selectedProjectId, selectedProject, setSelectedProjectId, refresh, secret, secretTitle, revealSecret, clearSecret }}>''',
        '''  const selectedProject = state.projects.find((item) => item.id === selectedProjectId) || state.projects[0];\n  const revealSecret = (title: string, value: string) => {\n    const normalized = value.trim();\n    if (!normalized) {\n      setSecret("");\n      setSecretTitle("");\n      setSecretError("The server did not return the one-time secret. Nothing was saved or copied. Do not retry blindly; review the request log or contact support with the request ID.");\n      return false;\n    }\n    setSecretError("");\n    setSecretTitle(title);\n    setSecret(normalized);\n    return true;\n  };\n  const clearSecret = () => { setSecret(""); setSecretTitle(""); };\n  const clearSecretError = () => setSecretError("");\n\n  return (\n    <PlatformContext.Provider value={{ state, loading, error, selectedProjectId, selectedProject, setSelectedProjectId, refresh, secret, secretTitle, secretError, revealSecret, clearSecret, clearSecretError }}>''',
        "one-time secret guard",
    )

    source = replace_once(
        source,
        '''  const { state, loading, error, selectedProjectId, setSelectedProjectId, refresh } = usePlatform();''',
        '''  const { state, loading, error, selectedProjectId, setSelectedProjectId, refresh, secretError, clearSecretError } = usePlatform();''',
        "shell secret error binding",
    )

    source = replace_once(
        source,
        '''            {error ? <div role="alert" className="mb-5 flex items-start gap-3 rounded-2xl border border-[#E4B9AE] bg-[#FFF2EE] px-4 py-3 text-[12px] leading-6 text-[#823628]"><CircleHelp className="mt-0.5 h-4 w-4 shrink-0" />{error}</div> : null}\n            <PlatformRoute route={route} navigate={navigate} />''',
        '''            {error ? <div role="alert" className="mb-5 flex items-start gap-3 rounded-2xl border border-[#E4B9AE] bg-[#FFF2EE] px-4 py-3 text-[12px] leading-6 text-[#823628]"><CircleHelp className="mt-0.5 h-4 w-4 shrink-0" />{error}</div> : null}\n            {secretError ? <div role="alert" aria-live="assertive" className="mb-5 flex items-start gap-3 rounded-2xl border border-[#E4B9AE] bg-[#FFF2EE] px-4 py-3 text-[12px] leading-6 text-[#823628]"><CircleHelp className="mt-0.5 h-4 w-4 shrink-0" /><span className="flex-1">{secretError}</span><button type="button" onClick={clearSecretError} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[#E4B9AE] bg-white/70" aria-label="Close"><X className="h-3.5 w-3.5" /></button></div> : null}\n            <PlatformRoute route={route} navigate={navigate} />''',
        "visible one-time secret failure",
    )

    source = replace_once(
        source,
        '''  const [working, setWorking] = useState(false);\n  const base = platformHost() ? "" : "/platform";\n  useEffect(() => { if (project) setSelectedProjectId(project.id); }, [project?.id]);\n  if (!project) return <NotFoundPage />;\n  const accounts = state.serviceAccounts.filter((item) => item.api_project_id === project.id);\n  const keys = state.keys.filter((item) => item.api_project_id === project.id);\n  const reset = async () => { setWorking(true); try { await apiClient.platformDeveloper.resetSandbox(project.id); await refresh(); } finally { setWorking(false); } };\n  return <div className="space-y-6"><PageHeader''',
        '''  const [working, setWorking] = useState(false);\n  const [localError, setLocalError] = useState("");\n  const base = platformHost() ? "" : "/platform";\n  useEffect(() => { if (project) setSelectedProjectId(project.id); }, [project?.id]);\n  if (!project) return <NotFoundPage />;\n  const accounts = state.serviceAccounts.filter((item) => item.api_project_id === project.id);\n  const keys = state.keys.filter((item) => item.api_project_id === project.id);\n  const reset = async () => {\n    if (!window.confirm(`Reset the deterministic sandbox for ${project.name}? Existing synthetic fields, observations, recommendations, reports, and jobs for this test project will be replaced.`)) return;\n    setWorking(true);\n    setLocalError("");\n    try { await apiClient.platformDeveloper.resetSandbox(project.id); await refresh(); }\n    catch (cause) { setLocalError(actionMessage(cause, "Sandbox reset failed.")); }\n    finally { setWorking(false); }\n  };\n  return <div className="space-y-6"><PageHeader''',
        "sandbox reset safety",
    )

    source = replace_once(
        source,
        ''' action={<div className="flex gap-3"><SecondaryButton onClick={() => navigate(`${base}/projects`)}>All projects</SecondaryButton>{project.environment === "test" ? <PrimaryButton onClick={() => void reset()} disabled={working}>{working ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />} Reset sandbox</PrimaryButton> : null}</div>} />\n    <div className="grid gap-4''',
        ''' action={<div className="flex gap-3"><SecondaryButton onClick={() => navigate(`${base}/projects`)}>All projects</SecondaryButton>{project.environment === "test" ? <PrimaryButton onClick={() => void reset()} disabled={working}>{working ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />} Reset sandbox</PrimaryButton> : null}</div>} />\n    <ActionError message={localError} />\n    <div className="grid gap-4''',
        "sandbox reset inline error",
    )

    source = replace_once(
        source,
        '''  const [name, setName] = useState("");\n  const [working, setWorking] = useState(false);\n  const create = async () => { if (!selectedProjectId || !name.trim()) return; setWorking(true); try { await apiClient.platformDeveloper.createServiceAccount(selectedProjectId, { name: name.trim(), description: "Platform console service account", scopes: DEFAULT_SCOPES }); setName(""); await refresh(); } finally { setWorking(false); } };''',
        '''  const [name, setName] = useState("");\n  const [working, setWorking] = useState(false);\n  const [localError, setLocalError] = useState("");\n  const create = async () => {\n    if (!selectedProjectId || !name.trim()) return;\n    setWorking(true);\n    setLocalError("");\n    try { await apiClient.platformDeveloper.createServiceAccount(selectedProjectId, { name: name.trim(), description: "Platform console service account", scopes: DEFAULT_SCOPES }); setName(""); await refresh(); }\n    catch (cause) { setLocalError(actionMessage(cause, "Service account creation failed.")); }\n    finally { setWorking(false); }\n  };''',
        "service account error handling",
    )

    source = replace_once(
        source,
        '''<Surface className="p-5"><div className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-end"><Field label="Project"><select className={inputClass} value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}><option value="">Select a project</option>{state.projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {project.environment}</option>)}</select></Field><Field label="Service account name"><input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} placeholder="backend-production" /></Field><PrimaryButton onClick={() => void create()} disabled={working || !selectedProjectId || !name.trim()}>{working ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Create</PrimaryButton></div></Surface>''',
        '''<Surface className="p-5"><div className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-end"><Field label="Project"><select className={inputClass} value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}><option value="">Select a project</option>{state.projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {project.environment}</option>)}</select></Field><Field label="Service account name"><input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} placeholder="backend-production" /></Field><PrimaryButton onClick={() => void create()} disabled={working || !selectedProjectId || !name.trim()}>{working ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Create</PrimaryButton></div><div className="mt-4"><ActionError message={localError} /></div></Surface>''',
        "service account inline error",
    )

    source = replace_once(
        source,
        '''  const [name, setName] = useState("");\n  const [working, setWorking] = useState("");\n  useEffect(() => { if (!accounts.some((item) => item.id === accountId)) setAccountId(accounts[0]?.id || ""); }, [selectedProjectId, state.serviceAccounts.length]);\n  const create = async () => { if (!accountId || !name.trim()) return; setWorking("create"); try { const result = record(await apiClient.platformDeveloper.createKey(accountId, { name: name.trim(), scopes: DEFAULT_SCOPES, expires_days: 90 })); revealSecret("Store this API key now", String(result.plaintext_key || "")); setName(""); await refresh(); } finally { setWorking(""); } };\n  const rotate = async (key: ApiKey) => { setWorking(key.id); try { const result = record(await apiClient.platformDeveloper.rotateKey(key.id)); revealSecret(`Rotated key · ${key.name}`, String(result.plaintext_key || "")); await refresh(); } finally { setWorking(""); } };\n  const revoke = async (key: ApiKey) => { if (!window.confirm(`Revoke ${key.name}? Existing integrations using it will stop authenticating.`)) return; setWorking(key.id); try { await apiClient.platformDeveloper.revokeKey(key.id); await refresh(); } finally { setWorking(""); } };''',
        '''  const [name, setName] = useState("");\n  const [working, setWorking] = useState("");\n  const [localError, setLocalError] = useState("");\n  useEffect(() => { if (!accounts.some((item) => item.id === accountId)) setAccountId(accounts[0]?.id || ""); }, [selectedProjectId, state.serviceAccounts.length]);\n  const create = async () => {\n    if (!accountId || !name.trim()) return;\n    setWorking("create");\n    setLocalError("");\n    try { const result = record(await apiClient.platformDeveloper.createKey(accountId, { name: name.trim(), scopes: DEFAULT_SCOPES, expires_days: 90 })); revealSecret("Store this API key now", String(result.plaintext_key || "")); setName(""); await refresh(); }\n    catch (cause) { setLocalError(actionMessage(cause, "API key creation failed.")); }\n    finally { setWorking(""); }\n  };\n  const rotate = async (key: ApiKey) => {\n    setWorking(key.id);\n    setLocalError("");\n    try { const result = record(await apiClient.platformDeveloper.rotateKey(key.id)); revealSecret(`Rotated key · ${key.name}`, String(result.plaintext_key || "")); await refresh(); }\n    catch (cause) { setLocalError(actionMessage(cause, "API key rotation failed.")); }\n    finally { setWorking(""); }\n  };\n  const revoke = async (key: ApiKey) => {\n    if (!window.confirm(`Revoke ${key.name}? Existing integrations using it will stop authenticating.`)) return;\n    setWorking(key.id);\n    setLocalError("");\n    try { await apiClient.platformDeveloper.revokeKey(key.id); await refresh(); }\n    catch (cause) { setLocalError(actionMessage(cause, "API key revocation failed.")); }\n    finally { setWorking(""); }\n  };''',
        "API key lifecycle errors",
    )

    source = replace_once(
        source,
        '''<Surface className="p-5"><div className="grid gap-4 xl:grid-cols-[1fr_1fr_1fr_auto] xl:items-end"><Field label="Project"><select className={inputClass} value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}><option value="">Select a project</option>{state.projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {project.environment}</option>)}</select></Field><Field label="Service account"><select className={inputClass} value={accountId} onChange={(event) => setAccountId(event.target.value)}><option value="">Select an identity</option>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></Field><Field label="Key name"><input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} placeholder="production-backend" /></Field><PrimaryButton onClick={() => void create()} disabled={working === "create" || !accountId || !name.trim()}>{working === "create" ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />} Create key</PrimaryButton></div></Surface>''',
        '''<Surface className="p-5"><div className="grid gap-4 xl:grid-cols-[1fr_1fr_1fr_auto] xl:items-end"><Field label="Project"><select className={inputClass} value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}><option value="">Select a project</option>{state.projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {project.environment}</option>)}</select></Field><Field label="Service account"><select className={inputClass} value={accountId} onChange={(event) => setAccountId(event.target.value)}><option value="">Select an identity</option>{accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></Field><Field label="Key name"><input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} placeholder="production-backend" /></Field><PrimaryButton onClick={() => void create()} disabled={working === "create" || !accountId || !name.trim()}>{working === "create" ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />} Create key</PrimaryButton></div><div className="mt-4"><ActionError message={localError} /></div></Surface>''',
        "API key inline error",
    )

    source = replace_once(
        source,
        '''  const [url, setUrl] = useState("");\n  const [working, setWorking] = useState("");\n  const create = async () => { if (!selectedProjectId || !url.trim()) return; setWorking("create"); try { const result = record(await apiClient.platformDeveloper.createWebhook({ api_project_id: selectedProjectId, url: url.trim(), description: "Platform console endpoint", subscribed_event_types: ["recommendation.created", "source.created", "sync.completed"] })); revealSecret("Store this webhook signing secret", String(result.signing_secret || "")); setUrl(""); await refresh(); } finally { setWorking(""); } };\n  const rotate = async (endpoint: UnknownRecord) => { setWorking(String(endpoint.id)); try { const result = record(await apiClient.platformDeveloper.rotateWebhookSecret(String(endpoint.id))); revealSecret("Rotated webhook signing secret", String(result.signing_secret || "")); await refresh(); } finally { setWorking(""); } };\n  const disable = async (endpoint: UnknownRecord) => { setWorking(String(endpoint.id)); try { await apiClient.platformDeveloper.disableWebhook(String(endpoint.id)); await refresh(); } finally { setWorking(""); } };''',
        '''  const [url, setUrl] = useState("");\n  const [working, setWorking] = useState("");\n  const [localError, setLocalError] = useState("");\n  const create = async () => {\n    if (!selectedProjectId || !url.trim()) return;\n    setWorking("create");\n    setLocalError("");\n    try { const result = record(await apiClient.platformDeveloper.createWebhook({ api_project_id: selectedProjectId, url: url.trim(), description: "Platform console endpoint", subscribed_event_types: ["recommendation.created", "source.created", "sync.completed"] })); revealSecret("Store this webhook signing secret", String(result.signing_secret || "")); setUrl(""); await refresh(); }\n    catch (cause) { setLocalError(actionMessage(cause, "Webhook creation failed.")); }\n    finally { setWorking(""); }\n  };\n  const rotate = async (endpoint: UnknownRecord) => {\n    setWorking(String(endpoint.id));\n    setLocalError("");\n    try { const result = record(await apiClient.platformDeveloper.rotateWebhookSecret(String(endpoint.id))); revealSecret("Rotated webhook signing secret", String(result.signing_secret || "")); await refresh(); }\n    catch (cause) { setLocalError(actionMessage(cause, "Webhook secret rotation failed.")); }\n    finally { setWorking(""); }\n  };\n  const disable = async (endpoint: UnknownRecord) => {\n    const endpointUrl = String(endpoint.url || endpoint.endpoint_url || "this endpoint");\n    if (!window.confirm(`Disable ${endpointUrl}? Event delivery will stop until the endpoint is explicitly re-enabled.`)) return;\n    setWorking(String(endpoint.id));\n    setLocalError("");\n    try { await apiClient.platformDeveloper.disableWebhook(String(endpoint.id)); await refresh(); }\n    catch (cause) { setLocalError(actionMessage(cause, "Webhook disablement failed.")); }\n    finally { setWorking(""); }\n  };''',
        "webhook lifecycle safety",
    )

    source = replace_once(
        source,
        '''<Surface className="p-5"><div className="grid gap-4 md:grid-cols-[1fr_1.4fr_auto] md:items-end"><Field label="Project"><select className={inputClass} value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}>{state.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></Field><Field label="HTTPS endpoint"><input className={inputClass} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/agroai/events" /></Field><PrimaryButton onClick={() => void create()} disabled={working === "create" || !url.trim()}>{working === "create" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Add endpoint</PrimaryButton></div></Surface>''',
        '''<Surface className="p-5"><div className="grid gap-4 md:grid-cols-[1fr_1.4fr_auto] md:items-end"><Field label="Project"><select className={inputClass} value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}>{state.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></Field><Field label="HTTPS endpoint"><input className={inputClass} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/agroai/events" /></Field><PrimaryButton onClick={() => void create()} disabled={working === "create" || !url.trim()}>{working === "create" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Add endpoint</PrimaryButton></div><div className="mt-4"><ActionError message={localError} /></div></Surface>''',
        "webhook inline error",
    )

    TARGET.write_text(source, encoding="utf-8")
    print(f"Hardened {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
