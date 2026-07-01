import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, ShieldAlert } from "lucide-react";
import { apiClient } from "../api/client";
import logoImg from "../../imports/agro-ai-logo-1.png";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import { Button } from "./ui/button";

type VerifyState = "loading" | "success" | "error";

export function VerifyEmailPage() {
  const token = useMemo(() => new URLSearchParams(window.location.search).get("token") || "", []);
  const [state, setState] = useState<VerifyState>(token ? "loading" : "error");
  const [message, setMessage] = useState(token ? "Confirming your secure AGRO-AI workspace access." : "Verification link expired or invalid.");
  const [requestEmail, setRequestEmail] = useState("");
  const [resendMessage, setResendMessage] = useState("");
  const [isResending, setIsResending] = useState(false);

  useEffect(() => {
    if (!token) return;
    let active = true;
    apiClient.auth.confirmEmailVerification({ token })
      .then(() => {
        if (!active) return;
        setState("success");
        setMessage("Email verified. Your AGRO-AI workspace is ready.");
      })
      .catch((error) => {
        if (!active) return;
        setState("error");
        setMessage(error instanceof Error ? error.message : "Verification link expired or invalid.");
      });
    return () => {
      active = false;
    };
  }, [token]);

  async function requestNewLink() {
    if (!requestEmail) {
      setResendMessage("Enter the email address used for your AGRO-AI account.");
      return;
    }
    setIsResending(true);
    setResendMessage("");
    try {
      const response = await apiClient.auth.requestEmailVerification({ email: requestEmail }) as Record<string, unknown>;
      setResendMessage(String(response.message || "If an account exists, we sent a new verification email."));
    } catch (error) {
      setResendMessage(error instanceof Error ? error.message : "Unable to request a new verification email.");
    } finally {
      setIsResending(false);
    }
  }

  const success = state === "success";
  const loading = state === "loading";

  return (
    <div className="min-h-screen grid lg:grid-cols-[1.02fr_0.98fr]" style={{ background: "#EEE9DB" }}>
      <section
        className="relative overflow-hidden px-8 py-8 lg:px-12 lg:py-12"
        style={{
          background:
            "radial-gradient(circle at 20% 18%, rgba(208,231,167,0.26), transparent 26%), radial-gradient(circle at 78% 24%, rgba(100,149,115,0.24), transparent 28%), linear-gradient(160deg, #071B14 0%, #0E2A1F 42%, #153628 100%)",
        }}
      >
        <div className="absolute inset-0 opacity-30" style={{ backgroundImage: "linear-gradient(rgba(255,255,255,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.08) 1px, transparent 1px)", backgroundSize: "38px 38px", maskImage: "radial-gradient(circle at center, black, transparent 82%)" }} />
        <div className="relative flex h-full min-h-[520px] flex-col justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center overflow-hidden rounded-xl bg-[#1A4F39] shadow-[0_8px_30px_rgba(0,0,0,0.2)]">
              <ImageWithFallback src={logoImg} alt="AGRO-AI" className="h-full w-full object-contain" />
            </div>
            <div>
              <div className="text-[15px] font-semibold tracking-tight text-white">AGRO-AI</div>
              <div className="text-[11px] text-white/45">Enterprise Portal</div>
            </div>
          </div>

          <div className="max-w-xl py-14">
            <div className="mb-5 inline-flex rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-[#DDEB8F]">
              Secure verification
            </div>
            <h1 className="text-[42px] font-semibold leading-[1.05] tracking-tight text-white">AGRO-AI Enterprise Portal</h1>
            <p className="mt-5 max-w-xl text-[15px] leading-7 text-white/72">
              A new kind of agricultural intelligence for farms, water agencies, advisors, and agricultural networks.
            </p>
          </div>

          <div className="text-[11px] leading-5 text-white/42">Verified access keeps field, water, evidence, and report workspaces secure.</div>
        </div>
      </section>

      <main className="flex items-center justify-center px-6 py-10">
        <div className="w-full max-w-[520px] rounded-[24px] border border-[rgba(16,35,27,0.1)] bg-[#FFFDF8] p-8 shadow-[0_24px_70px_rgba(16,35,27,0.12)]">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl" style={{ background: success ? "#F0FDF4" : loading ? "#F8F5EA" : "#FFF7ED" }}>
              {loading ? <Loader2 className="h-6 w-6 animate-spin text-[#617068]" /> : success ? <CheckCircle2 className="h-6 w-6 text-[#2D6A4F]" /> : <ShieldAlert className="h-6 w-6 text-[#A4492F]" />}
            </div>
            <div>
              <div className="text-[12px] font-semibold uppercase tracking-[0.18em]" style={{ color: success ? "#2D6A4F" : "#65736A" }}>{loading ? "Verifying" : success ? "Verified" : "Action needed"}</div>
              <h2 className="mt-2 text-[28px] font-semibold tracking-tight text-[#10231B]">{success ? "Email verified" : loading ? "Confirming your email" : "Verification link expired or invalid"}</h2>
              <p className="mt-3 text-[14px] leading-7 text-[#65736A]">{message}</p>
            </div>
          </div>

          <div className="mt-8 flex flex-wrap gap-3">
            <Button type="button" onClick={() => window.location.assign("/")} className="bg-[#10231B] text-white hover:bg-[#183528]">
              Continue to portal
            </Button>
            <Button type="button" variant="outline" onClick={() => window.location.assign("/")} className="border-[#D6DDD0] bg-white text-[#10231B] hover:bg-[#F6F4EE]">
              Sign in
            </Button>
          </div>

          {!success && !loading ? (
            <div className="mt-8 rounded-2xl border border-[#D6DDD0] bg-[#F8F5EA] p-4">
              <div className="text-[13px] font-semibold text-[#10231B]">Request a new verification email</div>
              <p className="mt-1 text-[12px] leading-6 text-[#65736A]">Enter the email used for your AGRO-AI account and we will send a fresh secure link.</p>
              <div className="mt-4 flex gap-2">
                <input
                  type="email"
                  value={requestEmail}
                  onChange={(event) => setRequestEmail(event.target.value)}
                  placeholder="you@company.com"
                  className="h-10 min-w-0 flex-1 rounded-lg border border-[#D6DDD0] bg-white px-3 text-[13px] text-[#10231B] outline-none"
                />
                <Button type="button" onClick={requestNewLink} disabled={isResending} className="bg-[#10231B] text-white hover:bg-[#183528]">
                  {isResending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Send link
                </Button>
              </div>
              {resendMessage ? <p className="mt-3 text-[12px] leading-6 text-[#375347]">{resendMessage}</p> : null}
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}
