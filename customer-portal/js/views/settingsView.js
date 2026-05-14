import { table } from "../components/ui.js";

export function renderSettings() {
  return `<div class="screen-stack"><section class="panel-card"><div class="section-heading"><p class="eyebrow">Settings</p><h2>Enterprise administration</h2><p>Placeholders are intentionally explicit until backend administration APIs are enabled.</p></div>${table(
    ["Area", "Status", "Backend requirement"],
    [
      ["Organization profile", "Placeholder", "Organization profile API"],
      ["Users and roles", "Placeholder", "Backend identity and RBAC"],
      ["Provider credentials", "Backend-required", "Secure credential vault endpoint"],
      ["Language", "Placeholder", "Localization preferences"],
    ],
    "No settings",
    "Settings modules will appear as backend capabilities are enabled."
  )}</section></div>`;
}
