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
            <div className="text-[14px] font-semibold text-[#10231B]">Your organization passed automated screening.</div>
            <p className="mt-1 text-[13px] leading-6 text-[#617068]">
              Verify the email sent to <span className="font-medium text-[#10231B]">{verification?.email || "your email"}</span> to activate secure portal access.
            </p>
          </div>
        </div>
      </div>

      {message ? <div className="rounded-md border border-[#D7E4CF] bg-[#FBFDF8] px-3 py-2 text-sm text-[#375347]">{message}</div> : null}

      <Field label="Password">
        <Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" placeholder="Re-enter password after verifying" />
      </Field>

      <div className="grid gap-3 sm:grid-cols-2">
        <Button type="button" onClick={resend} disabled={working !== ""} className="w-full bg-[#10231B] text-white hover:bg-[#183528]">
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
    if (!registerForm.website_url?.trim() && !registerForm.professional_profile_url?.trim()) {
      setError("Add an organization website or a verifiable professional profile.");
      return;
    }
    setIsSubmitting(true);
    try {
      await register({
        ...registerForm,
        crop: registerForm.primary_crops,
        region: registerForm.operating_region,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create account.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen grid lg:grid-cols-[0.92fr_1.08fr]" style={{ background: "#EEE9DB" }}>
      <section
        className="relative overflow-hidden px-8 py-8 lg:sticky lg:top-0 lg:h-screen lg:px-12 lg:py-12"
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
              Verified agricultural access
            </div>
            <h1 className="max-w-lg text-[42px] font-semibold leading-[1.05] tracking-tight text-white">AGRO-AI Enterprise Portal</h1>
            <p className="mt-5 max-w-xl text-[15px] leading-7 text-white/72">
              Live workspaces are reserved for verified farms, agribusinesses, water organizations, advisors, and agricultural technology partners.
            </p>
            <div className="mt-8 grid max-w-lg gap-3">
              {[
                "Every new organization is screened automatically before operational access is activated.",
                "Gmail and Outlook addresses are accepted, but require stronger organization and use-case evidence.",
                "Operational files, connected systems, and customer data remain behind server-enforced access controls.",
              ].map((line) => (
                <div key={line} className="rounded-xl border border-white/10 bg-white/5 p-4 text-[13px] leading-6 text-white/78 backdrop-blur-sm">
                  {line}
                </div>
              ))}
            </div>
          </div>

          <div className="relative text-[11px] leading-5 text-white/42">Real teams. Real operations. Verified access.</div>
        </div>
      </section>

      <main className="flex items-start justify-center px-5 py-8 lg:min-h-screen lg:px-8 lg:py-10">
        <div className={`w-full ${mode === "register" && !verification ? "max-w-[720px]" : "max-w-[460px]"} rounded-[20px] border border-[rgba(16,35,27,0.1)] bg-[#FFFDF8] p-7 shadow-[0_24px_70px_rgba(16,35,27,0.12)]`}>
          {verification ? (
            <VerificationPanel />
          ) : (
            <Tabs value={mode} onValueChange={setMode} className="gap-5">
              <TabsList className="grid w-full grid-cols-2 rounded-xl bg-[#F3EFE5] p-1">
                <TabsTrigger value="login" className="rounded-lg text-[13px]">Login</TabsTrigger>
                <TabsTrigger value="register" className="rounded-lg text-[13px]">Request access</TabsTrigger>
              </TabsList>

              {error ? <div className="rounded-md border border-[#B94A48]/25 bg-[#B94A48]/8 px-3 py-2 text-sm text-[#7A2E2B]">{error}</div> : null}

              <TabsContent value="login">
                <div className="mb-4">
                  <h2 className="text-[18px] font-semibold text-[#10231B]">Secure sign-in</h2>
                  <p className="mt-1 text-[13px] leading-6 text-[#65736A]">Sign in to a verified AGRO-AI organization workspace.</p>
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
                  <Button type="submit" disabled={isSubmitting} className="w-full bg-[#10231B] text-white hover:bg-[#183528]">
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    Sign in
                  </Button>
                </form>
              </TabsContent>

              <TabsContent value="register">
                <div className="mb-5">
                  <h2 className="text-[18px] font-semibold text-[#10231B]">Verify your organization</h2>
                  <p className="mt-1 text-[13px] leading-6 text-[#65736A]">
                    The system automatically accepts or rejects access using organization, operational, identity, and use-case signals. No manual review is required.
                  </p>
                </div>
                <form className="space-y-5" onSubmit={handleRegister}>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Full name">
                      <Input value={registerForm.name} onChange={(event) => setRegisterForm({ ...registerForm, name: event.target.value })} autoComplete="name" required />
                    </Field>
                    <Field label="Professional role">
                      <Input value={registerForm.professional_role} onChange={(event) => setRegisterForm({ ...registerForm, professional_role: event.target.value })} placeholder="Farm manager, agronomist, CEO..." required />
                    </Field>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Email">
                      <Input type="email" value={registerForm.email} onChange={(event) => setRegisterForm({ ...registerForm, email: event.target.value })} autoComplete="email" required />
                    </Field>
                    <Field label="Phone number">
                      <Input type="tel" value={registerForm.phone_number} onChange={(event) => setRegisterForm({ ...registerForm, phone_number: event.target.value })} autoComplete="tel" placeholder="Include country code" required />
                    </Field>
                  </div>

                  <Field label="Password">
                    <Input type="password" value={registerForm.password} onChange={(event) => setRegisterForm({ ...registerForm, password: event.target.value })} autoComplete="new-password" minLength={12} maxLength={128} required />
                    <p className="mt-1.5 text-[11px] leading-5 text-[#78837C]">Use at least 12 characters. Do not include your email name.</p>
                  </Field>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Legal organization name">
                      <Input value={registerForm.organization_name} onChange={(event) => setRegisterForm({ ...registerForm, organization_name: event.target.value })} autoComplete="organization" required />
                    </Field>
                    <Field label="Organization type">
                      <select
                        value={registerForm.organization_type}
                        onChange={(event) => setRegisterForm({ ...registerForm, organization_type: event.target.value })}
                        className="flex h-9 w-full rounded-md border border-input bg-input-background px-3 py-1 text-sm text-[#10231B] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                        required
                      >
                        <option value="">Select organization type</option>
                        {organizationTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    </Field>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Organization website">
                      <Input type="url" value={registerForm.website_url} onChange={(event) => setRegisterForm({ ...registerForm, website_url: event.target.value })} placeholder="https://company.com" />
                    </Field>
                    <Field label="Professional or company profile">
                      <Input type="url" value={registerForm.professional_profile_url} onChange={(event) => setRegisterForm({ ...registerForm, professional_profile_url: event.target.value })} placeholder="LinkedIn or public business profile" />
                    </Field>
                  </div>
                  <p className="-mt-3 text-[11px] leading-5 text-[#78837C]">At least one verifiable website or professional profile is required.</p>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Country">
                      <Input value={registerForm.country} onChange={(event) => setRegisterForm({ ...registerForm, country: event.target.value })} autoComplete="country-name" required />
                    </Field>
                    <Field label="Operating region">
                      <Input value={registerForm.operating_region} onChange={(event) => setRegisterForm({ ...registerForm, operating_region: event.target.value })} placeholder="California Central Valley" required />
                    </Field>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Acres, hectares, sites, or customers served">
                      <Input value={registerForm.acres_or_sites} onChange={(event) => setRegisterForm({ ...registerForm, acres_or_sites: event.target.value })} placeholder="2,500 acres across 4 farms" required />
                    </Field>
                    <Field label="Crops or agricultural segment">
                      <Input value={registerForm.primary_crops} onChange={(event) => setRegisterForm({ ...registerForm, primary_crops: event.target.value })} placeholder="Almonds, vineyards, irrigation services..." required />
                    </Field>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Initial operation name">
                      <Input value={registerForm.workspace_name} onChange={(event) => setRegisterForm({ ...registerForm, workspace_name: event.target.value })} placeholder="North ranch operations" required />
                    </Field>
                    <Field label="Systems or data sources to connect">
                      <Input value={registerForm.planned_data_sources} onChange={(event) => setRegisterForm({ ...registerForm, planned_data_sources: event.target.value })} placeholder="WiseConn, John Deere, PDFs, spreadsheets..." required />
                    </Field>
                  </div>

                  <Field label="Genuine operational use case">
                    <textarea
                      value={registerForm.intended_use}
                      onChange={(event) => setRegisterForm({ ...registerForm, intended_use: event.target.value })}
                      minLength={50}
                      maxLength={1200}
                      rows={4}
                      className="w-full resize-y rounded-md border border-input bg-input-background px-3 py-2 text-sm leading-6 text-[#10231B] outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                      placeholder="Explain the operation, the decisions your team needs to make, and how AGRO-AI will be used."
                      required
                    />
                  </Field>

                  <div className="rounded-xl border border-[#D7E4CF] bg-[#F6FAF1] p-4 text-[12px] leading-5 text-[#52645A]">
                    Organization evidence is scored automatically. Disposable email domains, fabricated organizations, placeholder data, and non-agricultural use cases are rejected. Personal email providers remain eligible when the supporting evidence is strong.
                  </div>

                  <Button type="submit" disabled={isSubmitting} className="w-full bg-[#10231B] text-white hover:bg-[#183528]">
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    Submit for automated verification
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
