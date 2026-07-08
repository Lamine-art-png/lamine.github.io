import { Brain, Gauge, Sparkles } from "lucide-react";
import { useState } from "react";
import { useAuth } from "../../auth/AuthProvider";
import { BORDER, MUTED, SURFACE, TEXT } from "../portalUi";

export const REASONING_MODE_STORAGE_KEY = "agroai_reasoning_mode_v1";
export type ReasoningMode = "quick" | "standard" | "deep";

const CAPACITY = {
  free: { ai: "25 actions/month", deep: "2 Deep previews/month" },
  professional: { ai: "500 actions/month", deep: "25 Deep analyses/month" },
  team: { ai: "2,500 actions/month", deep: "150 Deep analyses/month" },
  network: { ai: "10,000 actions/month", deep: "750 Deep analyses/month" },
  enterprise: { ai: "Contract-configured actions", deep: "Contract-configured Deep capacity" },
} as const;

type PlanId = keyof typeof CAPACITY;

function planId(value: unknown): PlanId {
  const raw = String(value || "free").toLowerCase();
  const aliases: Record<string, PlanId> = { pilot: "free", pro: "professional", waterops: "professional", assurance_audit: "professional", assurance: "team", internal: "enterprise" };
  const next = aliases[raw] || raw;
  return next in CAPACITY ? next as PlanId : "free";
}

function initialMode(): ReasoningMode {
  const value = window.localStorage.getItem(REASONING_MODE_STORAGE_KEY);
  return value === "quick" || value === "deep" ? value : "standard";
}

export function IntelligencePlanControls() {
  const { currentOrganization } = useAuth();
  const [mode, setModeState] = useState<ReasoningMode>(initialMode);
  const plan = planId(currentOrganization?.plan);
  const cap = CAPACITY[plan];

  function selectMode(next: ReasoningMode) {
    setModeState(next);
    window.localStorage.setItem(REASONING_MODE_STORAGE_KEY, next);
  }

  const options = [
    { id: "quick" as const, name: "Quick", text: "Fast answers", icon: Gauge },
    { id: "standard" as const, name: "Standard", text: cap.ai, icon: Brain },
    { id: "deep" as const, name: "Deep", text: cap.deep, icon: Sparkles },
  ];

  return <section className="border-b px-6 py-4" style={{ background: SURFACE, borderColor: BORDER }}>
    <div className="mx-auto flex max-w-[900px] flex-wrap items-center justify-between gap-4">
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: MUTED }}>{plan} intelligence</div>
        <div className="mt-1 text-[12px] font-medium" style={{ color: TEXT }}>{cap.ai}</div>
        {plan === "free" ? <div className="mt-1 max-w-[430px] text-[11px] leading-5" style={{ color: MUTED }}>Professional increases capacity to 500 actions and 25 Deep analyses each month.</div> : null}
      </div>
      <div className="flex flex-wrap gap-2">
        {options.map((item) => {
          const Icon = item.icon;
          const active = item.id === mode;
          return <button key={item.id} type="button" onClick={() => selectMode(item.id)} className="min-w-[112px] rounded-xl px-3 py-2 text-left" style={{ background: active ? "#0D2B1E" : "#F6F4EE", color: active ? "white" : TEXT, border: `1px solid ${active ? "#0D2B1E" : BORDER}` }}>
            <div className="flex items-center gap-2 text-[12px] font-semibold"><Icon size={14} />{item.name}</div>
            <div className="mt-1 text-[10px]" style={{ color: active ? "rgba(255,255,255,0.68)" : MUTED }}>{item.text}</div>
          </button>;
        })}
      </div>
    </div>
  </section>;
}
