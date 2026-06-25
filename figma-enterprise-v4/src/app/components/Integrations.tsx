import { useCallback } from "react";
import { apiClient } from "../api/client";
import { usePortalResource } from "../hooks/usePortalResource";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import wiseconnLogo from "../../imports/wiseconn-logo-1.png";
import talgilLogo from "../../imports/talgil-logo-1.png";
import { BG, BORDER, InlineState, MUTED, StatusBadge, SURFACE, TEXT } from "./portalUi";

type IntegrationStatus = { status?: string; connected?: boolean; authenticated?: boolean; configured?: boolean };

function statusLabel(resource: ReturnType<typeof usePortalResource<unknown>>, data: unknown) {
  if (resource.isUnavailable) return { label: "backend route unavailable", tone: "warn" as const };
  if (!data || typeof data !== "object") return { label: "not configured", tone: "neutral" as const };
  const item = data as IntegrationStatus;
  if (item.connected || item.authenticated || item.status === "connected") return { label: "connected", tone: "good" as const };
  if (item.configured || item.status === "credentials_required") return { label: "credentials required", tone: "warn" as const };
  return { label: item.status || "not configured", tone: "neutral" as const };
}

export function Integrations() {
  const wiseconn = usePortalResource<unknown>(useCallback(() => apiClient.integrations.wiseconn(), []));
  const talgil = usePortalResource<unknown>(useCallback(() => apiClient.integrations.talgil(), []));
  const wiseconnStatus = statusLabel(wiseconn, wiseconn.data);
  const talgilStatus = statusLabel(talgil, talgil.data);

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="bg-[#FFFEFA] border-b border-[rgba(16,35,27,0.12)] px-8 py-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <h1 className="text-2xl font-bold text-[#10231B]">Integrations</h1>
            <span className="px-2.5 py-1 bg-[#F6F4EE] border border-[rgba(16,35,27,0.12)] rounded text-xs font-medium text-[#68776F]">
              Live status
            </span>
          </div>
        </div>
      </header>
      <div className="p-8">
        <div className="bg-[#FFFEFA] border border-[rgba(16,35,27,0.12)] rounded-xl p-8">
          <h2 className="text-lg font-bold text-[#10231B] mb-4">Connected Systems</h2>
          <div className="grid grid-cols-2 gap-4 mb-6">
            <IntegrationCard logo={wiseconnLogo} name="WiseConn" status={wiseconnStatus.label} tone={wiseconnStatus.tone} />
            <IntegrationCard logo={talgilLogo} name="Talgil" status={talgilStatus.label} tone={talgilStatus.tone} />
          </div>
          {(wiseconn.error && !wiseconn.isUnavailable) || (talgil.error && !talgil.isUnavailable) ? (
            <div className="mb-5">
              <InlineState title={wiseconn.error || talgil.error} />
            </div>
          ) : null}
          <div className="grid grid-cols-3 gap-3 mb-4">
            {["CropX", "Telemetry APIs", "Controller exports"].map((name) => (
              <div key={name} className="rounded-lg px-4 py-3" style={{ background: BG, border: `1px solid ${BORDER}` }}>
                <div className="text-sm font-medium" style={{ color: TEXT }}>{name}</div>
                <div className="text-xs" style={{ color: MUTED }}>compatible</div>
              </div>
            ))}
          </div>
          <div className="text-xs text-[#68776F]">
            Compatibility indicates technical integration capability, not endorsement or partnership.
          </div>
        </div>
      </div>
    </div>
  );
}
function IntegrationCard({ logo, name, status, tone }: { logo: string; name: string; status: string; tone: "neutral" | "good" | "warn" | "locked" }) {
  return (
    <div className="flex items-center gap-4 p-4 bg-[#F6F4EE] border border-[rgba(16,35,27,0.12)] rounded-lg">
      <div className="w-12 h-12 bg-white rounded flex items-center justify-center overflow-hidden">
        <ImageWithFallback src={logo} alt={name} className="w-full h-full object-contain p-1" />
      </div>
      <div className="flex-1">
        <div className="text-sm font-medium text-[#10231B]">{name}</div>
        <div className="mt-1"><StatusBadge label={status} tone={tone} /></div>
      </div>
      <button disabled className="px-3 py-1.5 text-xs text-[#68776F] cursor-not-allowed">Configure</button>
    </div>
  );
}
