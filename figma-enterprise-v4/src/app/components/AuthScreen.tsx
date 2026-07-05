import { FormEvent, ReactNode, useEffect, useState } from "react";
import { CheckCircle2, Loader2, ShieldCheck } from "lucide-react";
import logoImg from "../../imports/agro-ai-logo-1.png";
import { RegisterPayload } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { ImageWithFallback } from "./figma/ImageWithFallback";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";

const initialRegisterForm: RegisterPayload = {
  name: "",
  email: "",
  password: "",
  organization_name: "",
  workspace_name: "",
  crop: "",
  region: "",
};

function VerificationPanel() {
  const { verification, requestVerification, login } = useAuth();
  const [message, setMessage] = useState(verification?.message || "");
  const [password, setPassword] = useState("");
  const [working, setWorking] = useState<"resend" | "refresh" | "">("");

  async function resend() {
    setWorking("resend");
    try {
      const nextMessage = await requestVerification(verification?.email);
      setMessage(nextMessage);
    } finally {
      setWorking("");
    }
  }

  async function refresh() {
    if (!verification?.email || !password) return;
    setWorking("refresh");
    try {
      await login(verification.email, password);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Verification is still pending.");
    } finally {
      setWorking("");
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-[#D7E4CF] bg-[#F6FAF1] p-4">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 h-5 w-5 text-[#2D6A4F]" />
          <div>
            <div className="text-[14px] font-semibold text-[#10231B]">Verify your email to activate your AGRO-AI workspace.</div>
            <p className="mt-1 text-[13px] leading-6 text-[#617068]">
              We sent a verification link to <span className="font-medium text-[#10231B]">{verification?.email || "your email"}</span>.
            </p>
          </div>
        </div>
      </div>

      {message ? <div className="rounded-md border border-[#D7E4CF] bg-[#FBFDF8] px-3 py-2 text-sm text-[#375347]">{message}</div> : null}

      <Field label="Password">
        <Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" placeholder="Re-enter password after verifying" />
      </Field>

      <div className="grid gap-3 sm:grid-cols-2">
        <Button type="button" onClick={resend} disabled={working !== ""} className="w-full bg-[#10231B] hover:bg-[#183528] text-white">
          {working === "resend" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Resend verification email
        </Button>
        <Button type="button" variant="outline" onClick={refresh} disabled={working !== "" || !password} className="w-full border-[#D6DDD0] bg-white text-[#10231B] hover:bg-[#F6F4EE]">
          {working === "refresh" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          I verified my email
        </Button>
      </div>
    </div>
  );
}

export function AuthScreen() {
  const { login, register, verification, confirmVerification } = useAuth();
  const [mode, setMode] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("mode") || params.get("auth");
    return requested === "register" || requested === "create" ? "register" : "login";
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [registerForm, setRegisterForm] = useState<RegisterPayload>(initialRegisterForm);

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) return;
    setIsSubmitting(true);
    confirmVerification(token)
      .catch((err) => setError(err instanceof Error ? err.message : "Verification link could not be confirmed."))
      .finally(() => setIsSubmitting(false));
  }, [confirmVerification]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await login(loginForm.email, loginForm.password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to sign in.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await register(registerForm);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create account.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen grid lg:grid-cols-[1.04fr_0.96fr]" style={{ background: "#EEE9DB" }}>
      <section
        className="relative overflow-hidden px-8 py-8 lg:px-12 lg:py-12"
        style={{
          background:
            "radial-gradient(circle at 18% 22%, rgba(208,231,167,0.28), transparent 26%), radial-gradient(circle at 78% 20%, rgba(100,149,115,0.26), transparent 28%), linear-gradient(160deg, #071B14 0%, #0E2A1F 38%, #153628 100%)",
        }}
      >
        <div className="absolute inset-0 opacity-30" style={{ backgroundImage: "linear-gradient(rgba(255,255,255,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.08) 1px, transparent 1px)", backgroundSize: "38px 38px", maskImage: "radial-gradient(circle at center, black, transparent 82%)" }} />
        <div className="relative flex h-full flex-col justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center overflow-hidden rounded-xl bg-[#1A4F39] shadow-[0_8px_30px_rgba(0,0,0,0.2)]">
              <ImageWithFallback src={logoImg} alt="AGRO-AI" className="h-full w-full object-contain" />
            </div>
            <div>
              <div className="text-[15px] font-semibold tracking-tight text-white">AGRO-AI</div>
              <div className="text-[11px] text-white/45">Enterprise Portal</div>
            </div>
          </div>

          <div className="relative max-w-xl py-14">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-[#DDEB8F]">
              <ShieldCheck className="h-3.5 w-3.5" />
              Secure workspace access
            </div>
            <h1 className="max-w-lg text-[42px] font-semibold leading-[1.05] tracking-tight text-white">AGRO-AI Enterprise Portal</h1>
            <p className="mt-5 max-w-xl text-[15px] leading-7 text-white/72">
              A new kind of agricultural intelligence for farms, water agencies, advisors, and agricultural networks.
            </p>
            <div className="mt-8 grid max-w-lg gap-3 sm:grid-cols-2">
              {[
                "Operate fields, evidence, water risk, and reports from one secure workspace.",
                "Turn agricultural evidence into decisions, reports, and operating clarity.",
              ].map((line) => (
                <div key={line} className="rounded-xl border border-white/10 bg-white/5 p-4 text-[13px] leading-6 text-white/78 backdrop-blur-sm">
                  {line}
                </div>
              ))}
            </div>
          </div>

          <div className="relative text-[11px] leading-5 text-white/42">Secure workspace access for agricultural operations.</div>
        </div>
      </section>

      <main className="flex items-center justify-center px-6 py-10">
        <div className="w-full max-w-[460px] rounded-[20px] border border-[rgba(16,35,27,0.1)] bg-[#FFFDF8] p-7 shadow-[0_24px_70px_rgba(16,35,27,0.12)]">
          {verification ? (
            <VerificationPanel />
          ) : (
            <Tabs value={mode} onValueChange={setMode} className="gap-5">
              <TabsList className="grid w-full grid-cols-2 rounded-xl bg-[#F3EFE5] p-1">
                <TabsTrigger value="login" className="rounded-lg text-[13px]">Login</TabsTrigger>
                <TabsTrigger value="register" className="rounded-lg text-[13px]">Create account</TabsTrigger>
              </TabsList>

              {error ? <div className="rounded-md border border-[#B94A48]/25 bg-[#B94A48]/8 px-3 py-2 text-sm text-[#7A2E2B]">{error}</div> : null}

              <TabsContent value="login">
                <div className="mb-4">
                  <h2 className="text-[18px] font-semibold text-[#10231B]">Secure sign-in</h2>
                  <p className="mt-1 text-[13px] leading-6 text-[#65736A]">Operate fields, evidence, water risk, and reports from one secure intelligence workspace.</p>
                </div>
                <form className="space-y-4" onSubmit={handleLogin}>
                  <Field label="Email">
                    <Input type="email" value={loginForm.email} onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })} autoComplete="email" required />
                  </Field>
                  <Field label="Password">
                    <Input type="password" value={loginForm.password} onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })} autoComplete="current-password" required />
                  </Field>
                  <div className="flex justify-end">
                    <a href="/recover-account" className="text-[13px] font-medium text-[#2D6A4F] hover:text-[#1E5B40] hover:underline">
                      Forgot password?
                    </a>
                  </div>
                  <Button type="submit" disabled={isSubmitting} className="w-full bg-[#10231B] hover:bg-[#183528] text-white">
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    Sign in
                  </Button>
                </form>
              </TabsContent>

              <TabsContent value="register">
                <div className="mb-4">
                  <h2 className="text-[18px] font-semibold text-[#10231B]">Create your workspace</h2>
                  <p className="mt-1 text-[13px] leading-6 text-[#65736A]">Coordinate field teams, water risk, compliance evidence, and executive reporting.</p>
                </div>
                <form className="space-y-4" onSubmit={handleRegister}>
                  <Field label="Name">
                    <Input value={registerForm.name} onChange={(event) => setRegisterForm({ ...registerForm, name: event.target.value })} autoComplete="name" required />
                  </Field>
                  <Field label="Email">
                    <Input type="email" value={registerForm.email} onChange={(event) => setRegisterForm({ ...registerForm, email: event.target.value })} autoComplete="email" required />
                  </Field>
                  <Field label="Password">
                    <Input type="password" value={registerForm.password} onChange={(event) => setRegisterForm({ ...registerForm, password: event.target.value })} autoComplete="new-password" minLength={12} required />
                  </Field>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Organization name">
                      <Input value={registerForm.organization_name} onChange={(event) => setRegisterForm({ ...registerForm, organization_name: event.target.value })} required />
                    </Field>
                    <Field label="Workspace name">
                      <Input value={registerForm.workspace_name} onChange={(event) => setRegisterForm({ ...registerForm, workspace_name: event.target.value })} required />
                    </Field>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Crop">
                      <Input value={registerForm.crop} onChange={(event) => setRegisterForm({ ...registerForm, crop: event.target.value })} />
                    </Field>
                    <Field label="Region">
                      <Input value={registerForm.region} onChange={(event) => setRegisterForm({ ...registerForm, region: event.target.value })} />
                    </Field>
                  </div>
                  <Button type="submit" disabled={isSubmitting} className="w-full bg-[#10231B] hover:bg-[#183528] text-white">
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    Create account
                  </Button>
                </form>
              </TabsContent>
            </Tabs>
          )}
        </div>
      </main>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[12px] font-medium text-[#10231B]">{label}</span>
      {children}
    </label>
  );
}
