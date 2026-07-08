import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiClient, ApiError, LoginPayload, RegisterPayload } from "../api/client";

const tokenKey = "agroai_access_token";

type User = {
  id?: string;
  name?: string;
  email?: string;
};

type Organization = {
  id?: string;
  name?: string;
  plan?: string;
  subscription_status?: string;
  role?: string;
};

type Workspace = {
  id?: string;
  name?: string;
  status?: string;
  evaluation_status?: string;
};

type VerificationState = {
  email?: string;
  status?: string;
  message?: string;
};

type AuthContextValue = {
  user: User | null;
  organizations: Organization[];
  currentOrganization: Organization | null;
  currentWorkspace: Workspace | null;
  entitlements: Record<string, unknown>;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  verification: VerificationState | null;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
  requestVerification: (email?: string) => Promise<string>;
  confirmVerification: (token: string) => Promise<void>;
  clearVerification: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function jwtPayload(token: string): Record<string, unknown> | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    return JSON.parse(window.atob(padded));
  } catch {
    return null;
  }
}

function isExpiredToken(token: string | null) {
  if (!token) return false;
  const payload = jwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp !== "number") return false;
  return exp <= Math.floor(Date.now() / 1000) + 30;
}

function getStoredToken() {
  const stored = localStorage.getItem(tokenKey);
  if (isExpiredToken(stored)) {
    localStorage.removeItem(tokenKey);
    return null;
  }
  return stored;
}

function arrayFromResponse<T>(response: unknown, key: string): T[] {
  if (Array.isArray(response)) return response as T[];
  if (response && typeof response === "object" && key in response) {
    const value = (response as Record<string, unknown>)[key];
    return Array.isArray(value) ? (value as T[]) : [];
  }
  return [];
}

function getAccessToken(response: unknown) {
  if (!response || typeof response !== "object") return null;
  const data = response as Record<string, unknown>;
  return typeof data.access_token === "string" ? data.access_token : null;
}

function normalizeMe(response: unknown) {
  const data = response && typeof response === "object" ? (response as Record<string, unknown>) : {};
  const currentOrganization = (data.current_organization || null) as Organization | null;
  const organizations = Array.isArray(data.organizations) ? (data.organizations as Organization[]) : currentOrganization ? [currentOrganization] : [];
  const rawVerification = (data.verification || null) as VerificationState | null;
  return {
    user: (data.user || null) as User | null,
    organizations,
    currentOrganization: currentOrganization || organizations[0] || null,
    currentWorkspace: null as Workspace | null,
    entitlements: ((data.entitlements || {}) as Record<string, unknown>) || {},
    verification: rawVerification?.status === "verified" ? null : rawVerification,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getStoredToken());
  const [user, setUser] = useState<User | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [currentOrganization, setCurrentOrganization] = useState<Organization | null>(null);
  const [currentWorkspace, setCurrentWorkspace] = useState<Workspace | null>(null);
  const [entitlements, setEntitlements] = useState<Record<string, unknown>>({});
  const [verification, setVerification] = useState<VerificationState | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const clearSession = useCallback(() => {
    localStorage.removeItem(tokenKey);
    setToken(null);
    setUser(null);
    setOrganizations([]);
    setCurrentOrganization(null);
    setCurrentWorkspace(null);
    setEntitlements({});
  }, []);

  const clearVerification = useCallback(() => {
    setVerification(null);
  }, []);

  const applyToken = useCallback((nextToken: string) => {
    localStorage.setItem(tokenKey, nextToken);
    setToken(nextToken);
  }, []);

  const refreshMe = useCallback(async () => {
    if (isExpiredToken(localStorage.getItem(tokenKey))) {
      clearSession();
      return;
    }
    const meResponse = await apiClient.me();
    const orgsResponse = await apiClient.getOrgs().catch(() => null);
    const workspacesResponse = await apiClient.getWorkspaces().catch(() => null);
    const normalized = normalizeMe(meResponse);
    const orgs = arrayFromResponse<Organization>(orgsResponse, "organizations");
    const workspaces = arrayFromResponse<Workspace>(workspacesResponse, "workspaces");
    setUser(normalized.user);
    setOrganizations(orgs.length ? orgs : normalized.organizations);
    setCurrentOrganization(normalized.currentOrganization || orgs[0] || null);
    setCurrentWorkspace(workspaces[0] || null);
    setEntitlements(normalized.entitlements);
    setVerification(normalized.verification);
  }, [clearSession]);

  const handleVerificationRequired = useCallback((error: ApiError, fallbackEmail?: string) => {
    clearSession();
    setVerification({
      email: fallbackEmail,
      status: "unverified",
      message: error.message || "Verify your email to activate your AGRO-AI workspace.",
    });
  }, [clearSession]);

  const login = useCallback(async (email: string, password: string) => {
    try {
      const response = await apiClient.login({ email, password } satisfies LoginPayload);
      const nextToken = getAccessToken(response);
      if (!nextToken) {
        throw new Error("Login response did not include an access token.");
      }
      applyToken(nextToken);
      setVerification(null);
      await refreshMe();
    } catch (error) {
      const apiError = error as ApiError;
      if (apiError.code === "email_verification_required") {
        handleVerificationRequired(apiError, email);
      }
      throw error;
    }
  }, [applyToken, handleVerificationRequired, refreshMe]);

  const register = useCallback(async (payload: RegisterPayload) => {
    const response = await apiClient.register(payload) as Record<string, unknown>;
    setVerification({
      email: payload.email,
      status: String((response.verification as Record<string, unknown> | undefined)?.status || "unverified"),
      message: String(response.message || "Verify your email to activate your AGRO-AI workspace."),
    });
    clearSession();
  }, [clearSession]);

  const logout = useCallback(async () => {
    await apiClient.logout().catch(() => null);
    clearSession();
  }, [clearSession]);

  const requestVerification = useCallback(async (email?: string) => {
    const response = await apiClient.auth.requestEmailVerification(email ? { email } : undefined) as Record<string, unknown>;
    const message = String(response.message || "If an account exists, we sent a verification email.");
    setVerification((current) => ({ ...(current || {}), email: email || current?.email, message }));
    return message;
  }, []);

  const confirmVerification = useCallback(async (verificationToken: string) => {
    const response = await apiClient.auth.confirmEmailVerification({ token: verificationToken }) as Record<string, unknown>;
    const nextToken = getAccessToken(response);
    const responseVerification = (response.verification || null) as VerificationState | null;

    // Backward-compatible fallback while frontend/backend deployments roll out.
    // The new backend returns a session token; an older backend still yields a
    // clear verified state instead of silently dropping the customer.
    if (!nextToken) {
      setVerification({
        email: responseVerification?.email,
        status: "verified",
        message: String(response.message || "Email verified. Sign in to continue."),
      });
      return;
    }

    // Establish authenticated state immediately from the atomic verify response.
    // A secondary /me refresh enriches workspace state but cannot undo successful
    // verification if another service is briefly unavailable during launch.
    const normalized = normalizeMe(response);
    applyToken(nextToken);
    setUser(normalized.user);
    setOrganizations(normalized.organizations);
    setCurrentOrganization(normalized.currentOrganization);
    setCurrentWorkspace(normalized.currentWorkspace);
    setEntitlements(normalized.entitlements);
    setVerification(null);

    await refreshMe().catch(() => null);
    setVerification(null);
  }, [applyToken, refreshMe]);

  useEffect(() => {
    window.addEventListener("agroai:unauthorized", clearSession);
    return () => window.removeEventListener("agroai:unauthorized", clearSession);
  }, [clearSession]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (isExpiredToken(localStorage.getItem(tokenKey))) {
        clearSession();
      }
    }, 60_000);
    return () => window.clearInterval(interval);
  }, [clearSession]);

  useEffect(() => {
    if (!token) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    refreshMe()
      .catch((error) => {
        const apiError = error as ApiError;
        if (apiError.code === "email_verification_required") {
          handleVerificationRequired(apiError);
        } else {
          clearSession();
        }
      })
      .finally(() => setIsLoading(false));
  }, [clearSession, handleVerificationRequired, refreshMe, token]);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    organizations,
    currentOrganization,
    currentWorkspace,
    entitlements,
    token,
    isLoading,
    isAuthenticated: Boolean(token && user),
    verification,
    login,
    register,
    logout,
    refreshMe,
    requestVerification,
    confirmVerification,
    clearVerification,
  }), [clearVerification, confirmVerification, currentOrganization, currentWorkspace, entitlements, isLoading, login, logout, organizations, refreshMe, register, requestVerification, token, user, verification]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}
