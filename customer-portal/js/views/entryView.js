export function renderEntryView() {
  return `<main class="entry-screen">
    <section class="entry-brand">
      <img src="./assets/agro-ai-logo.png" alt="AGRO-AI" class="entry-logo" />
      <p class="eyebrow">AGRO-AI Enterprise</p>
      <h1>Water Command Center for connected irrigation environments.</h1>
      <p class="entry-copy">Connect controller runtimes, assemble live field context, generate irrigation recommendations, schedule execution tasks, and verify what happened.</p>
      <div class="truth-stack">
        <span>WiseConn runtime live</span>
        <span>Talgil runtime live</span>
        <span>Intelligence Engine live</span>
        <span>Input normalization live</span>
      </div>
    </section>

    <section class="entry-actions">
      <article class="login-card">
        <p class="eyebrow">Customer Login</p>
        <h2>Enterprise sign-in</h2>
        <p class="muted">Auth-ready scaffold. Production authentication and organization selection require backend auth endpoints before customer credentials are accepted.</p>
        <form id="login-form" class="form-stack">
          <label>Email<input id="login-email" name="email" type="email" autocomplete="email" placeholder="you@organization.com" required /></label>
          <label>Password<input name="password" type="password" autocomplete="current-password" placeholder="Password" required /></label>
          <a href="#" class="text-link">Forgot password?</a>
          <button class="button primary" type="submit">Continue to organization selector</button>
        </form>
        <div class="org-placeholder">
          <strong>Organization selector placeholder</strong>
          <span>Enabled after backend authentication returns customer organizations.</span>
        </div>
      </article>

      <article class="demo-card">
        <p class="eyebrow">Demo Environment</p>
        <h2>Launch AGRO-AI Demo Workspace</h2>
        <p>Open an isolated, credential-free demo tenant with embedded demo farms, controller environments, recommendations, execution tasks, verification states, reports, and audit events.</p>
        <button id="launch-demo" class="button primary wide" type="button">Launch Demo Environment</button>
        <p class="demo-disclaimer">Demo data is clearly marked and is not mixed with live production API telemetry.</p>
      </article>
    </section>
  </main>`;
}
