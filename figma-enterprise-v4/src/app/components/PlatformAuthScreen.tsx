import { FormEvent, ReactNode, useEffect, useState } from "react";
import { CheckCircle2, Code2, Loader2, ShieldCheck, TerminalSquare } from "lucide-react";
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
  organization_type: "",
  professional_role: "",
  phone_number: "",
  website_url: "",
  professional_profile_url: "",
  country: "",
  operating_region: "",
  acres_or_sites: "",
  primary_crops: "",
  intended_use: "",
  planned_data_sources: "",
  workspace_name: "",
  crop: "",
  region: "",
};

const organizationTypes = [
  ["farm_or_grower", "Farm or grower"],
  ["agribusiness", "Agribusiness"],
  ["agricultural_landowner", "Agricultural landowner"],
  ["investment_manager", "Agricultural investment manager"],
  ["irrigation_dealer_or_contractor", "Irrigation dealer or contractor"],
  ["irrigation_technology_provider", "Irrigation technology provider"],
  ["oem_or_equipment_manufacturer", "OEM or equipment manufacturer"],
  ["agricultural_consultant", "Agricultural consultant"],
  ["research_institution", "Research institution"],
  ["water_agency_or_district", "Water agency or district"],
  ["food_or_supply_chain_company", "Food or supply-chain company"],
  ["other_agricultural_organization", "Other agricultural organization"],
] as const;

function Field({ label, children, note }: { label: string; children: ReactNode; note?: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-semibold text-[#405349]">{label}</span>
      {children}
      {note ? <span className="mt-1.5 block text-[10px] leading-5 text-[#7A867E]">{note}</span> : null}
    </label>
  );
}

function VerificationPanel() {
  const { verification, requestVerification, login } = useAuth();
  const [message, setMessage] = useState(verification?.message || "");
  const [password, setPassword] = useState("");
  const [working, setWorking] = useState<"resend" | "refresh" | "">("");

  async function resend() {
    setWorking("resend");
    try {
      setMessage(await requestVerification(verification?.email));
    } finally {
      setWorking("");
    }
  }

  async function refresh() {
    if (!verification?.email || !password) return;
    setWorking("refresh");
    try {
      await login(verification.email, password);
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Email verification is still pending.");
    } finally {
      setWorking("");
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-[#CFE0C8] bg-[#F5FAF1] p-5">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 h-5 w-5 text-[#2D6A4F]" />
          <div>
            <div className="text-[14px] font-semibold text-[#10231B]">Your organization passed automated screening.</div>
            <p className="mt-1 text-[12px] leading-6 text-[#617068]">
              Verify the email sent to <span className="font-semibold text-[#10231B]">{verification?.email || "your email"}</span>. After sign-in, an owner or admin can accept the current developer agreements and activate bounded TEST access without an API-access review.
            </p>
          </div>
        </div>
      </div>
      {message ? <div className="rounded-xl border border-[#D7E4CF] bg-white px-3 py-2 text-[11px] text-[#375347]">{message}</div> : null}
      <Field label="Password" note="Re-enter the password after you verify the email.">
        <Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Button type="button" onClick={() => void resend()} disabled={working !== ""} className="bg-[#10231B] text-white hover:bg-[#183528]">
          {working === "resend" ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Resend email
        </Button>
        <Button type="button" variant="outline" onClick={() => void refresh()} disabled={working !== "" || !password} className="border-[#D6DDD0] bg-white text-[#10231B]">
          {working === "refresh" ? <Loader2 className="h-4 w-4 animate-spin" /> : null} I verified my email
        </Button>
      </div>
    </div>
  );
}

export function PlatformAuthScreen() {
  const { login, register, verification, confirmVerification } = useAuth();
  const [mode, setMode] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("mode") || params.get("auth");
    return requested === "register" || requested === "create" ? "register" : "login";
  });
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [registerForm, setRegisterForm] = useState<RegisterPayload>(initialRegisterForm);

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) return;
    setWorking(true);
    confirmVerification(token)
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Verification link could not be confirmed."))
      .finally(() => setWorking(false));
  }, [confirmVerification]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setWorking(true);
    try {
      await login(loginForm.email, loginForm.password);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to sign in.");
    } finally {
      setWorking(false);
    }
  }

  async function handleRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!registerForm.website_url?.trim() && !registerForm.professional_profile_url?.trim()) {
      setError("Add an organization website or a verifiable professional profile.");
      return;
    }
    setWorking(true);
    try {
      await register({ ...registerForm, crop: registerForm.primary_crops, region: registerForm.operating_region });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create the developer account.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="min-h-screen grid lg:grid-cols-[.86fr_1.14fr]" style={{ background: "#EEE9DB" }}>
      <section className="relative overflow-hidden px-8 py-8 lg:sticky lg:top-0 lg:h-screen lg:px-12 lg:py-12" style={{ background: "radial-gradient(circle at 16% 16%,rgba(220,239,139,.22),transparent 27%),radial-gradient(circle at 82% 68%,rgba(81,139,100,.22),transparent 31%),linear-gradient(155deg,#061B13 0%,#0A281C 46%,#123A28 100%)" }}>
        <div className="absolute inset-0 opacity-30" style={{ backgroundImage: "linear-gradient(rgba(255,255,255,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.08) 1px,transparent 1px)", backgroundSize: "34px 34px", maskImage: "radial-gradient(circle at center,black,transparent 82%)" }} />
        <div className="relative flex h-full flex-col justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center overflow-hidden rounded-xl bg-[#1A4F39]"><ImageWithFallback src={logoImg} alt="AGRO-AI" className="h-full w-full object-contain" /></div>
            <div><div className="text-[15px] font-semibold text-white">AGRO-AI</div><div className="text-[11px] text-white/45">Platform API</div></div>
          </div>

          <div className="max-w-xl py-12">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[.17em] text-[#DCEF8B]"><Code2 className="h-3.5 w-3.5" /> Developer platform</div>
            <h1 className="mt-6 text-[44px] font-semibold leading-[1.03] tracking-[-.045em] text-white md:text-[52px]">Build on AGRO-AI.</h1>
            <p className="mt-5 max-w-lg text-[14px] leading-7 text-white/68">Create a verified agricultural organization account, accept the current developer agreements, and start with isolated TEST resources. No sales call or manual API-access review for eligible TEST developers.</p>
            <div className="mt-8 grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-[12px] text-white/75"><TerminalSquare className="mb-3 h-4 w-4 text-[#DCEF8B]" /> Browser + terminal onboarding</div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-[12px] text-white/75"><ShieldCheck className="mb-3 h-4 w-4 text-[#DCEF8B]" /> Scoped `agro_test_` credentials</div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-[12px] text-white/75"><CheckCircle2 className="mb-3 h-4 w-4 text-[#DCEF8B]" /> Deterministic agricultural TEST data</div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-[12px] text-white/75"><ShieldCheck className="mb-3 h-4 w-4 text-[#DCEF8B]" /> LIVE and physical actions stay gated</div>
            </div>
          </div>

          <div className="text-[10px] leading-5 text-white/40">Verified account. Versioned agreements. Bounded TEST access.</div>
        </div>
      </section>

      <main className="flex items-start justify-center px-5 py-8 lg:min-h-screen lg:px-8 lg:py-10">
        <div className={`w-full ${mode === "register" && !verification ? "max-w-[760px]" : "max-w-[470px]"} rounded-[22px] border border-black/10 bg-[#FFFDF8] p-7 shadow-[0_24px_70px_rgba(16,35,27,.12)]`}>
          {verification ? <VerificationPanel /> : (
            <Tabs value={mode} onValueChange={setMode} className="gap-5">
              <TabsList className="grid w-full grid-cols-2 rounded-xl bg-[#F3EFE5] p-1"><TabsTrigger value="login">Login</TabsTrigger><TabsTrigger value="register">Create account</TabsTrigger></TabsList>
              {error ? <div role="alert" className="rounded-xl border border-[#B94A48]/25 bg-[#B94A48]/8 px-3 py-2 text-[11px] text-[#7A2E2B]">{error}</div> : null}

              <TabsContent value="login">
                <div className="mb-5"><h2 className="text-[19px] font-semibold">Developer sign-in</h2><p className="mt-1 text-[12px] leading-6 text-[#65736A]">Sign in to your verified AGRO-AI organization. Your TEST developer state is resolved server-side.</p></div>
                <form className="space-y-4" onSubmit={handleLogin}>
                  <Field label="Email"><Input type="email" value={loginForm.email} onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })} autoComplete="email" required /></Field>
                  <Field label="Password"><Input type="password" value={loginForm.password} onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })} autoComplete="current-password" required /></Field>
                  <Button type="submit" disabled={working} className="w-full bg-[#10231B] text-white hover:bg-[#183528]">{working ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Sign in</Button>
                  <div className="flex justify-between text-[11px]"><a href="/recover-account" className="font-medium text-[#2D6A4F] hover:underline">Forgot password?</a><a href="/appeal" className="font-medium text-[#2D6A4F] hover:underline">Access restricted?</a></div>
                </form>
              </TabsContent>

              <TabsContent value="register">
                <div className="mb-5"><h2 className="text-[19px] font-semibold">Create a verified developer organization</h2><p className="mt-1 text-[12px] leading-6 text-[#65736A]">Automated screening protects the developer platform. Eligible owners/admins can activate TEST access after email verification and agreement acceptance.</p></div>
                <form className="space-y-5" onSubmit={handleRegister}>
                  <div className="grid gap-4 sm:grid-cols-2"><Field label="Full name"><Input value={registerForm.name} onChange={(event) => setRegisterForm({ ...registerForm, name: event.target.value })} autoComplete="name" required /></Field><Field label="Professional role"><Input value={registerForm.professional_role} onChange={(event) => setRegisterForm({ ...registerForm, professional_role: event.target.value })} placeholder="Farm manager, CTO, agronomist…" required /></Field></div>
                  <div className="grid gap-4 sm:grid-cols-2"><Field label="Email"><Input type="email" value={registerForm.email} onChange={(event) => setRegisterForm({ ...registerForm, email: event.target.value })} autoComplete="email" required /></Field><Field label="Phone number"><Input type="tel" value={registerForm.phone_number} onChange={(event) => setRegisterForm({ ...registerForm, phone_number: event.target.value })} autoComplete="tel" placeholder="Include country code" required /></Field></div>
                  <Field label="Password" note="At least 12 characters. Do not include your email name."><Input type="password" value={registerForm.password} onChange={(event) => setRegisterForm({ ...registerForm, password: event.target.value })} minLength={12} maxLength={128} autoComplete="new-password" required /></Field>
                  <div className="grid gap-4 sm:grid-cols-2"><Field label="Legal organization name"><Input value={registerForm.organization_name} onChange={(event) => setRegisterForm({ ...registerForm, organization_name: event.target.value })} autoComplete="organization" required /></Field><Field label="Organization type"><select value={registerForm.organization_type} onChange={(event) => setRegisterForm({ ...registerForm, organization_type: event.target.value })} className="flex h-9 w-full rounded-md border border-input bg-input-background px-3 text-sm" required><option value="">Select organization type</option>{organizationTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field></div>
                  <div className="grid gap-4 sm:grid-cols-2"><Field label="Organization website"><Input type="url" value={registerForm.website_url} onChange={(event) => setRegisterForm({ ...registerForm, website_url: event.target.value })} placeholder="https://…" /></Field><Field label="Professional profile"><Input type="url" value={registerForm.professional_profile_url} onChange={(event) => setRegisterForm({ ...registerForm, professional_profile_url: event.target.value })} placeholder="LinkedIn or equivalent" /></Field></div>
                  <div className="grid gap-4 sm:grid-cols-2"><Field label="Country"><Input value={registerForm.country} onChange={(event) => setRegisterForm({ ...registerForm, country: event.target.value })} required /></Field><Field label="Operating region"><Input value={registerForm.operating_region} onChange={(event) => setRegisterForm({ ...registerForm, operating_region: event.target.value })} placeholder="California Central Valley" required /></Field></div>
                  <div className="grid gap-4 sm:grid-cols-2"><Field label="Acres or sites"><Input value={registerForm.acres_or_sites} onChange={(event) => setRegisterForm({ ...registerForm, acres_or_sites: event.target.value })} placeholder="2,500 acres across four farms" required /></Field><Field label="Primary crops"><Input value={registerForm.primary_crops} onChange={(event) => setRegisterForm({ ...registerForm, primary_crops: event.target.value })} placeholder="Almonds, pistachios…" required /></Field></div>
                  <Field label="What are you building with AGRO-AI?"><textarea value={registerForm.intended_use} onChange={(event) => setRegisterForm({ ...registerForm, intended_use: event.target.value })} className="min-h-[92px] w-full rounded-md border border-input bg-input-background px-3 py-2 text-sm outline-none focus:border-ring" required /></Field>
                  <Field label="Planned data sources"><textarea value={registerForm.planned_data_sources} onChange={(event) => setRegisterForm({ ...registerForm, planned_data_sources: event.target.value })} className="min-h-[72px] w-full rounded-md border border-input bg-input-background px-3 py-2 text-sm outline-none focus:border-ring" placeholder="John Deere, WiseConn, files, weather…" required /></Field>
                  <Field label="Workspace name"><Input value={registerForm.workspace_name} onChange={(event) => setRegisterForm({ ...registerForm, workspace_name: event.target.value })} placeholder="Developer workspace" required /></Field>
                  <Button type="submit" disabled={working} className="w-full bg-[#10231B] text-white hover:bg-[#183528]">{working ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Create developer account</Button>
                  <p className="text-center text-[10px] leading-5 text-[#7A867E]">Account creation does not enable LIVE projects, billing, provider credentials, production webhooks, or physical execution.</p>
                </form>
              </TabsContent>
            </Tabs>
          )}
        </div>
      </main>
    </div>
  );
}
