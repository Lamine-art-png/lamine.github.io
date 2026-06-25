import { useState } from "react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { BG, BORDER, InlineState, MUTED, PortalButton, SURFACE, TEXT } from "./portalUi";

function extractUrl(response: unknown) {
  if (!response || typeof response !== "object") return "";
  const data = response as Record<string, unknown>;
  return typeof data.url === "string" ? data.url : typeof data.checkout_url === "string" ? data.checkout_url : "";
}

export function Admin() {
  const { currentOrganization, currentWorkspace, entitlements } = useAuth();
  const [billingMessage, setBillingMessage] = useState("");
  const entitlementEntries = Object.entries(entitlements).slice(0, 8);

  async function redirectWith(loader: () => Promise<unknown>) {
    setBillingMessage("");
    try {
      const response = await loader();
      const url = extractUrl(response);
      if (!url) {
        setBillingMessage("Billing is not configured yet.");
        return;
      }
      window.location.assign(url);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Billing is not configured yet.";
      setBillingMessage(message.toLowerCase().includes("stripe") ? "Billing is not configured yet." : message);
    }
  }

  return (
    <div className="min-h-screen" style={{ background: BG }}>
      <header className="bg-[#FFFEFA] border-b border-[rgba(16,35,27,0.12)] px-8 py-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <h1 className="text-2xl font-bold text-[#10231B]">Admin</h1>
            <span className="px-2.5 py-1 bg-[#F6F4EE] border border-[rgba(16,35,27,0.12)] rounded text-xs font-medium text-[#68776F]">
              Settings
            </span>
          </div>
        </div>
      </header>
      <div className="p-8">
        <div className="bg-[#FFFEFA] border border-[rgba(16,35,27,0.12)] rounded-xl p-8">
          <h2 className="text-lg font-bold text-[#10231B] mb-4">System Administration</h2>
          <div className="grid lg:grid-cols-3 gap-4">
            <AdminMetric label="Organization" value={currentOrganization?.name || "Unavailable"} />
            <AdminMetric label="Workspace" value={currentWorkspace?.name || "Evaluation workspace"} />
            <AdminMetric label="Role" value={currentOrganization?.role || "member"} />
            <AdminMetric label="Plan" value={currentOrganization?.plan || "free"} />
            <AdminMetric label="Subscription" value={currentOrganization?.subscription_status || "inactive"} />
            <AdminMetric label="Billing" value={billingMessage || "Available when backend returns a billing URL"} />
          </div>

          <div className="mt-8 border-t border-[rgba(16,35,27,0.12)] pt-6">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h3 className="text-sm font-bold text-[#10231B]">Billing</h3>
                <p className="text-sm text-[#68776F] mt-1">Upgrade and billing management use the live backend billing endpoints.</p>
              </div>
              <div className="flex items-center gap-2">
                <PortalButton variant="secondary" onClick={() => redirectWith(apiClient.billing.createPortalSession)}>Manage billing</PortalButton>
                <PortalButton onClick={() => redirectWith(apiClient.billing.createCheckoutSession)}>Upgrade</PortalButton>
              </div>
            </div>
            {billingMessage ? <div className="mt-4"><InlineState title={billingMessage} /></div> : null}
          </div>

          <div className="mt-8 border-t border-[rgba(16,35,27,0.12)] pt-6">
            <h3 className="text-sm font-bold text-[#10231B] mb-3">Entitlements</h3>
            {entitlementEntries.length ? (
              <div className="grid md:grid-cols-2 gap-2">
                {entitlementEntries.map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between rounded-md border border-[rgba(16,35,27,0.1)] bg-[#F6F4EE] px-3 py-2">
                    <span className="text-[12px] text-[#68776F]">{key}</span>
                    <span className="text-[12px] font-semibold text-[#10231B]">{String(value)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[#68776F]">No entitlement data returned for this session.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
function AdminMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[rgba(16,35,27,0.1)] bg-[#F6F4EE] p-4">
      <div className="text-[11px] font-semibold uppercase tracking-widest text-[#68776F]">{label}</div>
      <div className="mt-2 text-sm font-semibold text-[#10231B]">{value}</div>
    </div>
  );
}
