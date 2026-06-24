import { useEffect, useState } from "react";
import { API_BASE, apiClient } from "../api/client";
import { ProviderStatusList } from "../components/ProviderStatusList";
import { BackendBadge } from "../components/StatusBadge";
import { useCommandStore } from "../state/commandStore";
import type { BillingStatus, MeResponse, SaaSWorkspace } from "../api/contracts";

export function SettingsPage() {
  const backend = useCommandStore((s) => s.backend);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [workspaces, setWorkspaces] = useState<SaaSWorkspace[]>([]);
  const [billingMessage, setBillingMessage] = useState<string | null>(null);
  const [accountPhase, setAccountPhase] = useState<"loading" | "ready" | "locked" | "error">("loading");
  const [billingBusy, setBillingBusy] = useState(false);

  useEffect(() => {
    async function loadAccount() {
      const meResult = await apiClient.getMe();
      if (!meResult.ok || !meResult.data) {
        setAccountPhase(meResult.status === 401 ? "locked" : "error");
        return;
      }
      setMe(meResult.data);
      const orgId = meResult.data.current_organization?.id;
      const [billingResult, workspaceResult] = await Promise.all([
        apiClient.getBillingStatus(orgId),
        apiClient.getWorkspaces(),
      ]);
      if (billingResult.ok && billingResult.data) setBilling(billingResult.data);
      if (workspaceResult.ok && workspaceResult.data) setWorkspaces(workspaceResult.data.workspaces);
      setAccountPhase("ready");
    }
    void loadAccount();
  }, []);

  async function openCheckout(plan: "pilot" | "pro") {
    const orgId = me?.current_organization?.id;
    if (!orgId) {
      setBillingMessage("Sign in to manage a plan.");
      return;
    }
    setBillingBusy(true);
    const result = await apiClient.createCheckoutSession(orgId, plan);
    setBillingBusy(false);
    if (result.ok && result.data?.checkout_url) {
      window.location.assign(result.data.checkout_url);
      return;
    }
    setBillingMessage("Checkout is not configured for this environment.");
  }

  async function openPortal() {
    const orgId = me?.current_organization?.id;
    if (!orgId) {
      setBillingMessage("Sign in to open billing.");
      return;
    }
    setBillingBusy(true);
    const result = await apiClient.createBillingPortalSession(orgId);
    setBillingBusy(false);
    if (result.ok && result.data?.portal_url) {
      window.location.assign(result.data.portal_url);
      return;
    }
    setBillingMessage("Billing portal is not available for this organization yet.");
  }

  return (
    <div className="stack">
      <section className="card panel">
        <p className="eyebrow">Account</p>
        <h2>Organization and plan</h2>
        {accountPhase === "loading" && <p className="muted">Loading account state...</p>}
        {accountPhase === "locked" && <p className="entry-message">Sign in to manage organizations, workspaces, and billing.</p>}
        {accountPhase === "error" && <p className="entry-message">Account state is unavailable. Evaluation workspace remains available.</p>}
        <dl className="brief-def">
          <div>
            <dt>User</dt>
            <dd>{me?.user.email ?? "Not signed in"}</dd>
          </div>
          <div>
            <dt>Organization</dt>
            <dd>{me?.current_organization?.name ?? "Evaluation workspace"}</dd>
          </div>
          <div>
            <dt>Plan</dt>
            <dd>{billing ? `${billing.plan} · ${billing.subscription_status}` : "Evaluation"}</dd>
          </div>
          <div>
            <dt>Workspaces</dt>
            <dd>{workspaces.length ? workspaces.map((workspace) => `${workspace.name} (${workspace.mode})`).join(", ") : "Representative evaluation workspace"}</dd>
          </div>
        </dl>
        <div className="entry-actions">
          <button className="btn" disabled={billingBusy || accountPhase !== "ready"} onClick={() => void openCheckout("pilot")}>Upgrade Pilot</button>
          <button className="btn" disabled={billingBusy || accountPhase !== "ready"} onClick={() => void openCheckout("pro")}>Upgrade Pro</button>
          <button className="btn ghost" disabled={billingBusy || accountPhase !== "ready"} onClick={() => void openPortal()}>Billing portal</button>
        </div>
        {billingMessage && <p className="entry-message">{billingMessage}</p>}
      </section>

      <section className="card panel">
        <p className="eyebrow">Settings</p>
        <h2>Workspace and backend</h2>
        <dl className="brief-def">
          <div>
            <dt>Environment</dt>
            <dd>Evaluation workspace · representative data</dd>
          </div>
          <div>
            <dt>API base</dt>
            <dd>
              <code className="identifier">{API_BASE}</code>
            </dd>
          </div>
          <div>
            <dt>Backend status</dt>
            <dd>
              <BackendBadge status={backend.status} detail={backend.detail} />
            </dd>
          </div>
          <div>
            <dt>Backend detail</dt>
            <dd className="value">{backend.detail}</dd>
          </div>
        </dl>
      </section>

      <section className="card panel">
        <p className="eyebrow">Provider runtime</p>
        <h2>Dynamic integration status</h2>
        <ProviderStatusList />
      </section>

      <section className="card panel">
        <p className="eyebrow">Known limitations</p>
        <h2>Evaluation transparency</h2>
        <ul className="limitations">
          <li>Workbench sessions are evaluation session storage only (in-memory); tenant persistence is future work.</li>
          <li>Authentication and tenant provisioning are API-backed; production credential vaulting remains server-side work.</li>
          <li>Representative recommendations are evaluation fallbacks and are labelled as such.</li>
          <li>Live recommendations degrade safely when provider telemetry is unavailable.</li>
        </ul>
      </section>
    </div>
  );
}
