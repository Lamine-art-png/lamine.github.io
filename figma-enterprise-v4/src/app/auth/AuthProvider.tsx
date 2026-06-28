import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { apiClient, LoginPayload, RegisterPayload } from "../api/client";

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

type BillingStatus = {
  plan?: string;
  subscription_status?: string;
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
  login: (email: string, password: string) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const INTERNAL_TEST_ENTITLEMENTS: Record<string, unknown> = {
  internal_testing: true,
  all_features: true,
  connectors: true,
  connector_uploads: true,
  report_exports: true,
  reports: true,
  can_export_reports: true,
  ai: true,
  agents: true,
  evidence: true,
  decisions: true,
  admin: true,
  billing: true,
  integrations: true,
};

function arrayFromResponse<T>(response: unknown, key: string): T[] {
  if (Array.isArray(response)) {
    return response as T[];
  }

  if (response && typeof response === "object" && key in response) {
    const value = (response as Record<string, unknown>)[key];
    return Array.isArray(value) ? (value as T[]) : [];
  }

  return [];
}

function getAccessToken(response: unknown) {
  if (!response || typeof response !== "object") {
    return null;
  }

  const data = response as Record<string, unknown>;
  return typeof data.access_token === "string" ? data.access_token : null;
}

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

function objectFromResponse<T>(response: unknown): T | null {
  return response && typeof response === "object" ? (response as T) : null;
}

function normalizeMe(response: unknown) {
  const data =
    response && typeof response === "object" ? (response as Record<string, unknown>) : {};
  const organization = (data.organization || data.currentOrganization || null) as Organization | null;
  const organizations = Array.isArray(data.organizations)
    ? (data.organizations as Organization[])
    : organization
      ? [organization]
      : [];
  const workspace = (data.workspace || data.currentWorkspace || null) as Workspace | null;

  return {
    user: (data.user || null) as User | null,
    organizations,
    currentOrganization: organization || organizations[0] || null,
    currentWorkspace: workspace,
    entitlements: {
      ...(((data.entitlements || {}) as Record<string, unknown>) || {}),
      ...INTERNAL_TEST_ENTITLEMENTS,
    },
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getStoredToken());
  const [user, setUser] = useState<User | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [currentOrganization, setCurrentOrganization] = useState<Organization | null>(null);
  const [currentWorkspace, setCurrentWorkspace] = useState<Workspace | null>(null);
  const [entitlements, setEntitlements] = useState<Record<string, unknown>>({});
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
    const billingResponse = await apiClient.getBillingStatus().catch(() => null);
    const normalized = normalizeMe(meResponse);
    const orgs = arrayFromResponse<Organization>(orgsResponse, "organizations");
    const workspaces = arrayFromResponse<Workspace>(workspacesResponse, "workspaces");
    const billing = objectFromResponse<BillingStatus>(billingResponse);
    const organization = {
      ...(orgs[0] || {}),
      ...(normalized.currentOrganization || {}),
      ...(billing?.plan ? { plan: billing.plan } : {}),
      ...(billing?.subscription_status ? { subscription_status: billing.subscription_status } : {}),
    };

    setUser(normalized.user);
    setOrganizations(orgs.length ? orgs : normalized.organizations);
    setCurrentOrganization(Object.keys(organization).length ? organization : null);
    setCurrentWorkspace(workspaces[0] || normalized.currentWorkspace || null);
    setEntitlements({
      ...normalized.entitlements,
      ...INTERNAL_TEST_ENTITLEMENTS,
    });
  }, [clearSession]);

  const login = useCallback(
    async (email: string, password: string) => {
      const response = await apiClient.login({ email, password } satisfies LoginPayload);
      const nextToken = getAccessToken(response);

      if (!nextToken) {
        throw new Error("Login response did not include an access token.");
      }

      applyToken(nextToken);
      await refreshMe();
    },
    [applyToken, refreshMe],
  );

  const register = useCallback(
    async (payload: RegisterPayload) => {
      const response = await apiClient.register(payload);
      const nextToken = getAccessToken(response);

      if (!nextToken) {
        throw new Error("Registration response did not include an access token.");
      }

      applyToken(nextToken);
      await refreshMe();
    },
    [applyToken, refreshMe],
  );

  const logout = useCallback(async () => {
    await apiClient.logout().catch(() => null);
    clearSession();
  }, [clearSession]);

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
      .catch(() => clearSession())
      .finally(() => setIsLoading(false));
  }, [clearSession, refreshMe, token]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      organizations,
      currentOrganization,
      currentWorkspace,
      entitlements,
      token,
      isLoading,
      isAuthenticated: Boolean(token && user),
      login,
      register,
      logout,
      refreshMe,
    }),
    [
      user,
      organizations,
      currentOrganization,
      currentWorkspace,
      entitlements,
      token,
      isLoading,
      login,
      register,
      logout,
      refreshMe,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
