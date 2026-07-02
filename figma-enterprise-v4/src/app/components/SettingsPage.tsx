import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Bell, CreditCard, Database, Globe2, PlugZap, ShieldCheck, SlidersHorizontal, Users } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { useLocale } from "../hooks/useLocale";
import { LanguageSelector } from "./LanguageSelector";
import { BG, BORDER, GREEN, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

function Card({ title, description, icon: Icon, children, action }: { title: string; description?: string; icon: any; children?: ReactNode; action?: ReactNode }) {
  return <section className="rounded-2xl p-5" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}><div className="flex items-start gap-3"><div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: "#EEF8E8", color: GREEN }}><Icon className="h-5 w-5" /></div><div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-4"><div><h2 className="text-[17px] font-semibold" style={{ color: TEXT }}>{title}</h2>{description ? <p className="mt-1 text-[13px] leading-6" style={{ color: MUTED }}>{description}</p> : null}</div>{action}</div>{children ? <div className="mt-4">{children}</div> : null}</div></div></section>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block text-[12px] font-medium" style={{ color: MUTED }}>{label}<div className="mt-1">{children}</div></label>;
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className="h-10 w-full rounded-lg px-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} />;
}

function Toggle({ checked, onChange, label, detail }: { checked: boolean; onChange: (value: boolean) => void; label: string; detail: string }) {
  return <button type="button" onClick={() => onChange(!checked)} className="flex w-full items-center justify-between gap-4 rounded-xl p-3 text-left" style={{ background: BG, border: `1px solid ${BORDER}` }}><span><span className="block text-[13px] font-semibold" style={{ color: TEXT }}>{label}</span><span className="mt-1 block text-[12px] leading-5" style={{ color: MUTED }}>{detail}</span></span><span className="relative h-6 w-11 shrink-0 rounded-full" style={{ background: checked ? GREEN : "#CBD5D1" }}><span className="absolute top-1 h-4 w-4 rounded-full bg-white transition-all" style={{ left: checked ? 23 : 4 }} /></span></button>;
}

export function SettingsPage() {
  const { currentOrganization, currentWorkspace, user, refreshMe } = useAuth();
  const { t } = useLocale();
  const plan = currentOrganization?.plan || "free";
  const [name, setName] = useState(user?.name || "");
  const [company, setCompany] = useState(currentOrganization?.name || "");
  const [role, setRole] = useState("");
  const [organizationType, setOrganizationType] = useState("commercial_farm");
  const [acresOrSites, setAcresOrSites] = useState("");
  const [primaryGoal, setPrimaryGoal] = useState("Turn field evidence into operational decisions and reports.");
  const [notifyReports, setNotifyReports] = useState(() => localStorage.getItem("agroai_notify_reports") !== "false");
  const [notifyAlerts, setNotifyAlerts] = useState(() => localStorage.getItem("agroai_notify_alerts") !== "false");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => { setName(user?.name || ""); setCompany(currentOrganization?.name || ""); }, [user?.name, currentOrganization?.name]);

  async function saveProfile() {
    setBusy("profile"); setMessage("");
    try { await apiClient.account.updateProfile({ name, company, role }); await refreshMe().catch(() => null); setMessage(t("saved")); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not save profile."); }
    finally { setBusy(""); }
  }

  async function saveWorkspacePreferences() {
    setBusy("workspace"); setMessage("");
    try { await apiClient.onboarding.update({ organization_type: organizationType, acres_or_sites: acresOrSites, primary_goal: primaryGoal, workspace_id: currentWorkspace?.id, completed_steps: ["settings"] }); setMessage(t("saved")); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not save workspace preferences."); }
    finally { setBusy(""); }
  }

  function saveNotifications() { localStorage.setItem("agroai_notify_reports", String(notifyReports)); localStorage.setItem("agroai_notify_alerts", String(notifyAlerts)); setMessage(t("saved")); }

  return <div className="min-h-screen" style={{ background: BG }}><header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}><div className="flex flex-wrap items-start justify-between gap-5"><div><div className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: GREEN }}>{t("workspace")}</div><h1 className="mt-2 text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>{t("settingsTitle")}</h1><p className="mt-2 max-w-3xl text-[14px] leading-7" style={{ color: MUTED }}>{t("settingsSubtitle")}</p></div><Link to="/billing"><PortalButton>{t("subscriptionBilling")}</PortalButton></Link></div></header><main className="grid gap-5 px-8 py-6 lg:grid-cols-2" style={{ maxWidth: 1240 }}>{message ? <div className="lg:col-span-2 rounded-xl px-4 py-3 text-[13px]" style={{ background: "#F0FDF4", border: "1px solid #BBF7D0", color: "#15803D" }}>{message}</div> : null}<Card icon={Globe2} title={t("languageRegion")} description={t("languageRegionHint")}><div className="max-w-[420px]"><LanguageSelector /></div></Card><Card icon={CreditCard} title={t("subscriptionBilling")} description="Review the active plan and manage billing."><div className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}><div className="text-[12px]" style={{ color: MUTED }}>{t("plan")}</div><div className="mt-1 text-[20px] font-semibold capitalize" style={{ color: TEXT }}>{plan}</div><div className="mt-4 flex flex-wrap gap-2"><Link to="/pricing"><PortalButton variant="secondary">Change plan</PortalButton></Link><Link to="/billing"><PortalButton variant="secondary">Open billing</PortalButton></Link></div></div></Card><Card icon={SlidersHorizontal} title={t("accountProfile")} description="Edit the user identity used in requests and audit trails." action={<PortalButton disabled={busy === "profile"} onClick={saveProfile}>{busy === "profile" ? t("saving") : t("save")}</PortalButton>}><div className="grid gap-3 md:grid-cols-2"><Field label="Name"><TextInput value={name} onChange={(event) => setName(event.target.value)} /></Field><Field label={t("companyRole")}><TextInput value={role} onChange={(event) => setRole(event.target.value)} placeholder="Owner, operator, advisor" /></Field><Field label="Company"><TextInput value={company} onChange={(event) => setCompany(event.target.value)} /></Field><Field label="Email"><TextInput value={user?.email || ""} disabled /></Field></div></Card><Card icon={Database} title={t("workspacePreferences")} description="Tell AGRO-AI what kind of operation this workspace represents." action={<PortalButton disabled={busy === "workspace"} onClick={saveWorkspacePreferences}>{busy === "workspace" ? t("saving") : t("save")}</PortalButton>}><div className="grid gap-3 md:grid-cols-2"><Field label="Organization type"><select value={organizationType} onChange={(event) => setOrganizationType(event.target.value)} className="h-10 w-full rounded-lg px-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }}><option value="commercial_farm">Commercial farm</option><option value="advisor">Advisor</option><option value="water_district">Water district</option><option value="grower_network">Grower network</option><option value="lender_insurer">Lender or insurer</option><option value="enterprise_ag">Enterprise agriculture</option></select></Field><Field label="Acres or sites"><TextInput value={acresOrSites} onChange={(event) => setAcresOrSites(event.target.value)} placeholder="4,500 acres / 12 sites" /></Field></div><div className="mt-3"><Field label="Primary operating goal"><textarea rows={4} value={primaryGoal} onChange={(event) => setPrimaryGoal(event.target.value)} className="w-full rounded-lg px-3 py-3 text-[13px] outline-none" style={{ background: BG, border: `1px solid ${BORDER}`, color: TEXT }} /></Field></div></Card><Card icon={Bell} title={t("notifications")} description="Choose what the portal should surface." action={<PortalButton variant="secondary" onClick={saveNotifications}>{t("save")}</PortalButton>}><div className="space-y-2"><Toggle checked={notifyReports} onChange={setNotifyReports} label="Report delivery updates" detail="Show status when reports are generated, exported, or emailed." /><Toggle checked={notifyAlerts} onChange={setNotifyAlerts} label="Operational alerts" detail="Surface water-risk, missing-evidence, readiness, and compliance alerts." /></div></Card><Card icon={PlugZap} title={t("integrationsControllers")} description="Connect field systems, evidence sources, and controller gateways."><div className="flex flex-wrap gap-2"><Link to="/integrations"><PortalButton variant="secondary">Open connectors</PortalButton></Link><Link to="/readiness"><PortalButton variant="secondary">Check readiness</PortalButton></Link></div></Card><Card icon={ShieldCheck} title="Security & access" description="Protect account access and team operations."><div className="flex flex-wrap gap-2"><Link to="/security"><PortalButton variant="secondary">Open security</PortalButton></Link><Link to="/team"><PortalButton variant="secondary">Open team</PortalButton></Link></div></Card><Card icon={Users} title="Support & requests" description="Track support, onboarding, integration, sales, and upgrade requests."><div className="flex flex-wrap gap-2"><Link to="/support"><PortalButton variant="secondary">Create ticket</PortalButton></Link><Link to="/admin/requests"><PortalButton variant="secondary">Open requests</PortalButton></Link></div></Card></main></div>;
}
