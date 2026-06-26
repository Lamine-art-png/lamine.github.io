import { useCallback, useMemo, useState } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { usePortalResource } from "../hooks/usePortalResource";
import { BG, BORDER, InlineState, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type AnyRecord = Record<string, any>;
type ProviderId =
  | "wiseconn"
  | "talgil"
  | "weather"
  | "openet"
  | "manual_csv"
  | "gmail"
  | "outlook"
  | "google_drive"
  | "custom_api";

type Connector = {
  id: ProviderId;
  name: string;
  category: string;
  status: string;
  required_plan: "free" | "pilot" | "pro" | "enterprise";
  connection_methods: string[];
  imports: string[];
  used_by: string[];
  promise: string;
};

const FALLBACK_CONNECTORS: Connector[] = [
  {
    id: "wiseconn",
    name: "WiseConn",
    category: "Irrigation controllers",
    status: "missing_credentials",
    required_plan: "pilot",
    connection_methods: ["api_credentials", "export_upload"],
    imports: ["farms", "zones", "controller events", "flow", "irrigation history", "valve state"],
    used_by: ["Decisions", "Evidence", "Reports", "Assurance"],
    promise: "Turn WiseConn controller history into cited irrigation decisions and assurance records.",
  },
  {
    id: "talgil",
    name: "Talgil",
    category: "Irrigation controllers",
    status: "missing_credentials",
    required_plan: "pilot",
    connection_methods: ["api_credentials", "export_upload"],
    imports: ["targets", "program state", "valve state", "flow", "irrigation events"],
    used_by: ["Decisions", "Evidence", "Reports", "Assurance"],
    promise: "Transform Talgil controller evidence into water operations intelligence.",
  },
  {
    id: "manual_csv",
    name: "CSV / PDF / Spreadsheet upload",
    category: "Manual evidence",
    status: "upload_ready",
    required_plan: "free",
    connection_methods: ["upload"],
    imports: ["CSV", "PDF", "spreadsheets", "operator notes", "field logs"],
    used_by: ["Evidence", "Reports", "Ask AGRO-AI"],
    promise: "Upload fragmented evidence and let AGRO-AI structure it into field context.",
  },
  {
    id: "weather",
    name: "Weather / Forecast",
    category: "Environmental data",
    status: "not_configured",
    required_plan: "pilot",
    connection_methods: ["managed_provider", "api_credentials"],
    imports: ["temperature", "precipitation", "humidity", "forecast"],
    used_by: ["Decisions", "Reports"],
    promise: "Bring weather context into irrigation recommendations and risk flags.",
  },
  {
    id: "openet",
    name: "OpenET / ET data",
    category: "Water intelligence",
    status: "not_configured",
    required_plan: "pro",
    connection_methods: ["managed_provider", "api_credentials"],
    imports: ["ET", "ET0", "field water use estimates"],
    used_by: ["Decisions", "Assurance", "Reports"],
    promise: "Add satellite ET context to field-level water accounting.",
  },
  {
    id: "gmail",
    name: "Gmail",
    category: "Email evidence",
    status: "coming_soon",
    required_plan: "pro",
    connection_methods: ["oauth"],
    imports: ["attachments", "operator emails", "reports", "vendor records"],
    used_by: ["Evidence", "Reports", "Automations"],
    promise: "Pull approved agricultural evidence from email threads and attachments.",
  },
  {
    id: "outlook",
    name: "Outlook",
    category: "Email evidence",
    status: "coming_soon",
    required_plan: "pro",
    connection_methods: ["oauth"],
    imports: ["attachments", "operator emails", "reports", "vendor records"],
    used_by: ["Evidence", "Reports", "Automations"],
    promise: "Bring Microsoft email evidence into the same proof layer.",
  },
  {
    id: "google_drive",
    name: "Google Drive",
    category: "Document evidence",
    status: "coming_soon",
    required_plan: "pro",
    connection_methods: ["oauth"],
    imports: ["folders", "PDFs", "spreadsheets", "reports"],
    used_by: ["Evidence", "Reports"],
    promise: "Connect field folders and keep reports/evidence synced.",
  },
  {
    id: "custom_api",
    name: "Custom API",
    category: "Enterprise systems",
    status: "enterprise",
    required_plan: "enterprise",
    connection_methods: ["api_contract", "webhook", "sftp"],
    imports: ["ERP records", "district records", "sensor APIs", "custom telemetry"],
    used_by: ["Enterprise deployments"],
    promise: "Connect district, agribusiness, or enterprise systems into AGRO-AI.",
  },
];

const PLAN_RANK = { free: 0, pilot: 1, starter: 1, pro: 2, operator: 2, enterprise: 3 } as Record<string, number>;

function planRank(plan?: string) {
  return PLAN_RANK[String(plan || "free").toLowerCase()] ?? 0;
}

function statusTone(status: string): "neutral" | "good" | "warn" | "locked" {
  if (["connected", "available", "upload_ready"].includes(status)) return "good";
  if (["coming_soon", "enterprise"].includes(status)) return "locked";
  if (status.includes("missing") || status.includes("required") || status.includes("not_configured")) return "warn";
  return "neutral";
}

function asArray(value: unknown): AnyRecord[] {
  return Array.isArray(value) ? (value as AnyRecord[]) : [];
}

export function Integrations() {
  const { currentOrganization } = useAuth();
  const catalogState = usePortalResource<AnyRecord>(useCallback(() => apiClient.connectorHub.catalog(), []));
  const briefState = usePortalResource<AnyRecord>(useCallback(() => apiClient.intelligence.brief(), []));
  const [selected, setSelected] = useState<Connector | null>(null);
  const [setup, setSetup] = useState<AnyRecord | null>(null);
  const [starting, setStarting] = useState("");

  const catalog = useMemo(() => {
    const remote = asArray(catalogState.data?.connectors) as Connector[];
    return remote.length ? remote : FALLBACK_CONNECTORS;
  }, [catalogState.data]);

  const liveStatuses = asArray(briefState.data?.integration_status);
  const statusByName = new Map(liveStatuses.map((item) => [String(item.name || "").toLowerCase(), item]));

  const plan = String(currentOrganization?.plan || "free").toLowerCase();
  const rank = planRank(plan);

  function isUnlocked(connector: Connector) {
    return rank >= planRank(connector.required_plan);
  }

  async function start(connector: Connector) {
    setSelected(connector);
    setSetup(null);
    if (!isUnlocked(connector)) return;
    setStarting(connector.id);
    try {
      const response = await apiClient.connectorHub.start({
        provider: connector.id,
        method: connector.connection_methods[0] || "guided_setup",
        metadata: { surface: "connector_hub" },
      });
      setSetup(response as AnyRecord);
    } finally {
      setStarting("");
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="px-8 py-7" style={{ background: SURFACE, borderBottom: `1px solid ${BORDER}` }}>
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <StatusBadge label="Connector Hub" tone="good" />
              <StatusBadge label={`${plan} plan`} />
            </div>
            <h1 className="text-[30px] font-semibold tracking-tight" style={{ color: TEXT }}>Connectors</h1>
            <p className="mt-2 max-w-3xl text-[14px] leading-relaxed" style={{ color: MUTED }}>
              Connect controllers, telemetry, weather, documents, email, and enterprise systems into one evidence fabric. Every source becomes usable by Decisions, Evidence, Reports, Assurance, Automations, and Ask AGRO-AI.
            </p>
          </div>
          <PortalButton variant="secondary" onClick={() => { catalogState.refresh(); briefState.refresh(); }}>Refresh sources</PortalButton>
        </div>
      </header>

      <div className="px-8 py-6 space-y-6" style={{ maxWidth: 1280 }}>
        {catalogState.error && !catalogState.isUnavailable ? <InlineState title={catalogState.error} /> : null}

        <section className="grid gap-5" style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr" }}>
          <TierCard name="Free" headline="Evaluate the magic" items={["Demo workspace", "Sample telemetry", "Ask AGRO-AI", "Connector marketplace preview"]} active={plan === "free"} />
          <TierCard name="Pilot" headline="First live operation" items={["1 live controller source", "Manual uploads", "Basic decisions", "Report drafts"]} active={["pilot", "starter"].includes(plan)} />
          <TierCard name="Pro" headline="Daily water ops" items={["Multiple sources", "Agent runs", "Report exports", "Evidence gap analysis"]} active={["pro", "operator"].includes(plan)} />
          <TierCard name="Enterprise" headline="District-grade" items={["Custom APIs", "SSO/RBAC", "Audit logs", "Compliance templates"]} active={plan === "enterprise"} />
        </section>

        <section className="grid grid-cols-3 gap-4">
          {catalog.map((connector) => {
            const live = statusByName.get(connector.name.toLowerCase());
            const status = String(live?.status || connector.status);
            const unlocked = isUnlocked(connector);
            return (
              <ConnectorCard
                key={connector.id}
                connector={{ ...connector, status }}
                unlocked={unlocked}
                starting={starting === connector.id}
                onSelect={() => start({ ...connector, status })}
              />
            );
          })}
        </section>

        <section className="rounded-2xl p-6" style={{ background: "#0D2B1E", border: "1px solid rgba(255,255,255,0.08)" }}>
          <div className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: "rgba(155,216,75,0.65)" }}>UX principle</div>
          <h2 className="text-[22px] font-semibold mb-2" style={{ color: "white" }}>The customer should not manage data plumbing.</h2>
          <p className="text-[13px] leading-relaxed max-w-4xl" style={{ color: "rgba(255,255,255,0.68)" }}>
            AGRO-AI’s job is to absorb fragmented farm systems, identify what evidence exists, expose what is missing, generate decisions, and produce proof. Connectors are not settings. They are the front door to the operating system.
          </p>
        </section>
      </div>

      {selected ? (
        <div className="fixed inset-0 z-50">
          <button className="absolute inset-0 bg-black/30" onClick={() => { setSelected(null); setSetup(null); }} aria-label="Close connector setup" />
          <aside className="absolute right-0 top-0 h-full w-[560px] max-w-[96vw] overflow-y-auto shadow-2xl" style={{ background: SURFACE }}>
            <div className="px-6 py-5" style={{ borderBottom: `1px solid ${BORDER}` }}>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>{selected.category}</div>
                  <h2 className="text-xl font-semibold" style={{ color: TEXT }}>{selected.name}</h2>
                  <p className="mt-2 text-[13px] leading-relaxed" style={{ color: MUTED }}>{selected.promise}</p>
                </div>
                <StatusBadge label={selected.status} tone={statusTone(selected.status)} />
              </div>
            </div>

            <div className="p-6 space-y-5">
              {!isUnlocked(selected) ? (
                <InlineState
                  title={`${selected.name} requires ${selected.required_plan} plan`}
                  detail="Free mode is for evaluation and demo context. Live integrations, exports, and operational workflows unlock on paid plans."
                />
              ) : null}

              <Panel title="What AGRO-AI imports">
                <div className="flex flex-wrap gap-2">
                  {selected.imports.map((item) => <Chip key={item}>{item}</Chip>)}
                </div>
              </Panel>

              <Panel title="Used by">
                <div className="flex flex-wrap gap-2">
                  {selected.used_by.map((item) => <Chip key={item}>{item}</Chip>)}
                </div>
              </Panel>

              <Panel title="Setup flow">
                {(setup?.steps || [
                  "Choose connection method",
                  "Enter credentials or upload export",
                  "Test connection",
                  "Map farms, zones, blocks, and telemetry fields",
                  "Review imported evidence",
                  "Enable scheduled sync",
                ]).map((step: string, index: number) => (
                  <div key={step} className="flex gap-3 py-2">
                    <div className="h-6 w-6 rounded-full flex items-center justify-center text-[11px] font-semibold" style={{ background: BG, color: TEXT, border: `1px solid ${BORDER}` }}>{index + 1}</div>
                    <div className="text-[13px] leading-relaxed" style={{ color: MUTED }}>{step}</div>
                  </div>
                ))}
              </Panel>

              {setup ? (
                <InlineState
                  title="Connector setup session created"
                  detail={setup.warning || "Proceed through the portal setup flow before enabling live sync."}
                />
              ) : null}

              <div className="flex gap-2">
                <PortalButton disabled={!isUnlocked(selected) || Boolean(starting)} onClick={() => start(selected)}>
                  {starting ? "Starting…" : `Start ${selected.name} setup`}
                </PortalButton>
                <PortalButton variant="secondary" onClick={() => { setSelected(null); setSetup(null); }}>Close</PortalButton>
              </div>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function ConnectorCard({ connector, unlocked, starting, onSelect }: { connector: Connector; unlocked: boolean; starting: boolean; onSelect: () => void }) {
  return (
    <div className="rounded-2xl p-5 flex flex-col min-h-[265px]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest mb-1" style={{ color: MUTED }}>{connector.category}</div>
          <h3 className="text-[17px] font-semibold" style={{ color: TEXT }}>{connector.name}</h3>
        </div>
        <StatusBadge label={unlocked ? connector.status : `${connector.required_plan} plan`} tone={unlocked ? statusTone(connector.status) : "locked"} />
      </div>
      <p className="text-[12px] leading-relaxed mb-4 flex-1" style={{ color: MUTED }}>{connector.promise}</p>
      <div className="space-y-1 mb-4">
        {connector.imports.slice(0, 4).map((item) => (
          <div key={item} className="text-[11px]" style={{ color: MUTED }}>• {item}</div>
        ))}
      </div>
      <button
        type="button"
        onClick={onSelect}
        className="h-10 rounded-lg text-[12px] font-semibold transition-colors"
        style={{
          background: unlocked ? "#16533C" : "#F6F4EE",
          color: unlocked ? "white" : "#68776F",
          border: unlocked ? "1px solid #16533C" : `1px solid ${BORDER}`,
        }}
      >
        {starting ? "Starting…" : unlocked ? "Connect" : "View upgrade path"}
      </button>
    </div>
  );
}

function TierCard({ name, headline, items, active }: { name: string; headline: string; items: string[]; active: boolean }) {
  return (
    <section className="rounded-2xl p-5" style={{ background: active ? "#0D2B1E" : SURFACE, border: active ? "1px solid rgba(255,255,255,0.08)" : `1px solid ${BORDER}` }}>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-[15px] font-semibold" style={{ color: active ? "white" : TEXT }}>{name}</h3>
        {active ? <StatusBadge label="Current" tone="good" /> : null}
      </div>
      <div className="text-[12px] mb-3" style={{ color: active ? "rgba(255,255,255,0.62)" : MUTED }}>{headline}</div>
      <div className="space-y-1">
        {items.map((item) => <div key={item} className="text-[11px]" style={{ color: active ? "rgba(255,255,255,0.58)" : MUTED }}>• {item}</div>)}
      </div>
    </section>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl p-4" style={{ background: BG, border: `1px solid ${BORDER}` }}>
      <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: MUTED }}>{title}</div>
      {children}
    </section>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full px-3 py-1 text-[11px]" style={{ background: SURFACE, border: `1px solid ${BORDER}`, color: TEXT }}>
      {children}
    </span>
  );
}
