import { ROUTES } from "../routes/router.js";
import { can } from "../auth/rbac.js";

const labels = {
  command_center: "Command Center",
  farms: "Farms",
  intelligence: "Intelligence",
  verification: "Verification",
  reports: "Reports",
  integrations: "Integrations",
  settings: "Settings",
  audit_logs: "Audit Logs",
};

export function shellHtml(state, inner) {
  const role = state.session?.user?.role || "viewer";
  const routeItems = ROUTES.filter((route) => {
    if (route === "integrations") return can(role, "manage:integrations");
    if (route === "audit_logs") return can(role, "view:audit");
    return true;
  });

  const orgOptions = state.app.organizations
    .map((org) => `<option value="${org.id}" ${org.id === state.app.organizationId ? "selected" : ""}>${org.name}</option>`)
    .join("");

  const farmOptions = state.app.farms
    .filter((farm) => farm.organizationId === state.app.organizationId)
    .map((farm) => `<option value="${farm.id}" ${farm.id === state.app.farmId ? "selected" : ""}>${farm.name}</option>`)
    .join("");

  return `<div class="v2-shell">
    <aside class="v2-sidebar">
      <div class="brand">AGRO-AI Portal v2</div>
      ${routeItems.map((r) => `<button data-route="${r}" class="nav-btn ${state.app.route === r ? "active" : ""}">${labels[r]}</button>`).join("")}
      <button class="nav-btn demo-launch" data-action="launch-demo">Launch Demo Environment</button>
    </aside>
    <section class="v2-main">
      <header class="v2-header card">
        <div class="selectors">
          <label>Organization<select data-select="organization">${orgOptions}</select></label>
          <label>Farm<select data-select="farm">${farmOptions}</select></label>
        </div>
        <div class="header-right">
          <div class="notifications">${state.app.notifications[0]?.text || "No notifications"}</div>
          <div class="profile">${state.session?.user?.name} • ${role}</div>
          <button data-action="logout" class="btn danger">Logout</button>
        </div>
      </header>
      ${state.app.error ? `<div class="state-banner error">${state.app.error}</div>` : ""}
      ${state.app.success ? `<div class="state-banner success">${state.app.success}</div>` : ""}
      ${state.app.loading ? `<div class="state-banner loading">Loading enterprise workspace...</div>` : ""}
      ${inner}
    </section>
  </div>`;
}
