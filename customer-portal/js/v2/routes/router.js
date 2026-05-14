export const ROUTES = [
  "command_center",
  "farms",
  "intelligence",
  "verification",
  "reports",
  "integrations",
  "settings",
  "audit_logs",
];

export function normalizeRoute(route) {
  return ROUTES.includes(route) ? route : "command_center";
}
