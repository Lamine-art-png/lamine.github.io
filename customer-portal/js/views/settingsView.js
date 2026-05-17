import { table } from "../components/ui.js";

export function renderSettings() {
  return `<div class="screen-stack"><section class="panel-card admin-scaffold"><div class="section-heading"><p class="eyebrow">Settings</p><h2>Enterprise administration</h2><p>These controls are intentionally staged until backend administration endpoints are enabled.</p></div>${table(
    ["Area", "Current state", "Backend requirement"],
    [
      ["Organization profile", "Backend administration endpoint required", "Organization profile API"],
      ["Users and roles", "Backend administration endpoint required", "Identity and RBAC service"],
      ["Provider credentials", "Backend credential endpoint required", "Secure credential vault endpoint"],
      ["Language", "Backend administration endpoint required", "Localization preferences API"],
    ],
    "Administration endpoints pending",
    "Settings modules will become active as backend administration capabilities are enabled."
  )}</section></div>`;
}
