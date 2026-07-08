import { useEffect, useRef } from "react";
import { Lock } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { useLocale } from "../hooks/useLocale";
import { openCommercialBoundary } from "./CommercialBoundaryHost";
import { Intelligence } from "./Intelligence";

const PAID_ASK_PLANS = new Set(["professional", "team", "network", "enterprise", "pro", "waterops", "assurance_audit", "assurance"]);

function capabilityEnabled(entitlements: Record<string, unknown>, key: string, fallback: boolean) {
  const capabilities = entitlements.capabilities;
  if (!capabilities || typeof capabilities !== "object" || Array.isArray(capabilities)) return fallback;
  const value = (capabilities as Record<string, unknown>)[key];
  return value === true || value === "enabled" || value === "preview";
}

export function MonetizedIntelligenceV2() {
  const { currentOrganization, entitlements } = useAuth();
  const { t } = useLocale();
  const opened = useRef(false);
  const plan = String(currentOrganization?.plan || "free").toLowerCase();
  const locked = !capabilityEnabled(entitlements, "intelligence.ask", PAID_ASK_PLANS.has(plan));

  function openWall() {
    openCommercialBoundary({
      status: 402,
      code: "upgrade_required",
      feature: "intelligence.ask",
      recommended_plan: "professional",
      source: "intelligence",
    });
  }

  useEffect(() => {
    if (!locked || opened.current) return;
    opened.current = true;
    const timer = window.setTimeout(openWall, 80);
    return () => window.clearTimeout(timer);
  }, [locked]);

  if (!locked) return <Intelligence />;

  return (
    <div className="min-h-full px-6 py-8" style={{ background: "#F6F4EE" }}>
      <section className="mx-auto max-w-[760px] rounded-[24px] border border-[#D6DDD0] bg-[#FFFDF8] p-8 shadow-[0_20px_70px_rgba(16,35,27,0.08)] md:p-10">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#EAF3DC] text-[#1F5A43]">
          <Lock className="h-5 w-5" />
        </div>
        <div className="mt-6 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#2D6A4F]">{t("intelligence.workspaceBadge")}</div>
        <h1 className="mt-3 text-[34px] font-semibold tracking-tight text-[#10231B]">{t("intelligence.title")}</h1>
        <p className="mt-4 max-w-2xl text-[14px] leading-7 text-[#65736A]">{t("intelligence.subtitle")}</p>
        <button type="button" onClick={openWall} className="mt-7 inline-flex h-11 items-center rounded-xl bg-[#0D2B1E] px-5 text-[13px] font-semibold text-white">
          {t("upgrade")}
        </button>
      </section>
    </div>
  );
}
