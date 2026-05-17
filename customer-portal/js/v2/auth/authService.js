import { sessionService } from "./sessionService.js";

const MOCK_USERS = {
  "owner@agroai.com": { id: "u1", name: "Elena Ruiz", role: "owner", organizationId: "org_demo" },
  "manager@agroai.com": { id: "u2", name: "Ravi Kumar", role: "farm_manager", organizationId: "org_demo" },
  "operator@agroai.com": { id: "u3", name: "Mateo Silva", role: "operator", organizationId: "org_demo" },
  "viewer@agroai.com": { id: "u4", name: "Dana Ross", role: "viewer", organizationId: "org_demo" },
};

export const authService = {
  login({ email, password, remember }) {
    const user = MOCK_USERS[email?.toLowerCase()];
    if (!user || !password) {
      return { ok: false, error: "Invalid credentials. Verify email and password." };
    }
    const ttlMs = remember ? 1000 * 60 * 60 * 24 * 30 : 1000 * 60 * 60 * 8;
    const session = {
      token: `session_${Math.random().toString(36).slice(2)}`,
      refreshToken: `refresh_${Math.random().toString(36).slice(2)}`,
      user,
      remember,
      expiresAt: Date.now() + ttlMs,
      createdAt: new Date().toISOString(),
    };
    sessionService.write(session);
    return { ok: true, session };
  },
  logout() {
    sessionService.clear();
    return { ok: true };
  },
  restore() {
    return sessionService.read();
  },
  requestPasswordReset(email) {
    if (!email) return { ok: false, error: "Email is required." };
    return { ok: true, message: `Password reset instructions prepared for ${email}.` };
  },
  completePasswordReset({ token, password }) {
    if (!token || !password) return { ok: false, error: "Reset token and new password required." };
    return { ok: true, message: "Password reset scaffold completed. Connect backend endpoint to finalize." };
  },
};
