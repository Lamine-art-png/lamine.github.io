export const ROLE_PERMISSIONS = {
  owner: ["all"],
  admin: ["all"],
  farm_manager: ["view:all", "manage:recommendations", "manage:verification", "manage:integrations", "view:audit"],
  operator: ["view:all", "manage:verification", "view:intelligence"],
  advisor: ["view:all", "view:intelligence", "export:reports"],
  viewer: ["view:all"],
};

export function can(role, permission) {
  const permissions = ROLE_PERMISSIONS[role] || [];
  return permissions.includes("all") || permissions.includes(permission) || permissions.includes("view:all");
}
