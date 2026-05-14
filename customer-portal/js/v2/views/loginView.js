export function loginView(state) {
  const mode = state.authUi.mode;
  return `<div class="auth-wrap">
    <section class="card auth-card">
      <h1>AGRO-AI Enterprise Access</h1>
      <p>Secure access to multi-tenant irrigation intelligence operations.</p>
      ${state.authUi.message ? `<p class="auth-message">${state.authUi.message}</p>` : ""}
      ${mode === "login" ? loginForm() : ""}
      ${mode === "forgot" ? forgotForm() : ""}
      ${mode === "reset" ? resetForm() : ""}
      <div class="auth-switch">
        <button data-action="auth-mode" data-mode="login">Login</button>
        <button data-action="auth-mode" data-mode="forgot">Forgot password</button>
        <button data-action="auth-mode" data-mode="reset">Reset scaffold</button>
      </div>
      <p class="muted">Demo users: owner@agroai.com, manager@agroai.com, operator@agroai.com, viewer@agroai.com (any password).</p>
    </section>
  </div>`;
}

function loginForm() {
  return `<form data-form="login" class="form-grid">
      <label>Email<input type="email" name="email" required placeholder="name@company.com" /></label>
      <label>Password<input type="password" name="password" required placeholder="••••••••" /></label>
      <label class="remember"><input type="checkbox" name="remember" checked />Remember me (30-day session)</label>
      <button class="btn primary" type="submit">Sign in</button>
    </form>`;
}

function forgotForm() {
  return `<form data-form="forgot" class="form-grid">
      <label>Work email<input type="email" name="email" required placeholder="name@company.com" /></label>
      <button class="btn primary" type="submit">Send reset instructions</button>
    </form>`;
}

function resetForm() {
  return `<form data-form="reset" class="form-grid">
      <label>Reset token<input name="token" required placeholder="paste token" /></label>
      <label>New password<input type="password" name="password" required /></label>
      <button class="btn primary" type="submit">Complete reset</button>
    </form>`;
}
