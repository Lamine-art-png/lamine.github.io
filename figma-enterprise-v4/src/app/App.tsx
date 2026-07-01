import { useEffect, useState } from "react";
import { RouterProvider } from "react-router";
import { AuthProvider, useAuth } from "./auth/AuthProvider";
import { AuthScreen } from "./components/AuthScreen";
import { PricingPage } from "./components/ProductShell";
import { VerifyEmailPage } from "./components/VerifyEmail";

function PortalBootFallback({ reason }: { reason?: string }) {
  return (
    <div className="min-h-screen bg-[#F6F4EE] px-6 py-12 text-[#10231B]">
      <div className="mx-auto max-w-[760px] rounded-2xl border border-[#D6DDD0] bg-[#FFFDF8] p-8 shadow-[0_20px_60px_rgba(16,35,27,0.08)]">
        <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#2D6A4F]">AGRO-AI Enterprise Portal</div>
        <h1 className="mt-3 text-[30px] font-semibold tracking-tight">Portal recovery mode</h1>
        <p className="mt-3 text-[14px] leading-7 text-[#65736A]">
          The portal booted safely, but one workspace route failed to load. This screen prevents a white page while the route is repaired.
        </p>
        {reason ? (
          <pre className="mt-4 overflow-auto rounded-xl border border-[#E2D8C8] bg-[#F6F4EE] p-4 text-[12px] leading-5 text-[#7A2E0E]">{reason}</pre>
        ) : null}
        <div className="mt-6 flex flex-wrap gap-3">
          <a href="/" className="rounded-lg bg-[#10231B] px-4 py-2 text-[13px] font-medium text-white">Reload portal</a>
          <button
            type="button"
            onClick={() => {
              window.localStorage.removeItem("agroai_access_token");
              window.location.href = "/";
            }}
            className="rounded-lg border border-[#D6DDD0] bg-white px-4 py-2 text-[13px] font-medium text-[#10231B]"
          >
            Clear session and sign in again
          </button>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AuthenticatedApp />
    </AuthProvider>
  );
}

function AuthenticatedApp() {
  const { isAuthenticated, isLoading } = useAuth();
  const [router, setRouter] = useState<any>(null);
  const [routerError, setRouterError] = useState("");

  useEffect(() => {
    if (!isAuthenticated) {
      setRouter(null);
      setRouterError("");
      return;
    }

    let mounted = true;
    import("./routes")
      .then((module) => {
        if (mounted) {
          setRouter(() => module.router);
          setRouterError("");
        }
      })
      .catch((error) => {
        console.error("AGRO-AI portal route boot failed", error);
        if (mounted) {
          setRouter(null);
          setRouterError(error instanceof Error ? `${error.name}: ${error.message}` : String(error));
        }
      });

    return () => {
      mounted = false;
    };
  }, [isAuthenticated]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F6F4EE] text-[#68776F] text-sm">
        Loading session
      </div>
    );
  }

  if (window.location.pathname === "/verify-email") {
    return <VerifyEmailPage />;
  }

  if (window.location.pathname === "/pricing" && !isAuthenticated) {
    return <PricingPage />;
  }

  if (!isAuthenticated) {
    return <AuthScreen />;
  }

  if (routerError) {
    return <PortalBootFallback reason={routerError} />;
  }

  if (!router) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F6F4EE] text-[#68776F] text-sm">
        Loading portal
      </div>
    );
  }

  return <RouterProvider router={router} />;
}
