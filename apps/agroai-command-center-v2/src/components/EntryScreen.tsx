import { useState, type FormEvent } from "react";
import { apiClient, setAccessToken } from "../api/client";
import { actions, useCommandStore } from "../state/commandStore";

export function EntryScreen() {
  const message = useCommandStore((s) => s.productionSignInMessage);
  const onboardingOpen = useCommandStore((s) => s.onboardingOpen);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [organization, setOrganization] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setStatus(null);
    const response =
      mode === "login"
        ? await apiClient.login(email, password)
        : await apiClient.register({
            email,
            password,
            name,
            organization_name: organization || "Evaluation organization",
            workspace_name: "Evaluation workspace",
          });
    setBusy(false);
    if (!response.ok || !response.data) {
      setStatus("Sign-in failed. Check credentials or API availability.");
      return;
    }
    setAccessToken(response.data.access_token);
    setStatus(`${response.data.current_organization.name} connected.`);
    await actions.openEvaluationWorkspace();
  }

  return (
    <main className="entry-screen">
      <section className="entry-panel" aria-label="Water Command Center entry">
        <p className="eyebrow">Enterprise irrigation intelligence</p>
        <h1>AGRO-AI Water Command Center</h1>
        <p className="entry-subtitle">Turn scattered irrigation data into verified water decisions.</p>
        <div className="entry-actions">
          <button className="btn primary" onClick={() => void actions.openEvaluationWorkspace()}>
            Open evaluation workspace
          </button>
          <button className="btn" type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "Create account" : "Sign in"}
          </button>
          <button className="btn ghost" onClick={() => actions.openOnboarding()}>
            Request enterprise onboarding
          </button>
        </div>
        <form className="auth-form" onSubmit={submitAuth}>
          <label>
            <span>Email</span>
            <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required autoComplete="email" />
          </label>
          <label>
            <span>Password</span>
            <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required minLength={8} autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </label>
          {mode === "register" && (
            <>
              <label>
                <span>Name</span>
                <input value={name} onChange={(event) => setName(event.target.value)} type="text" autoComplete="name" />
              </label>
              <label>
                <span>Organization</span>
                <input value={organization} onChange={(event) => setOrganization(event.target.value)} type="text" required />
              </label>
            </>
          )}
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Connecting..." : mode === "login" ? "Sign in" : "Register"}
          </button>
        </form>
        {status && <p className="entry-message">{status}</p>}
        {message && <p className="entry-message">{message}</p>}
      </section>

      {onboardingOpen && (
        <div className="drawer-scrim" onClick={(e) => e.target === e.currentTarget && actions.closeOnboarding()}>
          <aside className="drawer onboarding-drawer" role="dialog" aria-modal="true" aria-label="Enterprise onboarding brief">
            <div className="drawer-head">
              <div>
                <p className="eyebrow">Enterprise onboarding</p>
                <h2>Production workspace requirements</h2>
              </div>
              <button className="btn ghost compact" onClick={() => actions.closeOnboarding()}>
                Close
              </button>
            </div>
            <div className="drawer-body">
              <dl className="brief-def">
                <div>
                  <dt>Identity</dt>
                  <dd>Provision tenant users, roles, and production identity before production access.</dd>
                </div>
                <div>
                  <dt>Sources</dt>
                  <dd>Register controller, weather, soil, flow, field-observation, and partner feed sources server-side.</dd>
                </div>
                <div>
                  <dt>Evidence</dt>
                  <dd>Move evaluation-session evidence into durable tenant persistence during production onboarding.</dd>
                </div>
                <div>
                  <dt>Calibration</dt>
                  <dd>Replace transparent v0.2 defaults with farm-specific crop, soil, flow, and controller calibration.</dd>
                </div>
              </dl>
            </div>
          </aside>
        </div>
      )}
    </main>
  );
}
