import { FormEvent, ReactNode, useState } from "react";
import { Loader2 } from "lucide-react";
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

export function AuthScreen() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [registerForm, setRegisterForm] = useState<RegisterPayload>(initialRegisterForm);

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
    <div className="min-h-screen grid lg:grid-cols-[0.95fr_1.05fr]" style={{ background: "#F6F4EE" }}>
      <section className="flex flex-col justify-between px-8 py-8 lg:px-12 lg:py-12 bg-[#061D15]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg overflow-hidden flex items-center justify-center bg-[#16533C]">
            <ImageWithFallback src={logoImg} alt="AGRO-AI" className="w-full h-full object-contain" />
          </div>
          <div>
            <div className="text-white font-semibold text-[14px] leading-tight">AGRO-AI</div>
            <div className="text-[11px] leading-tight text-white/45">Enterprise Portal</div>
          </div>
        </div>

        <div className="max-w-md py-16">
          <div className="text-[11px] uppercase tracking-widest font-semibold text-white/35 mb-4">
            Secure workspace access
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-white mb-5">Enterprise Portal</h1>
          <p className="text-sm leading-6 text-white/58">
            Sign in to review operational workspaces, evidence, reports, and account status for your
            organization.
          </p>
        </div>

        <div className="text-[11px] leading-5 text-white/35">
          Authenticated AGRO-AI organization access.
        </div>
      </section>

      <main className="flex items-center justify-center px-6 py-10">
        <div className="w-full max-w-[440px] bg-[#FFFEFA] border border-[rgba(16,35,27,0.12)] rounded-xl p-6 shadow-[0_18px_60px_rgba(16,35,27,0.08)]">
          <Tabs value={mode} onValueChange={setMode} className="gap-5">
            <TabsList className="grid w-full grid-cols-2 bg-[#F6F4EE] rounded-lg p-1">
              <TabsTrigger value="login" className="rounded-md text-[13px]">
                Login
              </TabsTrigger>
              <TabsTrigger value="register" className="rounded-md text-[13px]">
                Create account
              </TabsTrigger>
            </TabsList>

            {error ? (
              <div className="rounded-md border border-[#B94A48]/25 bg-[#B94A48]/8 px-3 py-2 text-sm text-[#7A2E2B]">
                {error}
              </div>
            ) : null}

            <TabsContent value="login">
              <form className="space-y-4" onSubmit={handleLogin}>
                <Field label="Email">
                  <Input
                    type="email"
                    value={loginForm.email}
                    onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })}
                    autoComplete="email"
                    required
                  />
                </Field>
                <Field label="Password">
                  <Input
                    type="password"
                    value={loginForm.password}
                    onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })}
                    autoComplete="current-password"
                    required
                  />
                </Field>
                <Button
                  type="submit"
                  disabled={isSubmitting}
                  className="w-full bg-[#10231B] hover:bg-[#16533C] text-white"
                >
                  {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  Sign in
                </Button>
              </form>
            </TabsContent>

            <TabsContent value="register">
              <form className="space-y-4" onSubmit={handleRegister}>
                <Field label="Name">
                  <Input
                    value={registerForm.name}
                    onChange={(event) => setRegisterForm({ ...registerForm, name: event.target.value })}
                    autoComplete="name"
                    required
                  />
                </Field>
                <Field label="Email">
                  <Input
                    type="email"
                    value={registerForm.email}
                    onChange={(event) => setRegisterForm({ ...registerForm, email: event.target.value })}
                    autoComplete="email"
                    required
                  />
                </Field>
                <Field label="Password">
                  <Input
                    type="password"
                    value={registerForm.password}
                    onChange={(event) => setRegisterForm({ ...registerForm, password: event.target.value })}
                    autoComplete="new-password"
                    required
                  />
                </Field>
                <div className="grid sm:grid-cols-2 gap-3">
                  <Field label="Organization">
                    <Input
                      value={registerForm.organization_name}
                      onChange={(event) =>
                        setRegisterForm({ ...registerForm, organization_name: event.target.value })
                      }
                      required
                    />
                  </Field>
                  <Field label="Workspace">
                    <Input
                      value={registerForm.workspace_name}
                      onChange={(event) =>
                        setRegisterForm({ ...registerForm, workspace_name: event.target.value })
                      }
                      required
                    />
                  </Field>
                </div>
                <div className="grid sm:grid-cols-2 gap-3">
                  <Field label="Crop">
                    <Input
                      value={registerForm.crop}
                      onChange={(event) => setRegisterForm({ ...registerForm, crop: event.target.value })}
                    />
                  </Field>
                  <Field label="Region">
                    <Input
                      value={registerForm.region}
                      onChange={(event) => setRegisterForm({ ...registerForm, region: event.target.value })}
                    />
                  </Field>
                </div>
                <Button
                  type="submit"
                  disabled={isSubmitting}
                  className="w-full bg-[#10231B] hover:bg-[#16533C] text-white"
                >
                  {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  Create account
                </Button>
              </form>
            </TabsContent>
          </Tabs>
        </div>
      </main>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[12px] font-medium text-[#10231B] mb-1.5">{label}</span>
      {children}
    </label>
  );
}
