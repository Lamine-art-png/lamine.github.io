import { FormEvent, useEffect, useMemo, useState } from "react";
import { Loader2, ShieldCheck, Users } from "lucide-react";
import { apiClient } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { useLocale } from "../hooks/useLocale";
import { LanguageSelector } from "./LanguageSelector";
import { LocalizedTemplate } from "./LocalizedTemplate";
import { BG, BORDER, MUTED, PortalButton, StatusBadge, SURFACE, TEXT } from "./portalUi";

const TERMS_VERSION = "2026-07-03";
const PRIVACY_VERSION = "2026-07-03";
const ROLE_LABELS: Record<string, string> = { admin: "Admin", manager: "Manager", operator: "Operator", viewer: "Viewer" };

type Preview = { organization_name?: string; role?: string; email?: string; account_exists?: boolean };
type Stage = "loading" | "ready" | "working" | "accepted" | "unavailable";

export function AcceptInvitationPage() {
  const { user, isAuthenticated, login, logout, adoptSession } = useAuth();
  const { effectiveLocale } = useLocale();
  const token = useMemo(() => new URLSearchParams(window.location.search).get("token") || "", []);
  const [stage, setStage] = useState<Stage>(token ? "loading" : "unavailable");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState(token ? "" : "This invitation link is invalid or has already been used.");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [termsAccepted, setTermsAccepted] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    apiClient.team.previewInvitation(token)
      .then((response) => {
        if (cancelled) return;
        setPreview(response as Preview);
        setStage("ready");
      })
      .catch((cause) => {
        if (cancelled) return;
        setError(cause instanceof Error ? cause.message : "This invitation link is invalid or has already been used.");
        setStage("unavailable");
      });
    return () => { cancelled = true; };
  }, [token]);

  const invitedEmail = (preview?.email || "").toLowerCase();
  const signedInAsInvitee = isAuthenticated && (user?.email || "").toLowerCase() === invitedEmail;
  const signedInAsOther = isAuthenticated && !signedInAsInvitee;
  const legalLang = encodeURIComponent(effectiveLocale);
  const linkClass = "font-semibold text-[#234224] underline underline-offset-2";
  const termsLink = <a href={`https://agroai-pilot.com/terms-of-service?lang=${legalLang}`} target="_blank" rel="noreferrer" className={linkClass}>AGRO-AI Terms of Service</a>;
  const privacyLink = <a href={`https://agroai-pilot.com/privacy-policy?lang=${legalLang}`} target="_blank" rel="noreferrer" className={linkClass}>Privacy Policy</a>;

  const invitedEmailNode = <span className="font-medium" style={{ color: TEXT }}>{invitedEmail}</span>;
  const currentEmailNode = <span className="font-medium">{user?.email}</span>;

  const finish = async (response: unknown) => {
    await adoptSession(response as Record<string, unknown>);
    window.history.replaceState({}, document.title, "/team");
    setStage("accepted");
    window.location.assign("/team");
  };

  const run = async (action: () => Promise<unknown>) => {
    setError("");
    setStage("working");
    try {
      await finish(await action());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The invitation could not be accepted.");
      setStage("ready");
    }
  };

  const acceptSignedIn = () => run(() => apiClient.team.acceptInvitation(token));

  const signInAndAccept = (event: FormEvent) => {
    event.preventDefault();
    run(async () => {
      await login(invitedEmail, password);
      return apiClient.team.acceptInvitation(token);
    });
  };

  const createAndAccept = (event: FormEvent) => {
    event.preventDefault();
    run(() => apiClient.team.acceptInvitationNewAccount({
      token, name: name.trim(), password, terms_accepted: termsAccepted,
      terms_version: TERMS_VERSION, privacy_version: PRIVACY_VERSION, locale: effectiveLocale,
    }));
  };

  const busy = stage === "working" || stage === "accepted";
  const input = "mt-1 h-10 w-full rounded-lg px-3 text-[13px]";
  const inputStyle = { background: BG, border: `1px solid ${BORDER}`, color: TEXT };

  return (
    <div className="min-h-screen grid lg:grid-cols-[0.95fr_1.05fr]" style={{ background: BG }}>
      <section className="flex flex-col justify-between gap-8 px-8 py-8 lg:px-12 lg:py-12 bg-[#061D15]">
        <div className="flex items-center gap-2 text-white font-semibold text-[15px]"><ShieldCheck className="h-4 w-4 text-[#DCEF8B]" />AGRO-AI</div>
        <div className="max-w-md">
          <div className="text-[11px] uppercase tracking-widest font-semibold text-white/35 mb-4">Team invitation</div>
          <h1 className="text-4xl font-bold tracking-tight text-white mb-5">Join your team on AGRO-AI</h1>
          <p className="text-sm leading-6 text-white/60">Invitations are single-use and expire. Your access is limited to the organization and role you were invited to.</p>
        </div>
        <div className="text-[11px] leading-5 text-white/35">Secure workspace access.</div>
      </section>

      <main className="flex items-center justify-center px-6 py-10">
        <section className="w-full max-w-[460px] rounded-xl p-6 shadow-[0_18px_60px_rgba(16,35,27,0.08)]" style={{ background: SURFACE, border: `1px solid ${BORDER}` }}>
          <div className="mb-4 flex justify-end"><div className="w-full max-w-[280px]"><LanguageSelector compact /></div></div>

          {stage === "loading" ? <div className="flex items-center gap-2 text-[14px]" style={{ color: MUTED }}><Loader2 className="h-4 w-4 animate-spin" />Checking your invitation…</div> : null}

          {stage === "unavailable" ? (
            <>
              <StatusBadge label="Action needed" tone="warn" />
              <h2 className="mt-4 text-[22px] font-semibold tracking-tight" style={{ color: TEXT }}>Invitation unavailable</h2>
              <p className="mt-3 text-[14px] leading-relaxed" style={{ color: MUTED }}>{error}</p>
              <div className="mt-6"><PortalButton onClick={() => window.location.assign("/")}>Go to AGRO-AI</PortalButton></div>
            </>
          ) : null}

          {preview && stage !== "unavailable" ? (
            <>
              <div className="flex items-start gap-3">
                <Users className="mt-1 h-5 w-5 text-[#2D6A4F]" />
                <div>
                  <h2 className="text-[20px] font-semibold tracking-tight" style={{ color: TEXT }}>{preview.organization_name}</h2>
                  <p className="mt-1 text-[13px]" style={{ color: MUTED }}>
                    <LocalizedTemplate template="Invitation for {email} with the {role} role." values={{ email: invitedEmailNode, role: ROLE_LABELS[preview.role || ""] || preview.role }} />
                  </p>
                </div>
              </div>
              {error ? <div className="mt-4 rounded-md border border-[#E7C9B5] bg-[#FFF7F0] px-3 py-2 text-[13px] text-[#8A3B12]" role="alert">{error}</div> : null}

              {signedInAsInvitee ? (
                <div className="mt-6"><PortalButton onClick={acceptSignedIn} disabled={busy}>{busy ? "Joining…" : "Accept invitation"}</PortalButton></div>
              ) : null}

              {signedInAsOther ? (
                <div className="mt-6 space-y-3">
                  <p className="text-[13px] leading-6" style={{ color: MUTED }}>
                    <LocalizedTemplate template="You are signed in as {current}. Sign out and continue as {invited} to accept this invitation." values={{ current: currentEmailNode, invited: invitedEmailNode }} />
                  </p>
                  <PortalButton variant="secondary" onClick={() => void logout()}>Sign out and continue</PortalButton>
                </div>
              ) : null}

              {!isAuthenticated && preview.account_exists ? (
                <form className="mt-6 space-y-4" onSubmit={signInAndAccept}>
                  <p className="text-[13px] leading-6" style={{ color: MUTED }}>Sign in to your AGRO-AI account to accept.</p>
                  <label className="block text-[12px]" style={{ color: MUTED }}>Email<input value={invitedEmail} readOnly className={input} style={inputStyle} /></label>
                  <label className="block text-[12px]" style={{ color: MUTED }}>Password<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} className={input} style={inputStyle} required /></label>
                  <PortalButton type="submit" disabled={busy || !password}>{busy ? "Joining…" : "Sign in and accept"}</PortalButton>
                  <p className="text-[12px]" style={{ color: MUTED }}><a href="/recover-account" className="underline underline-offset-2">Forgot your password?</a></p>
                </form>
              ) : null}

              {!isAuthenticated && preview.account_exists === false ? (
                <form className="mt-6 space-y-4" onSubmit={createAndAccept}>
                  <p className="text-[13px] leading-6" style={{ color: MUTED }}>Create your AGRO-AI account to accept.</p>
                  <label className="block text-[12px]" style={{ color: MUTED }}>Email<input value={invitedEmail} readOnly className={input} style={inputStyle} /></label>
                  <label className="block text-[12px]" style={{ color: MUTED }}>Full name<input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" className={input} style={inputStyle} required /></label>
                  <label className="block text-[12px]" style={{ color: MUTED }}>Password<input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} className={input} style={inputStyle} minLength={12} required /></label>
                  <p className="-mt-2 text-[11px] leading-5" style={{ color: MUTED }}>Use at least 12 characters. Do not include your email name.</p>
                  <label className="flex cursor-pointer items-start gap-3 rounded-xl border p-4" style={{ borderColor: BORDER, background: "#fff" }}>
                    <input type="checkbox" checked={termsAccepted} onChange={(event) => setTermsAccepted(event.target.checked)} className="mt-1 h-4 w-4" required />
                    <span className="text-[11px] leading-5 text-[#52645A]"><LocalizedTemplate template="I agree to the {terms} and acknowledge the {privacy}." values={{ terms: termsLink, privacy: privacyLink }} /></span>
                  </label>
                  <PortalButton type="submit" disabled={busy || !termsAccepted || !name.trim() || password.length < 12}>{busy ? "Joining…" : "Create account and join"}</PortalButton>
                </form>
              ) : null}
            </>
          ) : null}
        </section>
      </main>
    </div>
  );
}
