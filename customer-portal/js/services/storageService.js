const PREFIX = "terris:";
const LEGACY_PREFIX = "velia:";

export const storageService = {
  set(key, value) {
    localStorage.setItem(`${PREFIX}${key}`, JSON.stringify(value));
  },
  get(key, fallback) {
    const raw = localStorage.getItem(`${PREFIX}${key}`);
    if (raw) {
      try { return JSON.parse(raw); } catch { return fallback; }
    }
    const legacyRaw = localStorage.getItem(`${LEGACY_PREFIX}${key}`);
    if (!legacyRaw) return fallback;
    try {
      const parsed = JSON.parse(legacyRaw);
      localStorage.setItem(`${PREFIX}${key}`, JSON.stringify(parsed));
      return parsed;
    } catch { return fallback; }
  },
  remove(key) {
    localStorage.removeItem(`${PREFIX}${key}`);
  },
};
