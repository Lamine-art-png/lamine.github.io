import { createBrowserRouter } from "react-router";
import { MainLayout } from "./components/MainLayout";
import { Overview } from "./components/Overview";
import { Operations } from "./components/Operations";
import { Assurance } from "./components/Assurance";
import { Evidence } from "./components/Evidence";
import { Reports } from "./components/Reports";
import { Agents } from "./components/Agents";
import { Intelligence } from "./components/Intelligence";
import { Integrations } from "./components/Integrations";
import { DecisionWorkbench, Exceptions, Fields, Readiness, ReportFactory } from "./components/OperatorCockpit";
import { Sources } from "./components/Sources";
import { Audit } from "./components/Audit";
import { Admin, SystemHealthPage } from "./components/Admin";
import { RouteRecovery } from "./components/RouteRecovery";
import { VerifyEmailPage } from "./components/VerifyEmail";
import {
  BillingPage,
  AdminRequestsPage,
  OnboardingPage,
  PricingPage,
  ProfilePage,
  SecurityPage,
  SupportPage,
  TeamPage,
  WorkspaceSettingsPage,
} from "./components/ProductShell";

function PortalRouteError() {
  return (
    <div className="min-h-screen bg-[#F6F4EE] px-6 py-12 text-[#10231B]">
      <div className="mx-auto max-w-[720px] rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-8 shadow-[0_20px_60px_rgba(16,35,27,0.08)]">
        <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#2D6A4F]">AGRO-AI Enterprise Portal</div>
        <h1 className="mt-3 text-[30px] font-semibold tracking-tight">This workspace screen is not ready yet.</h1>
        <p className="mt-3 text-[14px] leading-7 text-[#65736A]">
          The portal recovered safely instead of showing a developer error. Continue to the operating room or sign in again.
        </p>
        <div className="mt-6 flex gap-3">
          <a href="/" className="rounded-lg bg-[#10231B] px-4 py-2 text-[13px] font-medium text-white">Continue to portal</a>
          <a href="/pricing" className="rounded-lg border border-[#D6DDD0] bg-white px-4 py-2 text-[13px] font-medium text-[#10231B]">View pricing</a>
        </div>
      </div>
    </div>
  );
}

export const router = createBrowserRouter([
  {
    path: "/verify-email",
    Component: VerifyEmailPage,
    errorElement: <PortalRouteError />,
  },
  {
    path: "/",
    Component: MainLayout,
    errorElement: <RouteRecovery />,
    children: [
      { index: true, Component: Overview },
      { path: "field-queue", Component: Overview },
      { path: "tasks", Component: Overview },
      { path: "readiness", Component: Readiness },
      { path: "fields", Component: Fields },
      { path: "exceptions", Component: Exceptions },
      { path: "decision-workbench", Component: DecisionWorkbench },
      { path: "report-factory", Component: ReportFactory },
      { path: "operations", Component: Operations },
      { path: "assurance", Component: Assurance },
      { path: "evidence", Component: Evidence },
      { path: "reports", Component: Reports },
      { path: "agents", Component: Agents },
      { path: "intelligence", Component: Intelligence },
      { path: "integrations", Component: Integrations },
      { path: "sources", Component: Sources },
      { path: "audit", Component: Audit },
      { path: "admin", Component: Admin },
      { path: "admin/system", Component: SystemHealthPage },
      { path: "admin/requests", Component: AdminRequestsPage },
      { path: "pricing", Component: PricingPage },
      { path: "profile", Component: ProfilePage },
      { path: "billing", Component: BillingPage },
      { path: "security", Component: SecurityPage },
      { path: "support", Component: SupportPage },
      { path: "settings", Component: WorkspaceSettingsPage },
      { path: "team", Component: TeamPage },
      { path: "onboarding", Component: OnboardingPage },
      { path: "*", Component: RouteRecovery },
    ],
  },
  {
    path: "*",
    element: <PortalRouteError />,
  },
]);
