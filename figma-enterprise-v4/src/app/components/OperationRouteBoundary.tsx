import { Outlet } from "react-router";
import { useAuth } from "../auth/AuthProvider";

export function OperationRouteBoundary() {
  const { currentWorkspace } = useAuth();
  return <Outlet key={currentWorkspace?.id || "no-operation"} />;
}
