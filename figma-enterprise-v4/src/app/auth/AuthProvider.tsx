import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiClient, ApiError, LoginPayload, RegisterPayload } from "../api/client";

const tokenKey = "agroai_access_token";
const activeWorkspaceKeyPrefix = "agroai_active_operation_v1:";

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

export type Workspace = {
  id?: string;
  organization_id?: string;
  name?: string;
  crop?: string;
  region?: string;
  mode?: string;
  status?: string;
  evaluation_status?: string;
  created_at?: string;
  updated_at?: string;
};

export type CreateOperationPayload = {
  name: string;
  crop?: string;
  region?: string;
  mode?: "evaluation" | "live";
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
  workspaces: Workspace[];
  currentWorkspace: Workspace | null;
  entitlements: Record<string, unknown>;
  platformAdmin: boolean;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  verification: VerificationState | null;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
  selectWorkspace: (workspaceId: string) => void;
  createWorkspace: (payload: CreateOperationPayload) => Promise<Workspace>;
  updateWorkspace: (workspaceId: string, payload: { name: string }) => Promise<Workspace>;
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

function workspaceStorageKey(organizationId?: string) {
  return `${activeWorkspaceKeyPrefix}${organizationId || "default"}`;
}

function storedWorkspaceId(organizationId?: string) {
  try {
    return localStorage.getItem(workspaceStorageKey(organizationId));
  } catch {
    return null;
  }
}

function storeWorkspaceId(organizationId: string | undefined, workspaceId: string | undefined) {
  if (!workspaceId) return;
  try {
    localStorage.setItem(workspaceStorageKey(organizationId), workspaceId);
  } catch {
    // Active-operation persistence is best effort; server state remains authoritative.
  }
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
    platformAdmin: data.platform_admin === true,
    verification: rawVerification?.status === "verified" ? null : rawVerification,
  };
}

function workspaceFromResponse(response: unknown): Workspace | null {
  if (!response || typeof response !== "object") return null;
  const data = response as Record<string, unknown>;
  const candidate = data.workspace;
  return candidate && typeof candidate === "object" ? candidate as Workspace : null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getStoredToken());
  const [user, setUser] = useState<User | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [currentOrganization, setCurrentOrganization] = useState<Organization | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [currentWorkspace, setCurrentWorkspace] = useState<Workspace | null>(null);
  const [entitlements, setEntitlements] = useState<Record<string, unknown>>({});
  const [platformAdmin, setPlatformAdmin] = useState(false);
  const [verification, setVerification] = useState<VerificationState | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const clearSession = useCallback(() => {
    localStorage.removeItem(tokenKey);
    setToken(null);
    setUser(null);
    setOrganizations([]);
    setCurrentOrganization(null);
    setWorkspaces([]);
    setCurrentWorkspace(null);
    setEntitlements({});
    setPlatformAdmin(false);
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
    const nextOrganization = normalized.currentOrganization || orgs[0] || null;
    const nextWorkspaces = arrayFromResponse<Workspace>(workspacesResponse, "workspaces");
    const organizationWorkspaces = nextOrganization?.id
      ? nextWorkspaces.filter((workspace) => !workspace.organization_id || workspace.organization_id === nextOrganization.id)
      : nextWorkspaces;

    setUser(normalized.user);
    setOrganizations(orgs.length ? orgs : normalized.organizations);
    setCurrentOrganization(nextOrganization);
    setWorkspaces(nextWorkspaces);
    setCurrentWorkspace((previous) => {
      const preferredId = previous?.organization_id === nextOrganization?.id
        ? previous.id
        : storedWorkspaceId(nextOrganization?.id);
      const selected = organizationWorkspaces.find((workspace) => workspace.id === preferredId) || organizationWorkspaces[0] || null;
      storeWorkspaceId(nextOrganization?.id, selected?.id);
      return selected;
    });
    setEntitlements(normalized.entitlements);
    setPlatformAdmin(normalized.platformAdmin);
    setVerification(normalized.verification);
  }, [clearSession]);

  const selectWorkspace = useCallback((workspaceId: string) => {
    setCurrentWorkspace((previous) => {
      const selected = workspaces.find((workspace) => workspace.id === workspaceId);
      if (!selected) return previous;
      if (currentOrganization?.id && selected.organization_id && selected.organization_id !== currentOrganization.id) return previous;
      storeWorkspaceId(currentOrganization?.id, selected.id);
      return selected;
    });
  }, [currentOrganization?.id, workspaces]);

  const createWorkspace = useCallback(async (payload: CreateOperationPayload) => {
    if (!currentOrganization?.id) throw new Error("No active organization is available.");
    const response = await apiClient.post("/v1/workspaces", {
      organization_id: currentOrganization.id,
      name: payload.name,
      crop: payload.crop,
      region: payload.region,
      mode: payload.mode || "evaluation",
    }) as Record<string, unknown>;
    const workspace = workspaceFromResponse(response);
    if (!workspace?.id) throw new Error("The operation was created without a valid workspace identifier.");
    setWorkspaces((current) => [...current.filter((item) => item.id !== workspace.id), workspace]);
    setCurrentWorkspace(workspace);
    storeWorkspaceId(currentOrganization.id, workspace.id);
    if (response.entitlements && typeof response.entitlements === "object") {
      setEntitlements(response.entitlements as Record<string, unknown>);
    }
    return workspace;
  }, [currentOrganization?.id]);

  const updateWorkspace = useCallback(async (workspaceId: string, payload: { name: string }) => {
    const response = await apiClient.patch(`/v1/workspaces/${encodeURIComponent(workspaceId)}`, payload) as Record<string, unknown>;
    const workspace = workspaceFromResponse(response);
    if (!workspace?.id) throw new Error("The operation update did not return a valid workspace.");
    setWorkspaces((current) => current.map((item) => item.id === workspace.id ? workspace : item));
    setCurrentWorkspace((current) => current?.id === workspace.id ? workspace : current);
    return workspace;
  }, []);

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

    if (!nextToken) {
      setVerification({
        email: responseVerification?.email,
        status: "verified",
        message: String(response.message || "Email verified. Sign in to continue."),
      });
      return;
    }

    const normalized = normalizeMe(response);
    applyToken(nextToken);
    setUser(normalized.user);
    setOrganizations(normalized.organizations);
    setCurrentOrganization(normalized.currentOrganization);
    setWorkspaces([]);
    setCurrentWorkspace(normalized.currentWorkspace);
    setEntitlements(normalized.entitlements);
    setPlatformAdmin(normalized.platformAdmin);
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
    workspaces,
    currentWorkspace,
    entitlements,
    platformAdmin,
    token,
    isLoading,
    isAuthenticated: Boolean(token && user),
    verification,
    login,
    register,
    logout,
    refreshMe,
    selectWorkspace,
    createWorkspace,
    updateWorkspace,
    requestVerification,
    confirmVerification,
    clearVerification,
  }), [clearVerification, confirmVerification, createWorkspace, currentOrganization, currentWorkspace, entitlements, isLoading, login, logout, organizations, platformAdmin, refreshMe, register, requestVerification, selectWorkspace, token, updateWorkspace, user, verification, workspaces]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}
