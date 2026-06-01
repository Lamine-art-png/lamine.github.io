export type Route = "command" | "sources" | "reports" | "integrations" | "compliance" | "settings";

export interface CommandState {
  activeRoute: Route;
  complianceEnabled: boolean;
}

export const initialCommandState: CommandState = {
  activeRoute: "command",
  complianceEnabled: import.meta.env.VITE_CALIFORNIA_COMPLIANCE_PACK_ENABLED === "true",
};
