import { escapeHtml } from "../components/dom.js";

export function renderEntryView(state) {
  const error = state.session.loginError;
  return `<main class="entry-screen entry-premium">
    <section class="entry-brand value-panel">
      <img src="./assets/agro-ai-logo.png" alt="AGRO-AI" class="entry-logo" />
      <p class="eyebrow">AGRO-AI Enterprise Operating System</p>
      <h1>Intelligence, WaterOps, and Assurance in one evidence-backed workspace.</h1>
      <p class="entry-copy">AGRO-AI turns irrigation telemetry, field records, proof packages, and agent workflows into review-ready operating decisions.</p>
      <div class="proof-point-grid" aria-label="Portal proof points">
        <span>AI-assisted action queue</span>
        <span>Evidence-backed decisions</span>
        <span>WaterOps verification</span>
        <span>Assurance Passport workflows</span>
        <span>Reviewer-gated proof packages</span>
      </div>
      <div class="compatibility-strip" aria-label="Integration compatibility">
        <span>Integrated with WiseConn</span>
        <span>Integrated with Talgil</span>
        <span>Compatible with additional telemetry and irrigation systems</span>
      </div>
      <p class="auth-safe-note">Customer authentication is prepared as an enterprise access surface. Production sign-in requires backend identity endpoints.</p>
    </section>

    <section class="entry-actions access-panel">
      <article class="login-card customer-access-card">
        <p class="eyebrow">Customer Access</p>
        <h2>Access your workspace</h2>
        <p class="muted">Use organization-issued credentials when production authentication is enabled. Evaluation access is available immediately below.</p>
        <form id="login-form" class="form-stack" novalidate>
          <label>Email<input id="login-email" name="email" type="email" autocomplete="email" placeholder="you@organization.com" required /></label>
          <label>Password<input name="password" type="password" autocomplete="current-password" placeholder="Password" required /></label>
          <div class="form-row">
            <label class="checkbox-label"><input name="remember" type="checkbox" /> Remember session</label>
            <a href="mailto:support@agroai-pilot.com?subject=AGRO-AI%20workspace%20password%20reset" class="text-link">Forgot password?</a>
          </div>
          <button class="button primary" type="submit">Continue to workspace</button>
          <p id="login-error" class="form-error ${error ? "" : "hidden"}" role="alert">${escapeHtml(error)}</p>
          ${error ? '<button id="live-status-preview" class="button secondary" type="button">Open live environment status preview</button>' : ''}
        </form>
        <div class="org-placeholder">
          <strong>Workspace access</strong>
          <span>Organization selection appears here after backend authentication verifies the user.</span>
        </div>
      </article>

      <article class="demo-card interactive-demo-card">
        <p class="eyebrow">Evaluation Workspace</p>
        <h2>Open the Enterprise OS workspace</h2>
        <p>Explore a clearly labeled evaluation workspace with representative irrigation, assurance, evidence, agent, and reporting flows.</p>
        <button id="launch-demo" class="button primary wide demo-launch" type="button">Open Evaluation Workspace</button>
        <p class="demo-disclaimer">One click. No production credentials. Sample data is labeled after entering the workspace.</p>
      </article>
    </section>
  </main>`;
}
