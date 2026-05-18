import { storageService } from "../../services/storageService.js";

const KEY = "agroai_portal_v2_session";

export const sessionService = {
  read() {
    const raw = storageService.get(KEY, null);
    if (!raw) return null;
    if (raw.expiresAt && Date.now() > raw.expiresAt) {
      storageService.remove(KEY);
      return null;
    }
    return raw;
  },
  write(session) {
    storageService.set(KEY, session);
  },
  clear() {
    storageService.remove(KEY);
  },
};
