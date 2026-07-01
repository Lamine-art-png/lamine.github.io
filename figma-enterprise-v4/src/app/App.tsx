import { RouterProvider } from "react-router";
import { AuthProvider, useAuth } from "./auth/AuthProvider";
import { AuthScreen } from "./components/AuthScreen";
import { PricingPage } from "./components/ProductShell";
import { VerifyEmailPage } from "./components/VerifyEmail";
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

  if (window.location.pathname === "/verify-email") {
    return <VerifyEmailPage />;
  }

  if (window.location.pathname === "/pricing" && !isAuthenticated) {
    return <PricingPage />;
  }

  if (!isAuthenticated) {
    return <AuthScreen />;
  }

  return <RouterProvider router={router} />;
}
