import { escapeHtml } from "../components/dom.js";

export function renderEntryView(state) {
  const error = state.session.loginError;
  return `<main class="entry-screen entry-premium">
    <section class="entry-brand value-panel">
      <img src="./assets/agro-ai-logo.png" alt="AGRO-AI" class="entry-logo" />
      <p class="eyebrow">AGRO-AI Water Command Center</p>
      <h1>Recommendation, execution, and verification for connected irrigation environments.</h1>
      <p class="entry-copy">A customer-facing operations layer for controller environments, live field context, irrigation decisions, planned-vs-applied verification, and executive reporting.</p>
      <div class="proof-point-grid" aria-label="Portal proof points">
        <span>WiseConn environment support</span>
        <span>Talgil environment support</span>
        <span>Live context intelligence</span>
        <span>Planned vs applied verification</span>
        <span>Executive reporting</span>
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
        <h2>Open the Water Command Center</h2>
        <p>Explore a simulated enterprise workspace with WiseConn and Talgil environments, recommendations, verification, and reports.</p>
        <button id="launch-demo" class="button primary wide demo-launch" type="button">Open Water Command Center</button>
        <p class="demo-disclaimer">One click. No production credentials. Sample data is labeled after entering the workspace.</p>
      </article>
    </section>
  </main>`;
}
