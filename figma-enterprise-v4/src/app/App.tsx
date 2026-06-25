import { RouterProvider } from "react-router";
import { AuthProvider, useAuth } from "./auth/AuthProvider";
import { AuthScreen } from "./components/AuthScreen";
import { router } from "./routes";

export default function App() {
  return (
    <AuthProvider>
      <AuthenticatedApp />
    </AuthProvider>
  );
}

function AuthenticatedApp() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F6F4EE] text-[#68776F] text-sm">
        Loading session
      </div>
    );
  }

  if (!isAuthenticated) {
    return <AuthScreen />;
  }

  return <RouterProvider router={router} />;
}
