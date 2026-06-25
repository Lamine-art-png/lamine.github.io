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
import { Sources } from "./components/Sources";
import { Audit } from "./components/Audit";
import { Admin } from "./components/Admin";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: MainLayout,
    children: [
      { index: true, Component: Overview },
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
    ],
  },
]);
