import { Component, ReactNode, useEffect, useState } from "react";
import { RouterProvider } from "react-router";
import { AuthProvider, useAuth } from "./auth/AuthProvider";
import { AuthScreen } from "./components/AuthScreen";
import { PricingPage } from "./components/PricingPage";
import { VerifyEmailPage } from "./components/VerifyEmail";
import { useLocale } from "./hooks/useLocale";
import { applyLocale, t } from "./i18n";

type PortalRuntimeBoundaryState = { error: string };

function PortalBootFallback({ reason }: { reason?: string }) {
  return (
    <div className="min-h-screen bg-[#F6F4EE] px-6 py-12 text-[#10231B]">
      <div className="mx-auto max-w-[760px] rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-8 shadow-[0_20px_60px_rgba(16,35,27,0.08)]">
        <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#2D6A4F]">{t("app.recoveryEyebrow")}</div>
        <h1 className="mt-3 text-[30px] font-semibold tracking-tight">{t("app.recoveryTitle")}</h1>
        <p className="mt-3 text-[14px] leading-7 text-[#65736A]">{t("app.recoveryBody")}</p>
        {reason ? <pre className="mt-4 overflow-auto rounded-xl border border-[#E2D8C8] bg-[#F6F4EE] p-4 text-[12px] leading-5 text-[#7A2E0E]">{reason}</pre> : null}
        <div className="mt-6 flex flex-wrap gap-3">
          <a href="/" className="rounded-lg bg-[#10231B] px-4 py-2 text-[13px] font-medium text-white">{t("app.reloadPortal")}</a>
          <button type="button" onClick={() => { window.localStorage.removeItem("agroai_access_token"); window.location.href = "/"; }} className="rounded-lg border border-[#D6DDD0] bg-white px-4 py-2 text-[13px] font-medium text-[#10231B]">{t("app.clearSession")}</button>
        </div>
      </div>
    </div>
  );
}

class PortalRuntimeBoundary extends Component<{ children: ReactNode }, PortalRuntimeBoundaryState> {
  state: PortalRuntimeBoundaryState = { error: "" };
  static getDerivedStateFromError(error: unknown): PortalRuntimeBoundaryState { return { error: error instanceof Error ? `${error.name}: ${error.message}` : String(error) }; }
  componentDidCatch(error: unknown) { console.error("AGRO-AI portal render failed", error); }
  render() { if (this.state.error) return <PortalBootFallback reason={this.state.error} />; return this.props.children; }
}

export default function App() {
  useEffect(() => { applyLocale(); }, []);
  return <PortalRuntimeBoundary><AuthProvider><AuthenticatedApp /></AuthProvider></PortalRuntimeBoundary>;
}

function AuthenticatedApp() {
  const { isAuthenticated, isLoading } = useAuth();
  const { locale } = useLocale();
  const [router, setRouter] = useState<any>(null);
  const [routerError, setRouterError] = useState("");

  useEffect(() => {
    applyLocale(locale);
  }, [locale]);

  useEffect(() => {
    if (!isAuthenticated) { setRouter(null); setRouterError(""); return; }
    let mounted = true;
    import("./routes").then((module) => { if (mounted) { setRouter(() => module.router); setRouterError(""); } }).catch((error) => { console.error("AGRO-AI portal route boot failed", error); if (mounted) { setRouter(null); setRouterError(error instanceof Error ? `${error.name}: ${error.message}` : String(error)); } });
    return () => { mounted = false; };
  }, [isAuthenticated]);

  if (isLoading) return <div className="min-h-screen flex items-center justify-center bg-[#F6F4EE] text-[#68776F] text-sm">{t("app.loadingSession", locale)}</div>;
  if (window.location.pathname === "/verify-email") return <VerifyEmailPage />;
  if (window.location.pathname === "/pricing" && !isAuthenticated) return <PricingPage />;
  if (!isAuthenticated) return <AuthScreen />;
  if (routerError) return <PortalBootFallback reason={routerError} />;
  if (!router) return <div className="min-h-screen flex items-center justify-center bg-[#F6F4EE] text-[#68776F] text-sm">{t("app.loadingPortal", locale)}</div>;
  return <RouterProvider router={router} />;
}
