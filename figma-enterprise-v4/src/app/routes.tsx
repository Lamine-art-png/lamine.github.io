import { createBrowserRouter } from "react-router";
import { MainLayout } from "./components/MainLayout";
import { Overview } from "./components/Overview";
import { Operations } from "./components/Operations";
import { Assurance } from "./components/Assurance";
import { Evidence } from "./components/Evidence";
import { Reports } from "./components/Reports";
import { Agents } from "./components/Agents";
import { Intelligence } from "./components/Intelligence";
import { Integrations } from "./components/Integrations";
import { DecisionWorkbench, Exceptions, Fields, Readiness, ReportFactory } from "./components/OperatorCockpit";
import { Sources } from "./components/Sources";
import { Audit } from "./components/Audit";
import { Admin } from "./components/Admin";
import {
  BillingPage,
  OnboardingPage,
  PricingPage,
  ProfilePage,
  SecurityPage,
  SupportPage,
  TeamPage,
  WorkspaceSettingsPage,
} from "./components/ProductShell";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: MainLayout,
    children: [
      { index: true, Component: Overview },
      { path: "field-queue", Component: Overview },
      { path: "tasks", Component: Overview },
      { path: "readiness", Component: Readiness },
      { path: "fields", Component: Fields },
      { path: "exceptions", Component: Exceptions },
      { path: "decision-workbench", Component: DecisionWorkbench },
      { path: "report-factory", Component: ReportFactory },
      { path: "operations", Component: Operations },
      { path: "assurance", Component: Assurance },
      { path: "evidence", Component: Evidence },
      { path: "reports", Component: Reports },
      { path: "agents", Component: Agents },
      { path: "intelligence", Component: Intelligence },
      { path: "integrations", Component: Integrations },
      { path: "sources", Component: Sources },
      { path: "audit", Component: Audit },
      { path: "admin", Component: Admin },
      { path: "pricing", Component: PricingPage },
      { path: "profile", Component: ProfilePage },
      { path: "billing", Component: BillingPage },
      { path: "security", Component: SecurityPage },
      { path: "support", Component: SupportPage },
      { path: "settings", Component: WorkspaceSettingsPage },
      { path: "team", Component: TeamPage },
      { path: "onboarding", Component: OnboardingPage },
    ],
  },
]);
