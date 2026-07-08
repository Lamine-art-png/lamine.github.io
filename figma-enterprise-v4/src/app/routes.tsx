import type { ComponentType } from "react";
import { createBrowserRouter, Navigate } from "react-router";
import { MainLayout } from "./components/MainLayout";
import { RouteRecovery } from "./components/RouteRecovery";
import { VerifyEmailPage } from "./components/VerifyEmail";
import { useLocale } from "./hooks/useLocale";

function PortalHome() {
  const { t } = useLocale();
  const params = new URLSearchParams(window.location.search || "");
  const connectorReturn = Boolean(params.get("connector") || params.get("provider") || params.get("connection_id"));

  if (connectorReturn) return <Navigate to={`/integrations${window.location.search}`} replace />;

  return <div className="min-h-full px-7 py-7" style={{ background: "#F6F4EE" }}><section className="rounded-2xl p-7 shadow-[0_18px_60px_rgba(16,35,27,0.08)]" style={{ background: "#FFFDF8", border: "1px solid #D6DDD0" }}><div className="text-[12px] font-semibold uppercase tracking-[0.18em]" style={{ color: "#2D6A4F" }}>{t("home.eyebrow")}</div><h1 className="mt-3 text-[32px] font-semibold tracking-tight" style={{ color: "#10231B" }}>{t("home.title")}</h1><p className="mt-3 max-w-3xl text-[14px] leading-7" style={{ color: "#65736A" }}>{t("home.body")}</p><div className="mt-6 flex flex-wrap gap-3"><a href="/intelligence" className="rounded-lg px-4 py-2 text-[13px] font-semibold text-white" style={{ background: "#0D2B1E" }}>{t("home.openAsk")}</a><a href="/evidence" className="rounded-lg px-4 py-2 text-[13px] font-semibold" style={{ background: "#F6F4EE", color: "#10231B", border: "1px solid #D6DDD0" }}>{t("home.reviewEvidence")}</a><a href="/readiness" className="rounded-lg px-4 py-2 text-[13px] font-semibold" style={{ background: "#F6F4EE", color: "#10231B", border: "1px solid #D6DDD0" }}>{t("home.checkReadiness")}</a></div></section></div>;
}

function PortalRouteError() {
  const { t } = useLocale();
  return <div className="min-h-screen bg-[#F6F4EE] px-6 py-12 text-[#10231B]"><div className="mx-auto max-w-[720px] rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-8 shadow-[0_20px_60px_rgba(16,35,27,0.08)]"><div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#2D6A4F]">{t("app.recoveryEyebrow")}</div><h1 className="mt-3 text-[30px] font-semibold tracking-tight">{t("routeRecovery.title")}</h1><p className="mt-3 text-[14px] leading-7 text-[#65736A]">{t("routeRecovery.body")}</p><div className="mt-6 flex gap-3"><a href="/" className="rounded-lg bg-[#10231B] px-4 py-2 text-[13px] font-medium text-white">{t("routeRecovery.continue")}</a><a href="/intelligence" className="rounded-lg border border-[#D6DDD0] bg-white px-4 py-2 text-[13px] font-medium text-[#10231B]">{t("routeRecovery.openAsk")}</a><a href="/settings" className="rounded-lg border border-[#D6DDD0] bg-white px-4 py-2 text-[13px] font-medium text-[#10231B]">{t("routeRecovery.settings")}</a></div></div></div>;
}

const lazyComponent = (loader: () => Promise<Record<string, unknown>>, exportName: string) => async () => {
  const module = await loader();
  return { Component: module[exportName] as ComponentType };
};

export const router = createBrowserRouter([
  { path: "/verify-email", Component: VerifyEmailPage, errorElement: <PortalRouteError /> },
  {
    path: "/",
    Component: MainLayout,
    errorElement: <RouteRecovery />,
    children: [
      { index: true, lazy: lazyComponent(() => import("./components/Overview"), "Overview") },
      { path: "field-queue", lazy: lazyComponent(() => import("./components/Overview"), "Overview") },
      { path: "tasks", lazy: lazyComponent(() => import("./components/Overview"), "Overview") },
      { path: "readiness", lazy: lazyComponent(() => import("./components/OperatorCockpit"), "Readiness") },
      { path: "fields", lazy: lazyComponent(() => import("./components/OperatorCockpit"), "Fields") },
      { path: "exceptions", lazy: lazyComponent(() => import("./components/OperatorCockpit"), "Exceptions") },
      { path: "decision-workbench", lazy: lazyComponent(() => import("./components/OperatorCockpit"), "DecisionWorkbench") },
      { path: "report-factory", lazy: lazyComponent(() => import("./components/OperatorCockpit"), "ReportFactory") },
      { path: "operations", lazy: lazyComponent(() => import("./components/Operations"), "Operations") },
      { path: "assurance", lazy: lazyComponent(() => import("./components/Assurance"), "Assurance") },
      { path: "evidence", lazy: lazyComponent(() => import("./components/Evidence"), "Evidence") },
      { path: "reports", lazy: lazyComponent(() => import("./components/MonetizedReportsV2"), "MonetizedReportsV2") },
      { path: "agents", lazy: lazyComponent(() => import("./components/Agents"), "Agents") },
      { path: "intelligence", lazy: lazyComponent(() => import("./components/Intelligence"), "Intelligence") },
      { path: "integrations", lazy: lazyComponent(() => import("./components/IntegrationsV3"), "IntegrationsV3") },
      { path: "sources", lazy: lazyComponent(() => import("./components/Sources"), "Sources") },
      { path: "audit", lazy: lazyComponent(() => import("./components/Audit"), "Audit") },
      { path: "admin", lazy: lazyComponent(() => import("./components/Admin"), "Admin") },
      { path: "admin/system", lazy: lazyComponent(() => import("./components/Admin"), "SystemHealthPage") },
      { path: "admin/requests", lazy: lazyComponent(() => import("./components/MonetizedRequestsV2"), "MonetizedRequestsV2") },
      { path: "pricing", lazy: lazyComponent(() => import("./components/PricingPage"), "PricingPage") },
      { path: "profile", lazy: lazyComponent(() => import("./components/ProductShell"), "ProfilePage") },
      { path: "billing", lazy: lazyComponent(() => import("./components/BillingPageV2"), "BillingPageV2") },
      { path: "security", lazy: lazyComponent(() => import("./components/ProductShell"), "SecurityPage") },
      { path: "support", lazy: lazyComponent(() => import("./components/SupportPage"), "SupportPage") },
      { path: "settings", lazy: lazyComponent(() => import("./components/SettingsPage"), "SettingsPage") },
      { path: "team", lazy: lazyComponent(() => import("./components/MonetizedTeamV2"), "MonetizedTeamV2") },
      { path: "onboarding", lazy: lazyComponent(() => import("./components/ProductShell"), "OnboardingPage") },
      { path: "*", Component: RouteRecovery },
    ],
  },
  { path: "*", element: <PortalRouteError /> },
]);
