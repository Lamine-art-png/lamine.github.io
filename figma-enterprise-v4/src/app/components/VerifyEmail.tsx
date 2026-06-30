import { useEffect, useMemo, useState } from "react";
import { apiClient } from "../api/client";
import { BG, BORDER, GREEN, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

type VerificationState = "checking" | "success" | "error";

export function VerifyEmailPage() {
  const token = useMemo(() => new URLSearchParams(window.location.search).get("token") || "", []);
  const [state, setState] = useState<VerificationState>(token ? "checking" : "error");
  const [message, setMessage] = useState(token ? "Checking verification link." : "Verification link is missing a token.");

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    apiClient.auth
      .confirmEmailVerification({ token })
      .then((response) => {
        if (cancelled) return;
        const payload = response && typeof response === "object" ? (response as Record<string, unknown>) : {};
        setState("success");
        setMessage(typeof payload.message === "string" ? payload.message : "Verification link received.");
      })
      .catch((error) => {
        if (cancelled) return;
        setState("error");
        setMessage(error instanceof Error ? error.message : "Verification link could not be processed.");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="min-h-screen grid lg:grid-cols-[0.95fr_1.05fr]" style={{ background: BG }}>
      <section className="flex flex-col justify-between px-8 py-8 lg:px-12 lg:py-12 bg-[#061D15]">
        <div>
          <div className="text-white font-semibold text-[15px]">AGRO-AI</div>
          <div className="mt-1 text-[11px] text-white/45">Enterprise Portal</div>
        </div>
        <div className="max-w-md">
          <div className="text-[11px] uppercase tracking-widest font-semibold text-white/35 mb-4">
            Account security
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-white mb-5">Email verification</h1>
          <p className="text-sm leading-6 text-white/58">
            AGRO-AI keeps account actions inside the authenticated organization workflow.
          </p>
        </div>
        <div className="text-[11px] leading-5 text-white/35">Secure workspace access.</div>
      </section>

      <main className="flex items-center justify-center px-6 py-10">
        <section className="w-full max-w-[460px] rounded-xl p-6 shadow-[0_18px_60px_rgba(16,35,27,0.08)]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <StatusBadge label={state === "checking" ? "Checking" : state === "success" ? "Received" : "Action needed"} tone={state === "error" ? "warn" : "good"} />
          <h2 className="mt-4 text-[24px] font-semibold tracking-tight" style={{ color: TEXT }}>
            {state === "checking" ? "Checking your link" : state === "success" ? "Verification request received" : "Verification link unavailable"}
          </h2>
          <p className="mt-3 text-[14px] leading-relaxed" style={{ color: MUTED }}>{message}</p>
          <div className="mt-6 flex flex-wrap gap-3">
            <PortalButton onClick={() => window.location.assign("/")}>Return to portal</PortalButton>
            <PortalButton variant="secondary" onClick={() => window.location.assign("/security")}>Security settings</PortalButton>
          </div>
          <div className="mt-6 rounded-lg p-4 text-[12px] leading-relaxed" style={{ background: BG, border: `1px solid ${BORDER}`, color: GREEN }}>
            For your protection, this page does not expose token details or account internals.
          </div>
        </section>
      </main>
    </div>
  );
}
