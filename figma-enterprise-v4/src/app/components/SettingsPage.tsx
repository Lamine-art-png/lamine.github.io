import type { InputHTMLAttributes, ReactNode } from "react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Bell, CreditCard, Database, FolderPen, Globe2, PlugZap, ShieldCheck, SlidersHorizontal, Users } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { getStoredLocale } from "../i18n";
import { useLocale } from "../hooks/useLocale";
import { translatePortalLiteral } from "../portalLiteralCatalog";
import { LanguageSelector } from "./LanguageSelector";
import { BG, BORDER, GREEN, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

const PRIMARY_GOAL_DEFAULT = { text: "Turn field evidence into operational decisions and reports." }.text;
const PENDING_PREFERENCES_KEY = "agroai_pending_preferences_v1";

type PreferencePayload = {
  locale: string;
  timezone: string;
  notifications: { report_delivery: boolean; operational_alerts: boolean; support_updates: boolean };
  ui: { density: string; assistant_speed: string; job_title: string };
};

function transientPreferenceSyncFailure(error: unknown) {
  const candidate = error && typeof error === "object" ? error as { status?: unknown; code?: unknown } : {};
  const status = Number(candidate.status || 0);
  const code = String(candidate.code || "");
  return status === 502 || status === 503 || status === 504 || code === "network_unavailable";
}

function readPendingPreferences(): PreferencePayload | null {
  try {
    const raw = localStorage.getItem(PENDING_PREFERENCES_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw);
    return value && typeof value === "object" && !Array.isArray(value) ? value as PreferencePayload : null;
  } catch {
    return null;
  }
}

function queuePendingPreferences(payload: PreferencePayload) {
  try { localStorage.setItem(PENDING_PREFERENCES_KEY, JSON.stringify(payload)); }
  catch { /* local persistence is best-effort */ }
}

function clearPendingPreferences() {
  try { localStorage.removeItem(PENDING_PREFERENCES_KEY); }
  catch { /* local persistence is best-effort */ }
}

function Card({ title, description, icon: Icon, children, action }: { title: string; description?: string; icon: any; children?: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: "#EEF8E8", color: GREEN }}><Icon className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-[17px] font-semibold" style={{ color: TEXT }}>{title}</h2>
              {description ? <p className="mt-1 text-[13px] leading-6" style={{ color: MUTED }}>{description}</p> : null}
            </div>
            {action}
          </div>
          {children ? <div className="mt-4">{children}</div> : null}
        </div>
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block text-[12px] font-medium" style={{ color: MUTED }}>{label}<div className="mt-1">{children}</div></label>;
}

function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`h-10 w-full rounded-lg px-3 text-[13px] outline-none ${props.className || ""}`.trim()} style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT, ...props.style }} />;
}

function Toggle({ checked, onChange, label, detail }: { checked: boolean; onChange: (value: boolean) => void; label: string; detail: string }) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className="flex w-full items-center justify-between gap-4 rounded-xl p-3 text-left" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <span><span className="block text-[13px] font-semibold" style={{ color: TEXT }}>{label}</span><span className="mt-1 block text-[12px] leading-5" style={{ color: MUTED }}>{detail}</span></span>
      <span className="relative h-6 w-11 shrink-0 rounded-full" style={{ background: checked ? GREEN : "#CBD5D1" }}><span className="absolute top-1 h-4 w-4 rounded-full bg-white transition-all" style={{ left: checked ? 23 : 4 }} /></span>
    </button>
  );
}

export function SettingsPage() {
  const { currentOrganization, currentWorkspace, user, refreshMe, updateWorkspace } = useAuth();
  const { t, setLocale, selectedLocale, catalogLoading } = useLocale();
  const plan = currentOrganization?.plan || "free";
  const canManageOperation = !currentOrganization?.role || ["owner", "admin"].includes(String(currentOrganization.role));
  const [operationName, setOperationName] = useState(currentWorkspace?.name || "");
  const [name, setName] = useState(user?.name || "");
  const [company, setCompany] = useState(currentOrganization?.name || "");
  const [jobTitle, setJobTitle] = useState("");
  const [organizationType, setOrganizationType] = useState("commercial_farm");
  const [acresOrSites, setAcresOrSites] = useState("");
  const [primaryGoalEdited, setPrimaryGoalEdited] = useState(false);
  const [primaryGoal, setPrimaryGoal] = useState(() => translatePortalLiteral(PRIMARY_GOAL_DEFAULT, getStoredLocale()));
  const [notifyReports, setNotifyReports] = useState(true);
  const [notifyAlerts, setNotifyAlerts] = useState(true);
  const [notifySupport, setNotifySupport] = useState(true);
  const [assistantSpeed, setAssistantSpeed] = useState("balanced");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    setName(user?.name || "");
    setCompany(currentOrganization?.name || "");
  }, [user?.name, currentOrganization?.name]);

  useEffect(() => {
    setOperationName(currentWorkspace?.name || "");
  }, [currentWorkspace?.id, currentWorkspace?.name]);

  useEffect(() => {
    if (!primaryGoalEdited && !catalogLoading) setPrimaryGoal(translatePortalLiteral(PRIMARY_GOAL_DEFAULT, selectedLocale));
  }, [selectedLocale, catalogLoading, primaryGoalEdited]);

  useEffect(() => {
    let mounted = true;
    apiClient.get("/v1/settings/preferences").then((response: any) => {
      if (!mounted) return;
      const prefs = response?.preferences || {};
      const notifications = prefs.notifications || {};
      const ui = prefs.ui || {};
      if (prefs.locale) setLocale(String(prefs.locale));
      setNotifyReports(notifications.report_delivery !== false);
      setNotifyAlerts(notifications.operational_alerts !== false);
      setNotifySupport(notifications.support_updates !== false);
      setAssistantSpeed(String(ui.assistant_speed || "balanced"));
      setJobTitle(String(ui.job_title || ""));
    }).catch(() => null);

    const pending = readPendingPreferences();
    if (pending) {
      apiClient.patch("/v1/settings/preferences", pending)
        .then(() => { if (mounted) clearPendingPreferences(); })
        .catch(() => null);
    }
    return () => { mounted = false; };
  }, []);

  async function saveOperationName() {
    if (!currentWorkspace?.id) return;
    if (operationName.trim().length < 2) {
      setMessage("Operation name must contain at least two characters.");
      return;
    }
    setBusy("operation");
    setMessage("");
    try {
      await updateWorkspace(currentWorkspace.id, { name: operationName.trim() });
      setMessage("Operation name saved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not rename the operation.");
    } finally {
      setBusy("");
    }
  }

  async function saveProfile() {
    setBusy("profile");
    setMessage("");
    try {
      await apiClient.patch("/v1/settings/profile", { name, company, job_title: jobTitle, organization_id: currentOrganization?.id });
      await refreshMe().catch(() => null);
      setMessage(t("saved"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save profile.");
    } finally {
      setBusy("");
    }
  }

  async function saveWorkspacePreferences() {
    setBusy("workspace");
    setMessage("");
    try {
      await apiClient.onboarding.update({ organization_type: organizationType, acres_or_sites: acresOrSites, primary_goal: primaryGoal, workspace_id: currentWorkspace?.id, completed_steps: ["settings"] });
      setMessage(t("saved"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save workspace preferences.");
    } finally {
      setBusy("");
    }
  }

  async function savePreferences() {
    setBusy("preferences");
    setMessage("");
    const payload: PreferencePayload = {
      locale: getStoredLocale(),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "auto",
      notifications: { report_delivery: notifyReports, operational_alerts: notifyAlerts, support_updates: notifySupport },
      ui: { density: "comfortable", assistant_speed: assistantSpeed, job_title: jobTitle },
    };
    queuePendingPreferences(payload);
    try {
      await apiClient.patch("/v1/settings/preferences", payload);
      clearPendingPreferences();
      setMessage(t("saved"));
    } catch (error) {
      if (transientPreferenceSyncFailure(error)) {
        console.warn("preferences_sync_deferred", { status: (error as any)?.status, code: (error as any)?.code });
        setMessage("");
      } else {
        setMessage(error instanceof Error ? error.message : "Could not save preferences.");
      }
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-4 py-6 sm:px-8 sm:py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: GREEN }}>{t("workspace")}</div>
            <h1 className="mt-2 text-[28px] font-semibold tracking-tight sm:text-[30px]" style={{ color: TEXT }}>{t("settingsTitle")}</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-7" style={{ color: MUTED }}>{t("settingsSubtitle")}</p>
          </div>
          <Link to="/billing"><PortalButton>{t("subscriptionBilling")}</PortalButton></Link>
        </div>
      </header>

      <main className="grid gap-5 px-4 py-5 sm:px-8 sm:py-6 lg:grid-cols-2" style={{ maxWidth: 1240 }}>
        {message ? <div className="rounded-xl px-4 py-3 text-[13px] lg:col-span-2" style={{ background: "#F0FDF4", border: "1px solid #BBF7D0", color: "#15803D" }}>{message}</div> : null}

        <Card
          icon={FolderPen}
          title="Current operation"
          description="Rename the active operation. Its files, evidence, tasks, decisions, connectors, and reports remain attached to the same operation identifier."
          action={<PortalButton disabled={busy === "operation" || !canManageOperation || !currentWorkspace?.id} onClick={saveOperationName}>{busy === "operation" ? t("saving") : t("save")}</PortalButton>}
        >
          <Field label="Operation name">
            <TextInput value={operationName} onChange={(event) => setOperationName(event.target.value)} maxLength={120} disabled={!canManageOperation || !currentWorkspace?.id} data-operation-name-setting />
          </Field>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Info label="Mode" value={currentWorkspace?.mode || "evaluation"} />
            <Info label="Crop" value={currentWorkspace?.crop || "Not set"} />
            <Info label="Region" value={currentWorkspace?.region || "Not set"} />
          </div>
          {!canManageOperation ? <p className="mt-3 text-[12px]" style={{ color: MUTED }}>Only an organization owner or admin can rename an operation.</p> : null}
        </Card>

        <Card icon={Globe2} title={t("languageRegion")} description={t("languageRegionHint")} action={<PortalButton disabled={busy === "preferences"} onClick={savePreferences}>{busy === "preferences" ? t("saving") : t("save")}</PortalButton>}>
          <div className="max-w-[420px]"><LanguageSelector /></div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <Field label="Timezone"><TextInput value={Intl.DateTimeFormat().resolvedOptions().timeZone || "auto"} disabled /></Field>
            <Field label="Assistant speed">
              <select value={assistantSpeed} onChange={(event) => setAssistantSpeed(event.target.value)} className="h-10 w-full rounded-lg px-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                <option value="fast">Fast answers for simple work</option>
                <option value="balanced">Balanced</option>
                <option value="deep">Deep mode for reports</option>
              </select>
            </Field>
          </div>
        </Card>

        <Card icon={CreditCard} title={t("subscriptionBilling")} description="Review the active plan and manage billing.">
          <div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
            <div className="text-[12px]" style={{ color: MUTED }}>{t("plan")}</div>
            <div className="mt-1 text-[20px] font-semibold capitalize" style={{ color: TEXT }}>{plan}</div>
            <div className="mt-4 flex flex-wrap gap-2"><Link to="/pricing"><PortalButton variant="secondary">Change plan</PortalButton></Link><Link to="/billing"><PortalButton variant="secondary">Open billing</PortalButton></Link></div>
          </div>
        </Card>

        <Card icon={SlidersHorizontal} title={t("accountProfile")} description="Edit the identity used in support tickets, requests, audit trails, and team workflows." action={<PortalButton disabled={busy === "profile"} onClick={saveProfile}>{busy === "profile" ? t("saving") : t("save")}</PortalButton>}>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Name"><TextInput value={name} onChange={(event) => setName(event.target.value)} /></Field>
            <Field label="Job title"><TextInput value={jobTitle} onChange={(event) => setJobTitle(event.target.value)} placeholder="Owner, operator, advisor" /></Field>
            <Field label="Company"><TextInput value={company} onChange={(event) => setCompany(event.target.value)} /></Field>
            <Field label="Email"><TextInput value={user?.email || ""} disabled /></Field>
          </div>
        </Card>

        <Card icon={Database} title={t("workspacePreferences")} description="Tell AGRO-AI what kind of operation this workspace represents." action={<PortalButton disabled={busy === "workspace"} onClick={saveWorkspacePreferences}>{busy === "workspace" ? t("saving") : t("save")}</PortalButton>}>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Organization type">
              <select value={organizationType} onChange={(event) => setOrganizationType(event.target.value)} className="h-10 w-full rounded-lg px-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}>
                <option value="commercial_farm">Commercial farm</option>
                <option value="advisor">Advisor</option>
                <option value="water_district">Water district</option>
                <option value="grower_network">Grower network</option>
                <option value="lender_insurer">Lender or insurer</option>
                <option value="enterprise_ag">Enterprise agriculture</option>
              </select>
            </Field>
            <Field label="Acres or sites"><TextInput value={acresOrSites} onChange={(event) => setAcresOrSites(event.target.value)} placeholder="4,500 acres / 12 sites" /></Field>
          </div>
          <div className="mt-3"><Field label="Primary operating goal"><textarea rows={4} value={primaryGoal} onChange={(event) => { setPrimaryGoalEdited(true); setPrimaryGoal(event.target.value); }} className="w-full rounded-lg px-3 py-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /></Field></div>
        </Card>

        <Card icon={Bell} title={t("notifications")} description="Choose what the portal should surface." action={<PortalButton variant="secondary" disabled={busy === "preferences"} onClick={savePreferences}>{t("save")}</PortalButton>}>
          <div className="space-y-2">
            <Toggle checked={notifyReports} onChange={setNotifyReports} label="Report delivery updates" detail="Show status when reports are generated, exported, or emailed." />
            <Toggle checked={notifyAlerts} onChange={setNotifyAlerts} label="Operational alerts" detail="Surface water-risk, missing-evidence, readiness, and compliance alerts." />
            <Toggle checked={notifySupport} onChange={setNotifySupport} label="Support updates" detail="Surface support ticket and onboarding request status updates." />
          </div>
        </Card>

        <Card icon={PlugZap} title={t("integrationsControllers")} description="Connect field systems, evidence sources, and controller gateways.">
          <div className="flex flex-wrap gap-2"><Link to="/integrations"><PortalButton variant="secondary">Open connectors</PortalButton></Link><Link to="/readiness"><PortalButton variant="secondary">Check readiness</PortalButton></Link></div>
        </Card>

        <Card icon={ShieldCheck} title="Security & access" description="Protect account access and team operations.">
          <div className="flex flex-wrap gap-2"><Link to="/security"><PortalButton variant="secondary">Open security</PortalButton></Link><Link to="/team"><PortalButton variant="secondary">Open team</PortalButton></Link></div>
        </Card>

        <Card icon={Users} title="Support & requests" description="Track support, onboarding, integration, sales, and upgrade requests.">
          <div className="flex flex-wrap gap-2"><Link to="/support"><PortalButton variant="secondary">Create ticket</PortalButton></Link><Link to="/admin/requests"><PortalButton variant="secondary">Open requests</PortalButton></Link></div>
        </Card>
      </main>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg px-3 py-2" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: MUTED }}>{label}</div><div className="mt-1 truncate text-[12px] capitalize" style={{ color: TEXT }}>{value}</div></div>;
}
