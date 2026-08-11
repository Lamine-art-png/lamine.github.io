import { useEffect, useMemo, useState } from "react";
import { Code2, ShieldCheck } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { BG, BORDER, GREEN, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type VerificationState = "checking" | "success" | "error";

export function VerifyEmailPage() {
  const { confirmVerification } = useAuth();
  const query = useMemo(() => new URLSearchParams(window.location.search), []);
  const token = useMemo(() => query.get("token") || "", [query]);
  const platformFlow = useMemo(() => query.get("product") === "platform_api", [query]);
  const platformHostname = window.location.hostname.toLowerCase() === "platform.agroai-pilot.com";
  const returnPath = platformFlow ? (platformHostname ? "/" : "/platform") : "/";
  const settingsPath = platformFlow ? (platformHostname ? "/settings" : "/platform/settings") : "/security";
  const [state, setState] = useState<VerificationState>(token ? "checking" : "error");
  const [message, setMessage] = useState(token ? "Checking verification link." : "Verification link is missing a token.");

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    confirmVerification(token)
      .then(() => {
        if (cancelled) return;
        setState("success");
        setMessage(platformFlow
          ? "Your verified organization account is active. Continue to the Platform API application and access state."
          : "Your email and organization access have been verified. You are signed in.");
        const nextSearch = platformFlow ? "?product=platform_api" : "";
        window.history.replaceState({}, document.title, `${window.location.pathname}${nextSearch}`);
      })
      .catch((error) => {
        if (cancelled) return;
        setState("error");
        setMessage(error instanceof Error ? error.message : "Verification link could not be processed.");
      });
    return () => { cancelled = true; };
  }, [confirmVerification, platformFlow, token]);

  return (
    <div className="min-h-screen grid lg:grid-cols-[0.95fr_1.05fr]" style={{ background: BG }}>
      <section className="flex flex-col justify-between px-8 py-8 lg:px-12 lg:py-12 bg-[#061D15]">
        <div>
          <div className="flex items-center gap-2 text-white font-semibold text-[15px]">
            {platformFlow ? <Code2 className="h-4 w-4 text-[#DCEF8B]" /> : <ShieldCheck className="h-4 w-4 text-[#DCEF8B]" />}
            AGRO-AI
          </div>
          <div className="mt-1 text-[11px] text-white/45">{platformFlow ? "Platform API" : "Enterprise Portal"}</div>
        </div>
        <div className="max-w-md">
          <div className="text-[11px] uppercase tracking-widest font-semibold text-white/35 mb-4">
            {platformFlow ? "Developer account security" : "Account security"}
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-white mb-5">Email verification</h1>
          <p className="text-sm leading-6 text-white/58">
            {platformFlow
              ? "AGRO-AI verifies the organization account before the separate Platform API enrollment review."
              : "AGRO-AI keeps account actions inside the authenticated organization workflow."}
          </p>
        </div>
        <div className="text-[11px] leading-5 text-white/35">
          {platformFlow ? "Verified account. Reviewed API enrollment." : "Secure workspace access."}
        </div>
      </section>

      <main className="flex items-center justify-center px-6 py-10">
        <section className="w-full max-w-[460px] rounded-xl p-6 shadow-[0_18px_60px_rgba(16,35,27,0.08)]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <StatusBadge label={state === "checking" ? "Checking" : state === "success" ? "Verified" : "Action needed"} tone={state === "error" ? "warn" : "good"} />
          <h2 className="mt-4 text-[24px] font-semibold tracking-tight" style={{ color: TEXT }}>
            {state === "checking" ? "Checking your link" : state === "success" ? "Email verified" : "Verification link unavailable"}
          </h2>
          <p className="mt-3 text-[14px] leading-relaxed" style={{ color: MUTED }}>{message}</p>
          <div className="mt-6 flex flex-wrap gap-3">
            <PortalButton onClick={() => window.location.assign(returnPath)} disabled={state === "checking"}>
              {platformFlow ? "Continue to Platform API" : "Return to portal"}
            </PortalButton>
            {state === "success" ? <PortalButton variant="secondary" onClick={() => window.location.assign(settingsPath)}>Security settings</PortalButton> : null}
          </div>
          <div className="mt-6 rounded-lg p-4 text-[12px] leading-relaxed" style={{ background: BG, border: `1px solid ${BORDER}`, color: GREEN }}>
            The single-use token is removed from browser history after successful verification. This page never exposes token details or account internals.
          </div>
        </section>
      </main>
    </div>
  );
}
